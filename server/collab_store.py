import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable


DB_PATH = os.environ.get("COLLAB_DB_PATH", os.path.join(os.path.dirname(__file__), "collab.sqlite3"))
_LOCK = threading.RLock()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def _tx() -> Iterable[sqlite3.Connection]:
    with _LOCK:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_collab_db() -> None:
    with _tx() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS project_members (
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
                joined_at TEXT NOT NULL,
                PRIMARY KEY(project_id, user_id),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_channels (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'general',
                name TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(created_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                edited_at TEXT,
                deleted_at TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(channel_id) REFERENCES chat_channels(id) ON DELETE CASCADE,
                FOREIGN KEY(author_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS chat_attachments (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                message_id TEXT,
                uploader_id TEXT NOT NULL,
                source TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                file_name TEXT,
                size_bytes INTEGER NOT NULL,
                storage_provider TEXT NOT NULL,
                storage_key TEXT NOT NULL,
                public_url TEXT,
                context_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(message_id) REFERENCES chat_messages(id) ON DELETE CASCADE,
                FOREIGN KEY(uploader_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT,
                actor_id TEXT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pm_user ON project_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_channels_project ON chat_channels(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_channel ON chat_messages(channel_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_project ON chat_messages(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_attach_message ON chat_attachments(message_id, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_attach_project ON chat_attachments(project_id, created_at DESC);
            """
        )


def create_user(email: str, display_name: str, password_hash: str) -> dict[str, Any]:
    now = _utc_now_iso()
    user_id = str(uuid.uuid4())
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, display_name, password_hash, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (user_id, email.strip().lower(), display_name.strip(), password_hash, now, now),
        )
    return get_user_by_id(user_id) or {}


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _tx() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with _tx() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def create_project(name: str, created_by: str) -> dict[str, Any]:
    now = _utc_now_iso()
    project_id = str(uuid.uuid4())
    channel_id = str(uuid.uuid4())
    with _tx() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, created_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, name.strip(), created_by, now, now),
        )
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
            (project_id, created_by, now),
        )
        conn.execute(
            "INSERT INTO chat_channels (id, project_id, kind, name, created_by, created_at) VALUES (?, ?, 'general', 'Общий', ?, ?)",
            (channel_id, project_id, created_by, now),
        )
    return get_project(project_id) or {}


def get_project(project_id: str) -> dict[str, Any] | None:
    with _tx() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None


def list_projects_for_user(user_id: str) -> list[dict[str, Any]]:
    with _tx() as conn:
        rows = conn.execute(
            """
            SELECT p.*, pm.role
            FROM projects p
            JOIN project_members pm ON pm.project_id = p.id
            WHERE pm.user_id = ?
            ORDER BY p.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def add_member(project_id: str, user_id: str, role: str) -> None:
    now = _utc_now_iso()
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO project_members (project_id, user_id, role, joined_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role
            """,
            (project_id, user_id, role, now),
        )


def get_membership(project_id: str, user_id: str) -> dict[str, Any] | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def list_channels(project_id: str) -> list[dict[str, Any]]:
    with _tx() as conn:
        rows = conn.execute(
            "SELECT * FROM chat_channels WHERE project_id = ? ORDER BY created_at ASC",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_channel(project_id: str, kind: str, name: str, created_by: str) -> dict[str, Any]:
    now = _utc_now_iso()
    channel_id = str(uuid.uuid4())
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO chat_channels (id, project_id, kind, name, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (channel_id, project_id, kind, name.strip(), created_by, now),
        )
    with _tx() as conn:
        row = conn.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
        return dict(row) if row else {}


def list_messages(channel_id: str, limit: int = 50, before: str | None = None) -> list[dict[str, Any]]:
    with _tx() as conn:
        if before:
            rows = conn.execute(
                """
                SELECT * FROM chat_messages
                WHERE channel_id = ? AND created_at < ? AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (channel_id, before, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM chat_messages
                WHERE channel_id = ? AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (channel_id, limit),
            ).fetchall()
        out = [dict(r) for r in rows]
        out.reverse()
        _attach_message_attachments(conn, out)
        return out


def create_message(project_id: str, channel_id: str, author_id: str, body: str) -> dict[str, Any]:
    now = _utc_now_iso()
    msg_id = str(uuid.uuid4())
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages (id, project_id, channel_id, author_id, body, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (msg_id, project_id, channel_id, author_id, body.strip(), now),
        )
        conn.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (now, project_id),
        )
    with _tx() as conn:
        row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (msg_id,)).fetchone()
        msg = dict(row) if row else {}
        _attach_message_attachments(conn, [msg] if msg else [])
        return msg


def create_attachment(
    project_id: str,
    uploader_id: str,
    source: str,
    mime_type: str,
    file_name: str,
    size_bytes: int,
    storage_provider: str,
    storage_key: str,
    public_url: str | None = None,
    context_json: dict[str, Any] | None = None,
    attachment_id: str | None = None,
) -> dict[str, Any]:
    now = _utc_now_iso()
    attachment_id = attachment_id or str(uuid.uuid4())
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO chat_attachments (
                id, project_id, message_id, uploader_id, source, mime_type, file_name, size_bytes,
                storage_provider, storage_key, public_url, context_json, created_at
            )
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attachment_id,
                project_id,
                uploader_id,
                source,
                mime_type,
                file_name,
                int(size_bytes),
                storage_provider,
                storage_key,
                public_url,
                json.dumps(context_json or {}, ensure_ascii=False),
                now,
            ),
        )
    with _tx() as conn:
        row = conn.execute("SELECT * FROM chat_attachments WHERE id = ?", (attachment_id,)).fetchone()
        return _attachment_row_to_dict(row) if row else {}


def bind_attachments_to_message(project_id: str, message_id: str, attachment_ids: list[str]) -> None:
    if not attachment_ids:
        return
    with _tx() as conn:
        qmarks = ",".join("?" for _ in attachment_ids)
        rows = conn.execute(
            f"SELECT id, message_id FROM chat_attachments WHERE project_id = ? AND id IN ({qmarks})",
            (project_id, *attachment_ids),
        ).fetchall()
        found = {str(r["id"]): str(r["message_id"] or "") for r in rows}
        for aid in attachment_ids:
            if aid not in found:
                raise ValueError(f"Attachment not found in project: {aid}")
            if found[aid]:
                raise ValueError(f"Attachment already bound: {aid}")
        conn.execute(
            f"UPDATE chat_attachments SET message_id = ? WHERE project_id = ? AND id IN ({qmarks})",
            (message_id, project_id, *attachment_ids),
        )


def get_attachment(project_id: str, attachment_id: str) -> dict[str, Any] | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM chat_attachments WHERE project_id = ? AND id = ?",
            (project_id, attachment_id),
        ).fetchone()
        return _attachment_row_to_dict(row) if row else None


def _attachment_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if not row:
        return {}
    data = dict(row)
    try:
        data["context_json"] = json.loads(data.get("context_json") or "{}")
    except Exception:
        data["context_json"] = {}
    return data


def _attach_message_attachments(conn: sqlite3.Connection, messages: list[dict[str, Any]]) -> None:
    if not messages:
        return
    ids = [m.get("id") for m in messages if m.get("id")]
    if not ids:
        return
    qmarks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM chat_attachments WHERE message_id IN ({qmarks}) ORDER BY created_at ASC",
        ids,
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        rd = _attachment_row_to_dict(r)
        grouped.setdefault(str(rd.get("message_id", "")), []).append(rd)
    for msg in messages:
        msg["attachments"] = grouped.get(str(msg.get("id", "")), [])


def write_audit(project_id: str | None, actor_id: str | None, action: str, entity_type: str, entity_id: str | None, payload: dict[str, Any] | None = None) -> None:
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (project_id, actor_id, action, entity_type, entity_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                actor_id,
                action,
                entity_type,
                entity_id,
                json.dumps(payload or {}, ensure_ascii=False),
                _utc_now_iso(),
            ),
        )
