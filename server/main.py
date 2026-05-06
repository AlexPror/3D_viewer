import hashlib
import os
import re
from pathlib import Path
from typing import Any

import json
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from spec_builder import build_spec_from_assembly
from kompas_metadata import read_kompas_metadata, build_assembly_map
from collab_auth import create_token, decode_token, hash_password, token_expiration_iso, verify_password
from collab_store import (
    add_member,
    bind_attachments_to_message,
    create_channel,
    create_attachment,
    create_message,
    create_project,
    create_user,
    get_attachment,
    get_membership,
    get_user_by_email,
    get_user_by_id,
    init_collab_db,
    list_channels,
    list_messages,
    list_projects_for_user,
    write_audit,
)

try:
    from step_to_glb import step_to_glb_bytes, is_server_conversion_available
except Exception:
    step_to_glb_bytes = None
    is_server_conversion_available = lambda: False


app = FastAPI(title="3d_viewer local server", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_cache: dict[str, Any] = {}

init_collab_db()


_re_x2 = re.compile(r"\\X2\\([0-9A-Fa-f]+)\\X0\\")


def _decode_step_x2(s: str) -> str:
    """Decode STEP Part21 extended encoding \\X2\\...\\X0\\ (UTF-16BE hex)."""

    def repl(m: re.Match[str]) -> str:
        hex_str = m.group(1)
        try:
            b = bytes.fromhex(hex_str)
            return b.decode("utf-16-be", errors="replace")
        except Exception:
            return m.group(0)

    return _re_x2.sub(repl, s)


def _unescape_step_string(s: str) -> str:
    # STEP uses doubled apostrophe to escape single quote inside strings.
    return s.replace("''", "'")


def _decode_text(data: bytes) -> str:
    # Most exports are UTF-8, but some can be legacy; fallback to latin-1.
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


_re_product = re.compile(
    r"PRODUCT\s*\(\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'",
    re.IGNORECASE,
)


def parse_products(step_text: str) -> list[dict[str, str]]:
    products: list[dict[str, str]] = []
    for m in _re_product.finditer(step_text):
        designation = _decode_step_x2(_unescape_step_string(m.group(1))).strip()
        name = _decode_step_x2(_unescape_step_string(m.group(2))).strip()
        description = _decode_step_x2(_unescape_step_string(m.group(3))).strip()
        products.append(
            {
                "designation": designation,
                "name": name,
                "description": description,
            }
        )
    return products


_re_entity = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;", re.IGNORECASE | re.DOTALL)


def _iter_entities(step_text: str) -> list[tuple[int, str, str]]:
    """Return a list of (id, entityNameUpper, argsString) for DATA section."""
    entities: list[tuple[int, str, str]] = []
    for m in _re_entity.finditer(step_text):
        entities.append((int(m.group(1)), m.group(2).upper(), m.group(3).strip()))
    return entities


def _first_strings(args: str, n: int) -> list[str]:
    """Extract first N STEP strings from args (handles doubled quotes)."""
    out: list[str] = []
    i = 0
    L = len(args)
    while i < L and len(out) < n:
        if args[i] != "'":
            i += 1
            continue
        i += 1
        buf = []
        while i < L:
            ch = args[i]
            if ch == "'":
                if i + 1 < L and args[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                i += 1
                break
            buf.append(ch)
            i += 1
        out.append(_decode_step_x2("".join(buf)))
    return out


def _last_two_refs(args: str) -> tuple[int | None, int | None]:
    refs = [int(x) for x in re.findall(r"#(\d+)", args)]
    if len(refs) < 2:
        return None, None
    return refs[-2], refs[-1]


def _last_ref(args: str) -> int | None:
    m = re.findall(r"#(\d+)", args)
    return int(m[-1]) if m else None


def build_assembly(step_text: str) -> dict[str, Any]:
    """
    Best-effort assembly extraction for STEP AP214/AP242:
    PRODUCT -> PRODUCT_DEFINITION_FORMATION -> PRODUCT_DEFINITION
    NEXT_ASSEMBLY_USAGE_OCCURRENCE links parent/child PRODUCT_DEFINITION.
    """
    entities = _iter_entities(step_text)

    product_by_id: dict[int, dict[str, str]] = {}
    pdf_to_product: dict[int, int] = {}
    pd_to_pdf: dict[int, int] = {}
    nauo_edges: list[tuple[int, int]] = []

    for ent_id, ent, args in entities:
        if ent == "PRODUCT":
            s = _first_strings(args, 3)
            designation = _unescape_step_string(s[0] if len(s) > 0 else "").strip()
            name = _unescape_step_string(s[1] if len(s) > 1 else "").strip()
            description = _unescape_step_string(s[2] if len(s) > 2 else "").strip()
            product_by_id[ent_id] = {
                "designation": designation,
                "name": name,
                "description": description,
            }
        elif ent == "PRODUCT_DEFINITION_FORMATION":
            prod_id = _last_ref(args)
            if prod_id is not None:
                pdf_to_product[ent_id] = prod_id
        elif ent == "PRODUCT_DEFINITION":
            pdf_id = _last_ref(args)
            if pdf_id is not None:
                pd_to_pdf[ent_id] = pdf_id
        elif ent == "NEXT_ASSEMBLY_USAGE_OCCURRENCE":
            parent_pd, child_pd = _last_two_refs(args)
            if parent_pd is not None and child_pd is not None:
                nauo_edges.append((parent_pd, child_pd))

    def pd_to_product(pd_id: int) -> dict[str, str] | None:
        pdf_id = pd_to_pdf.get(pd_id)
        if pdf_id is None:
            return None
        prod_id = pdf_to_product.get(pdf_id)
        if prod_id is None:
            return None
        return product_by_id.get(prod_id)

    # Build occurrence edges on product level
    prod_edges: list[tuple[str, str]] = []
    prod_nodes: dict[str, dict[str, str]] = {}
    for p_pd, c_pd in nauo_edges:
        p = pd_to_product(p_pd)
        c = pd_to_product(c_pd)
        if not p or not c:
            continue
        p_key = f"{p.get('designation','')}|{p.get('name','')}"
        c_key = f"{c.get('designation','')}|{c.get('name','')}"
        prod_nodes[p_key] = p
        prod_nodes[c_key] = c
        prod_edges.append((p_key, c_key))

    children: dict[str, list[str]] = {}
    indeg: dict[str, int] = {k: 0 for k in prod_nodes}
    for a, b in prod_edges:
        children.setdefault(a, []).append(b)
        indeg[b] = indeg.get(b, 0) + 1
        indeg.setdefault(a, indeg.get(a, 0))

    roots = [k for k, d in indeg.items() if d == 0] or list(prod_nodes.keys())[:1]

    def build_tree(node: str, depth: int = 0) -> dict[str, Any]:
        info = prod_nodes.get(node, {"designation": "", "name": "", "description": ""})
        ch = children.get(node, [])
        # aggregate counts per direct child
        cnt: dict[str, int] = {}
        for c in ch:
            cnt[c] = cnt.get(c, 0) + 1
        return {
            "key": node,
            "designation": info.get("designation", ""),
            "name": info.get("name", ""),
            "description": info.get("description", ""),
            "children": [
                {**build_tree(c, depth + 1), "qty": cnt.get(c, 1)} for c in sorted(cnt.keys())
            ],
        }

    trees = [build_tree(r) for r in roots]
    return {
        "roots": roots,
        "trees": trees,
        "edge_count": len(prod_edges),
        "node_count": len(prod_nodes),
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/step/metadata")
async def step_metadata(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    digest = hashlib.sha1(data).hexdigest()
    if digest in _cache:
        return _cache[digest]

    text = _decode_text(data)
    products = parse_products(text)
    assembly = build_assembly(text)
    spec = build_spec_from_assembly(assembly, products)

    # De-dup by (designation, name, description) while preserving order.
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for p in products:
        key = (p["designation"], p["name"], p["description"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    res = {
        "filename": file.filename,
        "sha1": digest,
        "product_count": len(products),
        "unique_product_count": len(unique),
        "products": unique,
        "assembly": assembly,
        "spec": spec,
    }
    _cache[digest] = res
    return res


# Лимит размера STEP для серверной конвертации (байты), 100 МБ
STEP_TO_GLB_MAX_BYTES = 100 * 1024 * 1024


def _discover_a3d_files(root_dir: str) -> list[dict[str, Any]]:
    """
    Рекурсивно находит .a3d в папке.
    Возвращает отсортированный список (сначала самые новые).
    """
    root = Path(root_dir).expanduser()
    if not root.exists() or not root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for p in root.rglob("*.a3d"):
        try:
            st = p.stat()
            found.append(
                {
                    "name": p.name,
                    "path": str(p.resolve()),
                    "dir": str(p.parent.resolve()),
                    "size_bytes": int(st.st_size),
                    "mtime": float(st.st_mtime),
                }
            )
        except Exception:
            continue
    found.sort(key=lambda x: x["mtime"], reverse=True)
    return found


@app.get("/api/convert/step-to-glb/status")
def convert_step_to_glb_status() -> dict[str, Any]:
    """Проверка: доступна ли серверная конвертация STEP → GLB."""
    return {
        "available": is_server_conversion_available(),
        "max_file_bytes": STEP_TO_GLB_MAX_BYTES,
    }


@app.post("/api/convert/step-to-glb")
async def convert_step_to_glb(file: UploadFile = File(...)) -> Response:
    """
    Конвертация STEP/STP в GLB на сервере (для больших файлов).
    Возвращает бинарный GLB или 501/413/500.
    """
    if step_to_glb_bytes is None or not is_server_conversion_available():
        return Response(
            content=b"Server conversion not available (install cadquery and trimesh)",
            status_code=501,
            media_type="text/plain",
        )
    data = await file.read()
    if len(data) > STEP_TO_GLB_MAX_BYTES:
        return Response(
            content=f"File too large (max {STEP_TO_GLB_MAX_BYTES // (1024*1024)} MB)".encode(),
            status_code=413,
            media_type="text/plain",
        )
    glb_bytes = step_to_glb_bytes(data)
    if glb_bytes is None:
        return Response(
            content=b"Conversion failed",
            status_code=500,
            media_type="text/plain",
        )
    return Response(content=glb_bytes, media_type="model/gltf-binary")


@app.get("/api/convert/jt/status")
def convert_jt_status() -> dict[str, Any]:
    """
    Явный статус JT-конвертации.
    Пока конвертер не встроен в локальный backend.
    """
    return {
        "available": False,
        "message": "JT conversion is not configured on this backend",
    }


@app.post("/api/convert/jt")
async def convert_jt(file: UploadFile = File(...)) -> Response:
    """
    Заглушка для JT-конвертации.
    Нужен внешний сервис или отдельный модуль конвертации JT -> GLB.
    """
    _ = await file.read()
    return Response(
        content=b"JT conversion endpoint is not configured. Set VITE_CONVERTER_URL to external JT converter.",
        status_code=501,
        media_type="text/plain",
    )


@app.get("/api/kompas/assemblies/resolve")
def resolve_kompas_assemblies(root_dir: str) -> dict[str, Any]:
    """
    Сценарий:
    - 0 сборок -> mode='none'
    - 1 сборка -> mode='auto', selected=...
    - >1 сборки -> mode='select', assemblies=[...]
    """
    assemblies = _discover_a3d_files(root_dir)
    if not assemblies:
        return {
            "mode": "none",
            "root_dir": os.path.abspath(os.path.expanduser(root_dir)),
            "assemblies": [],
            "message": "Сборки .a3d не найдены",
        }
    if len(assemblies) == 1:
        return {
            "mode": "auto",
            "root_dir": os.path.abspath(os.path.expanduser(root_dir)),
            "selected": assemblies[0],
            "count": 1,
        }
    return {
        "mode": "select",
        "root_dir": os.path.abspath(os.path.expanduser(root_dir)),
        "assemblies": assemblies,
        "count": len(assemblies),
    }


@app.get("/api/kompas/metadata")
def kompas_metadata(assembly_path: str) -> dict[str, Any]:
    """
    Читает metadata напрямую из сборки КОМПАС (.a3d).
    Возвращает parts/instances/meshBindings/tree/bom для фронтенда.
    """
    try:
        meta = read_kompas_metadata(assembly_path)
        return {
            "ok": True,
            "mode": "direct",
            "metadata": meta,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "assembly_path": os.path.abspath(os.path.expanduser(assembly_path)),
        }


@app.get("/api/kompas/metadata/auto")
def kompas_metadata_auto(root_dir: str) -> dict[str, Any]:
    """
    Режим автовыбора:
    - если сборка одна: сразу возвращаем metadata;
    - если несколько: отдаём список на выбор;
    - если нет: mode='none'.
    """
    resolved = resolve_kompas_assemblies(root_dir)
    mode = resolved.get("mode")
    if mode == "none":
        return {
            "ok": False,
            "mode": "none",
            "root_dir": resolved.get("root_dir"),
            "assemblies": [],
            "message": resolved.get("message", "Сборки .a3d не найдены"),
        }
    if mode == "select":
        return {
            "ok": True,
            "mode": "select",
            "root_dir": resolved.get("root_dir"),
            "assemblies": resolved.get("assemblies", []),
            "count": resolved.get("count", 0),
        }

    selected = resolved.get("selected") or {}
    selected_path = selected.get("path")
    if not selected_path:
        return {
            "ok": False,
            "mode": "error",
            "error": "Resolve returned auto mode without selected.path",
            "root_dir": resolved.get("root_dir"),
        }

    try:
        meta = read_kompas_metadata(selected_path)
        return {
            "ok": True,
            "mode": "auto",
            "selected": selected,
            "metadata": meta,
        }
    except Exception as e:
        return {
            "ok": False,
            "mode": "auto",
            "selected": selected,
            "error": str(e),
        }


@app.get("/api/kompas/assembly-map")
def kompas_assembly_map(assembly_path: str) -> dict[str, Any]:
    """
    Контракт для будущего матчинга:
    parts/instances/tree/bom + signatures.
    """
    try:
        return {
            "ok": True,
            "mode": "direct",
            "assemblyMap": build_assembly_map(assembly_path),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "assembly_path": os.path.abspath(os.path.expanduser(assembly_path)),
        }


@app.get("/api/kompas/assembly-map/auto")
def kompas_assembly_map_auto(root_dir: str) -> dict[str, Any]:
    """
    Авто-режим для assembly-map:
    - none/select/auto так же, как metadata.
    """
    resolved = resolve_kompas_assemblies(root_dir)
    mode = resolved.get("mode")
    if mode == "none":
        return {
            "ok": False,
            "mode": "none",
            "root_dir": resolved.get("root_dir"),
            "assemblies": [],
            "message": resolved.get("message", "Сборки .a3d не найдены"),
        }
    if mode == "select":
        return {
            "ok": True,
            "mode": "select",
            "root_dir": resolved.get("root_dir"),
            "assemblies": resolved.get("assemblies", []),
            "count": resolved.get("count", 0),
        }
    selected = resolved.get("selected") or {}
    selected_path = selected.get("path")
    if not selected_path:
        return {
            "ok": False,
            "mode": "error",
            "error": "Resolve returned auto mode without selected.path",
            "root_dir": resolved.get("root_dir"),
        }
    try:
        return {
            "ok": True,
            "mode": "auto",
            "selected": selected,
            "assemblyMap": build_assembly_map(selected_path),
        }
    except Exception as e:
        return {
            "ok": False,
            "mode": "auto",
            "selected": selected,
            "error": str(e),
        }


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(min_length=2, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class AddMemberRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    role: str = Field(default="viewer", pattern="^(owner|editor|viewer)$")


class CreateChannelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="general", pattern="^(general|module|thread)$")


class CreateMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    attachment_ids: list[str] = Field(default_factory=list, alias="attachmentIds")


def _extract_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    return token


def _current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    token = _extract_token(authorization)
    payload = decode_token(token)
    user_id = str(payload.get("sub", ""))
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token subject")
    user = get_user_by_id(user_id)
    if not user or not bool(user.get("is_active", 0)):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def _require_project_member(project_id: str, user_id: str) -> dict[str, Any]:
    membership = get_membership(project_id, user_id)
    if not membership:
        raise HTTPException(status_code=403, detail="Project access denied")
    return membership


@app.post("/api/auth/register")
def auth_register(payload: RegisterRequest) -> dict[str, Any]:
    exists = get_user_by_email(payload.email)
    if exists:
        raise HTTPException(status_code=409, detail="User already exists")
    user = create_user(
        email=str(payload.email),
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
    )
    token = create_token(user)
    write_audit(None, user.get("id"), "auth.register", "user", user.get("id"), {"email": user.get("email")})
    return {
        "ok": True,
        "token": token,
        "expiresAt": token_expiration_iso(),
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "displayName": user.get("display_name"),
        },
    }


@app.post("/api/auth/login")
def auth_login(payload: LoginRequest) -> dict[str, Any]:
    user = get_user_by_email(str(payload.email))
    if not user or not verify_password(payload.password, str(user.get("password_hash", ""))):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not bool(user.get("is_active", 0)):
        raise HTTPException(status_code=403, detail="User is inactive")
    token = create_token(user)
    write_audit(None, user.get("id"), "auth.login", "user", user.get("id"), None)
    return {
        "ok": True,
        "token": token,
        "expiresAt": token_expiration_iso(),
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "displayName": user.get("display_name"),
        },
    }


@app.get("/api/me")
def me(user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    return {
        "ok": True,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "displayName": user.get("display_name"),
        },
    }


@app.get("/api/projects")
def projects_list(user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    projects = list_projects_for_user(str(user["id"]))
    return {"ok": True, "projects": projects}


@app.post("/api/projects")
def projects_create(payload: CreateProjectRequest, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    project = create_project(payload.name, str(user["id"]))
    write_audit(project.get("id"), user.get("id"), "project.create", "project", project.get("id"), {"name": payload.name})
    return {"ok": True, "project": project}


@app.post("/api/projects/{project_id}/members")
def projects_add_member(project_id: str, payload: AddMemberRequest, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    membership = _require_project_member(project_id, str(user["id"]))
    if membership.get("role") not in ("owner", "editor"):
        raise HTTPException(status_code=403, detail="Only owner/editor can add members")
    target = get_user_by_email(str(payload.email))
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")
    if payload.role == "owner" and membership.get("role") != "owner":
        raise HTTPException(status_code=403, detail="Only owner can assign owner role")
    add_member(project_id, str(target["id"]), payload.role)
    write_audit(project_id, user.get("id"), "project.member.upsert", "membership", str(target["id"]), {"role": payload.role})
    return {"ok": True}


@app.get("/api/projects/{project_id}/channels")
def channels_list(project_id: str, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    return {"ok": True, "channels": list_channels(project_id)}


@app.post("/api/projects/{project_id}/channels")
def channels_create(project_id: str, payload: CreateChannelRequest, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    membership = _require_project_member(project_id, str(user["id"]))
    if membership.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewer cannot create channels")
    channel = create_channel(project_id, payload.kind, payload.name, str(user["id"]))
    write_audit(project_id, user.get("id"), "chat.channel.create", "channel", channel.get("id"), {"kind": payload.kind, "name": payload.name})
    return {"ok": True, "channel": channel}


@app.get("/api/projects/{project_id}/channels/{channel_id}/messages")
def messages_list(project_id: str, channel_id: str, limit: int = 50, before: str | None = None, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    safe_limit = min(200, max(1, int(limit)))
    return {"ok": True, "messages": list_messages(channel_id, safe_limit, before)}


@app.post("/api/projects/{project_id}/channels/{channel_id}/messages")
def messages_create(project_id: str, channel_id: str, payload: CreateMessageRequest, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    membership = _require_project_member(project_id, str(user["id"]))
    if membership.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewer cannot send messages")
    msg = create_message(project_id, channel_id, str(user["id"]), payload.body)
    if payload.attachment_ids:
        try:
            bind_attachments_to_message(project_id, str(msg.get("id", "")), payload.attachment_ids)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # reload with attachments
        msgs = list_messages(channel_id, limit=1)
        if msgs:
            msg = msgs[-1]
    write_audit(project_id, user.get("id"), "chat.message.create", "message", msg.get("id"), {"channelId": channel_id})
    return {"ok": True, "message": msg}


_ATTACH_ROOT = Path(__file__).resolve().parent / "uploads" / "chat"
_ATTACH_MAX_BYTES = 20 * 1024 * 1024
_ATTACH_ALLOWED_MIME = {"image/png", "image/jpeg", "image/webp"}


@app.post("/api/projects/{project_id}/attachments/upload")
async def upload_attachment(
    project_id: str,
    file: UploadFile = File(...),
    source: str = Form(default="other"),
    context_json: str = Form(default="{}"),
    user: dict[str, Any] = Depends(_current_user),
) -> dict[str, Any]:
    membership = _require_project_member(project_id, str(user["id"]))
    if membership.get("role") == "viewer":
        raise HTTPException(status_code=403, detail="Viewer cannot upload attachments")
    mime = (file.content_type or "").lower().strip()
    if mime not in _ATTACH_ALLOWED_MIME:
        raise HTTPException(status_code=400, detail=f"Unsupported mime type: {mime}")
    data = await file.read()
    if len(data) > _ATTACH_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Attachment is too large")
    try:
        context = json.loads(context_json) if context_json else {}
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid context_json") from e
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        ext = ".png" if mime == "image/png" else ".jpg" if mime == "image/jpeg" else ".webp"
    attach_id = str(uuid.uuid4())
    project_dir = _ATTACH_ROOT / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    local_name = f"{attach_id}{ext}"
    local_path = project_dir / local_name
    with local_path.open("wb") as f:
        f.write(data)
    rec = create_attachment(
        project_id=project_id,
        uploader_id=str(user["id"]),
        source=(source or "other")[:32],
        mime_type=mime,
        file_name=file.filename or local_name,
        size_bytes=len(data),
        storage_provider="local",
        storage_key=str(local_path),
        public_url=f"/api/projects/{project_id}/attachments/{attach_id}",
        context_json=context if isinstance(context, dict) else {"value": context},
        attachment_id=attach_id,
    )
    write_audit(project_id, user.get("id"), "chat.attachment.upload", "attachment", rec.get("id"), {"source": source})
    return {"ok": True, "attachment": rec}


@app.get("/api/projects/{project_id}/attachments/{attachment_id}")
def get_attachment_file(project_id: str, attachment_id: str, user: dict[str, Any] = Depends(_current_user)) -> FileResponse:
    _require_project_member(project_id, str(user["id"]))
    rec = get_attachment(project_id, attachment_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = str(rec.get("storage_key") or "")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Attachment file is missing")
    return FileResponse(path=path, media_type=str(rec.get("mime_type") or "application/octet-stream"), filename=str(rec.get("file_name") or "attachment"))

