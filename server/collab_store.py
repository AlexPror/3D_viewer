import json
import os
from collections import defaultdict
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable


DB_PATH = os.environ.get("COLLAB_DB_PATH", os.path.join(os.path.dirname(__file__), "collab.sqlite3"))
_LOCK = threading.RLock()

# API / DB slugs (UI labels are in the viewer)
PROJECT_MEMBER_ROLES: tuple[str, ...] = (
    "gip",
    "chief_designer",
    "designer",
    "installer",
    "assembler",
    "client",
)


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


def _migrate_project_members_roles(conn: sqlite3.Connection) -> None:
    """Replace owner/editor/viewer with engineering roles (one-time rebuild)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='project_members'"
    ).fetchone()
    if not row or not row[0]:
        return
    ddl = row[0]
    if "'gip'" in ddl:
        return
    roles_csv = ",".join(f"'{r}'" for r in PROJECT_MEMBER_ROLES)
    conn.executescript(
        f"""
        PRAGMA foreign_keys=OFF;
        CREATE TABLE project_members_new (
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ({roles_csv})),
            joined_at TEXT NOT NULL,
            PRIMARY KEY(project_id, user_id),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        INSERT INTO project_members_new SELECT
            project_id,
            user_id,
            CASE role
                WHEN 'owner' THEN 'gip'
                WHEN 'editor' THEN 'chief_designer'
                WHEN 'viewer' THEN 'client'
                WHEN 'gip' THEN 'gip'
                WHEN 'chief_designer' THEN 'chief_designer'
                WHEN 'designer' THEN 'designer'
                WHEN 'installer' THEN 'installer'
                WHEN 'assembler' THEN 'assembler'
                WHEN 'client' THEN 'client'
                ELSE 'client'
            END,
            joined_at
        FROM project_members;
        DROP TABLE project_members;
        ALTER TABLE project_members_new RENAME TO project_members;
        CREATE INDEX IF NOT EXISTS idx_pm_user ON project_members(user_id);
        PRAGMA foreign_keys=ON;
        """
    )


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
                role TEXT NOT NULL CHECK(role IN ('gip','chief_designer','designer','installer','assembler','client')),
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

            CREATE TABLE IF NOT EXISTS message_reads (
                project_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                last_read_at TEXT NOT NULL,
                last_read_msg_id TEXT,
                PRIMARY KEY(project_id, channel_id, user_id),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(channel_id) REFERENCES chat_channels(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(last_read_msg_id) REFERENCES chat_messages(id) ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pm_user ON project_members(user_id);
            CREATE INDEX IF NOT EXISTS idx_channels_project ON chat_channels(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_channel ON chat_messages(channel_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_project ON chat_messages(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_attach_message ON chat_attachments(message_id, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_attach_project ON chat_attachments(project_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_reads_project_channel ON message_reads(project_id, channel_id, last_read_at DESC);

            CREATE TABLE IF NOT EXISTS project_telemost (
                project_id TEXT PRIMARY KEY,
                conference_id TEXT NOT NULL,
                join_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS project_asset_pairs (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                pdf_attachment_id TEXT,
                model_attachment_id TEXT,
                pdf_stem TEXT NOT NULL,
                model_stem TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(pdf_attachment_id) REFERENCES chat_attachments(id) ON DELETE SET NULL,
                FOREIGN KEY(model_attachment_id) REFERENCES chat_attachments(id) ON DELETE SET NULL,
                FOREIGN KEY(created_by) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_asset_pairs_project ON project_asset_pairs(project_id, created_at DESC);
            """
        )
        _migrate_project_members_roles(conn)


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
            "INSERT INTO project_members (project_id, user_id, role, joined_at) VALUES (?, ?, 'gip', ?)",
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


def count_project_members(project_id: str) -> int:
    with _tx() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM project_members WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return int(row["c"]) if row and row["c"] is not None else 0


def count_role_in_project(project_id: str, role: str) -> int:
    with _tx() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM project_members WHERE project_id = ? AND role = ?",
            (project_id, role),
        ).fetchone()
        return int(row["c"]) if row and row["c"] is not None else 0


def delete_project_member(project_id: str, user_id: str) -> bool:
    with _tx() as conn:
        cur = conn.execute(
            "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        return cur.rowcount > 0


def get_membership(project_id: str, user_id: str) -> dict[str, Any] | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def list_project_members(project_id: str) -> list[dict[str, Any]]:
    with _tx() as conn:
        rows = conn.execute(
            """
            SELECT u.id AS id, u.email AS email, u.display_name AS display_name,
                   pm.role AS role, pm.joined_at AS joined_at
            FROM project_members pm
            JOIN users u ON u.id = pm.user_id
            WHERE pm.project_id = ?
            ORDER BY pm.joined_at ASC
            """,
            (project_id,),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            result.append(
                {
                    "id": d["id"],
                    "email": d["email"],
                    "displayName": d["display_name"],
                    "role": d["role"],
                    "joinedAt": d["joined_at"],
                }
            )
        return result


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
        _enrich_messages_authors(conn, out)
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
        _enrich_messages_authors(conn, [msg] if msg else [])
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


def upsert_message_read(project_id: str, channel_id: str, user_id: str, last_read_msg_id: str | None = None) -> dict[str, Any]:
    now = _utc_now_iso()
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO message_reads (project_id, channel_id, user_id, last_read_at, last_read_msg_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(project_id, channel_id, user_id)
            DO UPDATE SET
                last_read_at = excluded.last_read_at,
                last_read_msg_id = excluded.last_read_msg_id
            """,
            (project_id, channel_id, user_id, now, last_read_msg_id),
        )
        row = conn.execute(
            """
            SELECT * FROM message_reads
            WHERE project_id = ? AND channel_id = ? AND user_id = ?
            """,
            (project_id, channel_id, user_id),
        ).fetchone()
    return dict(row) if row else {}


def _attachment_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if not row:
        return {}
    data = dict(row)
    try:
        data["context_json"] = json.loads(data.get("context_json") or "{}")
    except Exception:
        data["context_json"] = {}
    # Удобные дубликаты для JSON/TS (camelCase)
    if data.get("file_name") is not None:
        data["fileName"] = data["file_name"]
    if data.get("mime_type") is not None:
        data["mimeType"] = data["mime_type"]
    if data.get("size_bytes") is not None:
        data["sizeBytes"] = data["size_bytes"]
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


def _enrich_messages_authors(conn: sqlite3.Connection, messages: list[dict[str, Any]]) -> None:
    if not messages:
        return
    author_ids = list({str(m.get("author_id", "")) for m in messages if m.get("author_id")})
    if not author_ids:
        return
    qmarks = ",".join("?" for _ in author_ids)
    rows = conn.execute(
        f"SELECT id, email, display_name FROM users WHERE id IN ({qmarks})",
        author_ids,
    ).fetchall()
    by_id: dict[str, dict[str, Any]] = {str(r["id"]): dict(r) for r in rows}

    role_lookup: dict[str, dict[str, str]] = {}
    project_ids = {str(m.get("project_id", "")) for m in messages if m.get("project_id")}
    for pid in project_ids:
        if not pid:
            continue
        aids_for_p = list(
            {
                str(m.get("author_id", ""))
                for m in messages
                if str(m.get("project_id", "")) == pid and m.get("author_id")
            }
        )
        if not aids_for_p:
            continue
        qm = ",".join("?" for _ in aids_for_p)
        proles = conn.execute(
            f"SELECT user_id, role FROM project_members WHERE project_id = ? AND user_id IN ({qm})",
            (pid, *aids_for_p),
        ).fetchall()
        role_lookup[pid] = {str(r["user_id"]): str(r["role"]) for r in proles}

    for msg in messages:
        aid = str(msg.get("author_id", ""))
        pid = str(msg.get("project_id", ""))
        proj_role = role_lookup.get(pid, {}).get(aid) if pid and aid else None
        u = by_id.get(aid)
        if u:
            dn = u.get("display_name") or ""
            em = u.get("email") or ""
            author_obj: dict[str, Any] = {
                "id": aid,
                "email": em,
                "displayName": dn,
                "display_name": dn,
            }
            if proj_role:
                author_obj["projectRole"] = proj_role
                author_obj["project_role"] = proj_role
            msg["author"] = author_obj
            msg["authorDisplayName"] = dn
            msg["authorEmail"] = em
        if proj_role:
            msg["authorProjectRole"] = proj_role


def get_project_telemost(project_id: str) -> dict[str, Any] | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT project_id, conference_id, join_url, created_at FROM project_telemost WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return dict(row) if row else None


def stem_filename(name: str) -> str:
    base = os.path.basename(name.strip())
    if not base:
        return ""
    dot = base.rfind(".")
    return base[:dot].lower() if dot > 0 else base.lower()


def _attachment_kind(file_name: str) -> str | None:
    lower = file_name.lower()
    if lower.endswith(".pdf"):
        return "pdf"
    for ext in (".glb", ".gltf", ".stl", ".stp", ".step", ".iges", ".igs"):
        if lower.endswith(ext):
            return "model"
    return None


def list_project_attachments(project_id: str, limit: int = 800) -> list[dict[str, Any]]:
    with _tx() as conn:
        rows = conn.execute(
            """
            SELECT * FROM chat_attachments
            WHERE project_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (project_id, limit),
        ).fetchall()
        return [_attachment_row_to_dict(r) for r in rows]


def _asset_pair_row(row: sqlite3.Row | None) -> dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    if d.get("pdf_attachment_id"):
        d["pdfAttachmentId"] = d["pdf_attachment_id"]
    if d.get("model_attachment_id"):
        d["modelAttachmentId"] = d["model_attachment_id"]
    d["pdfStem"] = d.get("pdf_stem")
    d["modelStem"] = d.get("model_stem")
    return d


def list_asset_pairs(project_id: str) -> list[dict[str, Any]]:
    with _tx() as conn:
        rows = conn.execute(
            """
            SELECT * FROM project_asset_pairs
            WHERE project_id = ?
            ORDER BY created_at DESC
            """,
            (project_id,),
        ).fetchall()
        return [_asset_pair_row(r) for r in rows]


def get_asset_pair(project_id: str, pair_id: str) -> dict[str, Any] | None:
    with _tx() as conn:
        row = conn.execute(
            "SELECT * FROM project_asset_pairs WHERE project_id = ? AND id = ?",
            (project_id, pair_id),
        ).fetchone()
        return _asset_pair_row(row) if row else None


def create_asset_pair(
    project_id: str,
    created_by: str,
    *,
    pdf_attachment_id: str | None,
    model_attachment_id: str | None,
    pdf_stem: str,
    model_stem: str,
) -> dict[str, Any]:
    pair_id = str(uuid.uuid4())
    now = _utc_now_iso()
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO project_asset_pairs (
                id, project_id, pdf_attachment_id, model_attachment_id,
                pdf_stem, model_stem, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pair_id,
                project_id,
                pdf_attachment_id,
                model_attachment_id,
                pdf_stem.strip(),
                model_stem.strip(),
                created_by,
                now,
                now,
            ),
        )
    return get_asset_pair(project_id, pair_id) or {}


def delete_asset_pair(project_id: str, pair_id: str) -> bool:
    with _tx() as conn:
        cur = conn.execute(
            "DELETE FROM project_asset_pairs WHERE project_id = ? AND id = ?",
            (project_id, pair_id),
        )
        return cur.rowcount > 0


def suggest_asset_pair_candidates(project_id: str) -> list[dict[str, Any]]:
    """Пары с одинаковым stem имени файла (без расширения): например чертеж.pdf и чертеж.glb."""
    attachments = list_project_attachments(project_id)
    pairs_existing = list_asset_pairs(project_id)
    used_pdf = {str(p.get("pdf_attachment_id")) for p in pairs_existing if p.get("pdf_attachment_id")}
    used_model = {str(p.get("model_attachment_id")) for p in pairs_existing if p.get("model_attachment_id")}

    pdf_by_stem: dict[str, list[dict[str, str]]] = defaultdict(list)
    model_by_stem: dict[str, list[dict[str, str]]] = defaultdict(list)

    for a in attachments:
        aid = str(a.get("id") or "")
        fn = str(a.get("file_name") or "")
        if not aid or not fn:
            continue
        kind = _attachment_kind(fn)
        stem = stem_filename(fn)
        if not stem or not kind:
            continue
        entry = {"id": aid, "stem": stem, "fileName": fn}
        if kind == "pdf":
            pdf_by_stem[stem].append(entry)
        else:
            model_by_stem[stem].append(entry)

    out: list[dict[str, Any]] = []
    for stem in pdf_by_stem:
        if stem not in model_by_stem:
            continue
        pl = pdf_by_stem[stem]
        ml = model_by_stem[stem]
        n = min(len(pl), len(ml))
        for i in range(n):
            p, m = pl[i], ml[i]
            if p["id"] in used_pdf or m["id"] in used_model:
                continue
            out.append(
                {
                    "pdfAttachmentId": p["id"],
                    "modelAttachmentId": m["id"],
                    "pdfStem": stem,
                    "modelStem": stem,
                    "reason": "exact_stem",
                    "pdfFileName": p["fileName"],
                    "modelFileName": m["fileName"],
                }
            )
            used_pdf.add(p["id"])
            used_model.add(m["id"])
    return out


def upsert_project_telemost(project_id: str, conference_id: str, join_url: str) -> None:
    now = _utc_now_iso()
    with _tx() as conn:
        conn.execute(
            """
            INSERT INTO project_telemost (project_id, conference_id, join_url, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                conference_id = excluded.conference_id,
                join_url = excluded.join_url,
                created_at = excluded.created_at
            """,
            (project_id, conference_id, join_url, now),
        )


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
