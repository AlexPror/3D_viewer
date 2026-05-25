import hashlib
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import json
import uuid
from pathlib import Path

import asyncio

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from spec_builder import build_spec_from_assembly
from kompas_metadata import read_kompas_metadata, build_assembly_map
from collab_auth import create_token, decode_token, hash_password, token_expiration_iso, verify_password, warn_if_default_auth_secret
from yadisk_routes import router as yadisk_router
from collab_store import (
    PROJECT_MEMBER_ROLES,
    add_member,
    bind_attachments_to_message,
    create_channel,
    create_attachment,
    create_message,
    create_project,
    create_user,
    get_attachment,
    get_membership,
    get_project_telemost,
    get_user_by_email,
    create_asset_pair,
    delete_asset_pair,
    list_asset_pairs,
    list_project_attachments,
    list_project_members,
    count_project_members,
    count_role_in_project,
    delete_project_member,
    get_user_by_id,
    init_collab_db,
    list_channels,
    list_messages,
    list_projects_for_user,
    upsert_message_read,
    stem_filename,
    suggest_asset_pair_candidates,
    upsert_project_telemost,
    write_audit,
)

_MEMBER_ROLE_PATTERN = "^(" + "|".join(PROJECT_MEMBER_ROLES) + ")$"


def _role_can_manage_members(role: str) -> bool:
    """Invite or change roles (except assigning ГИП — see endpoint)."""
    return role in ("gip", "chief_designer", "designer")


def _role_is_client(role: str) -> bool:
    return role == "client"

try:
    from step_to_glb import step_to_glb_bytes, is_server_conversion_available
except Exception:
    step_to_glb_bytes = None
    is_server_conversion_available = lambda: False


app = FastAPI(title="3d_viewer local server", version="0.2.0")
app.include_router(yadisk_router)

_cors_extra = os.environ.get("COLLAB_CORS_ORIGINS", "").strip()
if _cors_extra:
    _cors_origins = [o.strip() for o in _cors_extra.split(",") if o.strip()]
else:
    _cors_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_cache: dict[str, Any] = {}

init_collab_db()
warn_if_default_auth_secret()

_REQUIRE_AUTH_HEAVY_APIS = os.environ.get("COLLAB_REQUIRE_AUTH_HEAVY_APIS", "").lower() in ("1", "true", "yes")

_AUTH_RATE_LOCK = threading.Lock()
_AUTH_RATE_BUCKETS: dict[str, list[float]] = {}
_AUTH_RATE_WINDOW_SEC = 60.0
_AUTH_RATE_MAX_PER_WINDOW = int(os.environ.get("COLLAB_AUTH_RATE_LIMIT_PER_MINUTE", "60"))


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _enforce_auth_rate_limit(request: Request) -> None:
    if _AUTH_RATE_MAX_PER_WINDOW <= 0:
        return
    ip = _client_ip(request)
    now = time.time()
    with _AUTH_RATE_LOCK:
        bucket = _AUTH_RATE_BUCKETS.setdefault(ip, [])
        bucket[:] = [t for t in bucket if now - t < _AUTH_RATE_WINDOW_SEC]
        if len(bucket) >= _AUTH_RATE_MAX_PER_WINDOW:
            raise HTTPException(status_code=429, detail="Too many requests; try again later")
        bucket.append(now)


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


def _require_heavy_auth_if_configured(authorization: str | None = Header(default=None)) -> None:
    """When COLLAB_REQUIRE_AUTH_HEAVY_APIS=1, heavy CPU/file endpoints need a valid Bearer token."""
    if not _REQUIRE_AUTH_HEAVY_APIS:
        return
    _current_user(authorization)


def _authenticate_ws_user(project_id: str, token: str) -> str | None:
    try:
        payload = decode_token(token.strip())
    except Exception:
        return None
    uid = str(payload.get("sub", ""))
    if not uid:
        return None
    user = get_user_by_id(uid)
    if not user or not bool(user.get("is_active", 0)):
        return None
    if not get_membership(project_id, uid):
        return None
    return uid


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
async def step_metadata(
    file: UploadFile = File(...),
    _: None = Depends(_require_heavy_auth_if_configured),
) -> dict[str, Any]:
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
async def convert_step_to_glb(
    file: UploadFile = File(...),
    _: None = Depends(_require_heavy_auth_if_configured),
) -> Response:
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
async def convert_jt(
    file: UploadFile = File(...),
    _: None = Depends(_require_heavy_auth_if_configured),
) -> Response:
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
def resolve_kompas_assemblies(
    root_dir: str,
    _: None = Depends(_require_heavy_auth_if_configured),
) -> dict[str, Any]:
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
def kompas_metadata(
    assembly_path: str,
    _: None = Depends(_require_heavy_auth_if_configured),
) -> dict[str, Any]:
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
def kompas_metadata_auto(
    root_dir: str,
    _: None = Depends(_require_heavy_auth_if_configured),
) -> dict[str, Any]:
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
def kompas_assembly_map(
    assembly_path: str,
    _: None = Depends(_require_heavy_auth_if_configured),
) -> dict[str, Any]:
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
def kompas_assembly_map_auto(
    root_dir: str,
    _: None = Depends(_require_heavy_auth_if_configured),
) -> dict[str, Any]:
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
    role: str = Field(default="client", pattern=_MEMBER_ROLE_PATTERN)


class UpdateMemberRoleRequest(BaseModel):
    role: str = Field(pattern=_MEMBER_ROLE_PATTERN)


class CreateChannelRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="general", pattern="^(general|module|thread)$")


class CreateMessageRequest(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    attachment_ids: list[str] = Field(default_factory=list, alias="attachmentIds")


class MarkReadRequest(BaseModel):
    last_read_msg_id: str | None = Field(default=None, alias="lastReadMsgId")


class CreateAssetPairRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pdf_attachment_id: str | None = Field(default=None, alias="pdfAttachmentId")
    model_attachment_id: str | None = Field(default=None, alias="modelAttachmentId")
    pdf_stem: str = Field(default="", alias="pdfStem", max_length=400)
    model_stem: str = Field(default="", alias="modelStem", max_length=400)


class RealtimeHub:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_project: dict[str, set[WebSocket]] = {}

    async def register(self, project_id: str, ws: WebSocket) -> None:
        """Добавляет уже принятый (`accept`) сокет в комнату проекта."""
        async with self._lock:
            self._by_project.setdefault(project_id, set()).add(ws)

    async def disconnect(self, project_id: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._by_project.get(project_id)
            if not conns:
                return
            conns.discard(ws)
            if not conns:
                self._by_project.pop(project_id, None)

    async def broadcast(self, project_id: str, event: dict[str, Any]) -> None:
        async with self._lock:
            targets = list(self._by_project.get(project_id, set()))
        for ws in targets:
            try:
                await ws.send_json(event)
            except Exception:
                await self.disconnect(project_id, ws)

    async def broadcast_except(self, project_id: str, event: dict[str, Any], exclude: WebSocket | None) -> None:
        async with self._lock:
            targets = [ws for ws in list(self._by_project.get(project_id, set())) if ws is not exclude]
        for ws in targets:
            try:
                await ws.send_json(event)
            except Exception:
                await self.disconnect(project_id, ws)


_hub = RealtimeHub()

# История CRDT-обновлений Yjs по проекту (ретрансляция без слияния на сервере; новые клиенты получают полную цепочку)
_project_yjs_updates: dict[str, list[str]] = {}
_yjs_updates_lock = asyncio.Lock()
_YJS_SYNC_CHUNK = 120
_YJS_MAX_UPDATE_B64_CHARS = max(4096, int(os.environ.get("COLLAB_YJS_MAX_UPDATE_B64_CHARS", str(750_000))))
_YJS_MAX_STORED_UPDATES = max(100, int(os.environ.get("COLLAB_YJS_MAX_STORED_UPDATES", str(6000))))


async def _append_yjs_update(project_id: str, raw: str) -> bool:
    """Ограничивает размер одного апдейта и общий объём истории в памяти."""
    if len(raw) > _YJS_MAX_UPDATE_B64_CHARS:
        return False
    async with _yjs_updates_lock:
        lst = _project_yjs_updates.setdefault(project_id, [])
        lst.append(raw)
        over = len(lst) - _YJS_MAX_STORED_UPDATES
        if over > 0:
            del lst[0:over]
    return True


async def _send_yjs_history(ws: WebSocket, project_id: str) -> None:
    async with _yjs_updates_lock:
        updates = list(_project_yjs_updates.get(project_id, []))
    if not updates:
        await ws.send_json({"type": "yjs.sync", "updates": [], "final": True})
        return
    for i in range(0, len(updates), _YJS_SYNC_CHUNK):
        chunk = updates[i : i + _YJS_SYNC_CHUNK]
        final = (i + _YJS_SYNC_CHUNK) >= len(updates)
        await ws.send_json({"type": "yjs.sync", "updates": chunk, "final": final})


@app.post("/api/auth/register")
def auth_register(payload: RegisterRequest, request: Request) -> dict[str, Any]:
    _enforce_auth_rate_limit(request)
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
def auth_login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    _enforce_auth_rate_limit(request)
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
    if not _role_can_manage_members(str(membership.get("role", ""))):
        raise HTTPException(status_code=403, detail="Only GIP / chief designer / designer can add members")
    target = get_user_by_email(str(payload.email))
    if not target:
        raise HTTPException(status_code=404, detail="Target user not found")
    if payload.role == "gip" and str(membership.get("role")) != "gip":
        raise HTTPException(status_code=403, detail="Only GIP can assign GIP role")
    add_member(project_id, str(target["id"]), payload.role)
    write_audit(project_id, user.get("id"), "project.member.upsert", "membership", str(target["id"]), {"role": payload.role})
    return {"ok": True}


@app.get("/api/projects/{project_id}/members")
def projects_list_members(project_id: str, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    return {"ok": True, "members": list_project_members(project_id)}


@app.get("/api/projects/{project_id}/telemost")
def projects_telemost(project_id: str, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    """Один звонок Телемоста на проект: создаётся через API при первом запросе, затем хранится в БД."""
    _require_project_member(project_id, str(user["id"]))
    cached = get_project_telemost(project_id)
    if cached:
        return {"ok": True, "joinUrl": cached["join_url"], "cached": True}
    token = os.environ.get("YANDEX_TELEMOST_OAUTH", "").strip()
    if not token:
        return {
            "ok": False,
            "needsOAuth": True,
            "message": (
                "Автоматическое создание комнаты Телемоста недоступно: задайте на сервере переменную окружения "
                "YANDEX_TELEMOST_OAUTH с OAuth-токеном API Яндекс Телемоста (организации Яндекс 360 для бизнеса)."
            ),
        }
    try:
        r = httpx.post(
            "https://cloud-api.yandex.net/v1/telemost-api/conferences",
            headers={
                "Authorization": f"OAuth {token}",
                "Content-Type": "application/json",
            },
            json={"waiting_room_level": "PUBLIC"},
            timeout=45.0,
        )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Telemost API недоступен: {e}") from e

    if r.status_code != 201:
        detail_body = r.text
        try:
            err_j = r.json()
            detail_body = str(err_j.get("message") or err_j.get("error") or detail_body)
        except Exception:
            pass
        raise HTTPException(status_code=502, detail=f"Телемост API ({r.status_code}): {detail_body}")

    try:
        data = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Телемост: неверный JSON ответа: {e}") from e

    join_url = str(data.get("join_url") or "").strip()
    conf_id = str(data.get("id") or "").strip()
    if not join_url:
        raise HTTPException(status_code=502, detail="Телемост API не вернул join_url")
    upsert_project_telemost(project_id, conf_id or "-", join_url)
    write_audit(project_id, user.get("id"), "telemost.conference.create", "project", project_id, {"conferenceId": conf_id})
    return {"ok": True, "joinUrl": join_url, "cached": False}


@app.get("/api/projects/{project_id}/attachments")
def projects_list_attachments(project_id: str, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    return {"ok": True, "attachments": list_project_attachments(project_id)}


@app.get("/api/projects/{project_id}/asset-pairs")
def projects_list_asset_pairs(project_id: str, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    return {"ok": True, "pairs": list_asset_pairs(project_id)}


@app.get("/api/projects/{project_id}/asset-pairs/suggestions")
def projects_asset_pair_suggestions(project_id: str, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    return {"ok": True, "suggestions": suggest_asset_pair_candidates(project_id)}


@app.post("/api/projects/{project_id}/asset-pairs")
def projects_create_asset_pair(
    project_id: str,
    payload: CreateAssetPairRequest,
    user: dict[str, Any] = Depends(_current_user),
) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    pdf_stem = (payload.pdf_stem or "").strip()
    model_stem = (payload.model_stem or "").strip()
    pdf_aid = (payload.pdf_attachment_id or "").strip() or None
    model_aid = (payload.model_attachment_id or "").strip() or None

    if pdf_aid:
        pa = get_attachment(project_id, pdf_aid)
        if not pa:
            raise HTTPException(status_code=404, detail="PDF attachment not found in project")
        pdf_stem = stem_filename(str(pa.get("file_name") or "")) or pdf_stem
    if model_aid:
        ma = get_attachment(project_id, model_aid)
        if not ma:
            raise HTTPException(status_code=404, detail="Model attachment not found in project")
        model_stem = stem_filename(str(ma.get("file_name") or "")) or model_stem

    if not pdf_stem or not model_stem:
        raise HTTPException(status_code=400, detail="Укажите pdfStem/modelStem или id вложений")

    pair = create_asset_pair(
        project_id,
        str(user["id"]),
        pdf_attachment_id=pdf_aid,
        model_attachment_id=model_aid,
        pdf_stem=pdf_stem,
        model_stem=model_stem,
    )
    write_audit(project_id, user.get("id"), "project.asset_pair.create", "asset_pair", str(pair.get("id")), None)
    return {"ok": True, "pair": pair}


@app.delete("/api/projects/{project_id}/asset-pairs/{pair_id}")
def projects_delete_asset_pair(project_id: str, pair_id: str, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    if not delete_asset_pair(project_id, pair_id):
        raise HTTPException(status_code=404, detail="Pair not found")
    write_audit(project_id, user.get("id"), "project.asset_pair.delete", "asset_pair", pair_id, None)
    return {"ok": True}


@app.patch("/api/projects/{project_id}/members/{target_user_id}")
def projects_update_member_role(
    project_id: str,
    target_user_id: str,
    payload: UpdateMemberRoleRequest,
    user: dict[str, Any] = Depends(_current_user),
) -> dict[str, Any]:
    membership = _require_project_member(project_id, str(user["id"]))
    if not _role_can_manage_members(str(membership.get("role", ""))):
        raise HTTPException(
            status_code=403,
            detail="Only GIP / chief designer / designer can change roles",
        )
    target = get_membership(project_id, target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found in project")
    if payload.role == "gip" and str(membership.get("role")) != "gip":
        raise HTTPException(status_code=403, detail="Only GIP can assign GIP role")
    prev_role = str(target.get("role", ""))
    if prev_role == "gip" and payload.role != "gip" and count_role_in_project(project_id, "gip") <= 1:
        raise HTTPException(
            status_code=400,
            detail="Assign another GIP before changing the last GIP role",
        )
    add_member(project_id, target_user_id, payload.role)
    write_audit(
        project_id,
        user.get("id"),
        "project.member.role",
        "membership",
        target_user_id,
        {"role": payload.role, "previousRole": prev_role},
    )
    return {"ok": True}


@app.delete("/api/projects/{project_id}/members/{target_user_id}")
def projects_remove_member(
    project_id: str,
    target_user_id: str,
    user: dict[str, Any] = Depends(_current_user),
) -> dict[str, Any]:
    actor_id = str(user["id"])
    membership = _require_project_member(project_id, actor_id)
    target = get_membership(project_id, target_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found in project")

    target_role = str(target.get("role", ""))

    if target_user_id == actor_id:
        n = count_project_members(project_id)
        if n <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot leave project: you are the only member",
            )
        if target_role == "gip" and count_role_in_project(project_id, "gip") <= 1:
            raise HTTPException(
                status_code=400,
                detail="Assign another GIP before leaving the project",
            )
        delete_project_member(project_id, actor_id)
        write_audit(project_id, actor_id, "project.member.leave", "membership", actor_id, None)
        return {"ok": True}

    if not _role_can_manage_members(str(membership.get("role", ""))):
        raise HTTPException(
            status_code=403,
            detail="Only GIP / chief designer / designer can remove members",
        )
    if target_role == "gip" and str(membership.get("role")) != "gip":
        raise HTTPException(status_code=403, detail="Only GIP can remove a GIP member")
    if target_role == "gip" and count_role_in_project(project_id, "gip") <= 1:
        raise HTTPException(
            status_code=400,
            detail="Assign another GIP before removing the current GIP",
        )
    delete_project_member(project_id, target_user_id)
    write_audit(
        project_id,
        actor_id,
        "project.member.remove",
        "membership",
        target_user_id,
        {"role": target_role},
    )
    return {"ok": True}


@app.get("/api/projects/{project_id}/channels")
def channels_list(project_id: str, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    return {"ok": True, "channels": list_channels(project_id)}


@app.post("/api/projects/{project_id}/channels")
def channels_create(project_id: str, payload: CreateChannelRequest, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    membership = _require_project_member(project_id, str(user["id"]))
    if _role_is_client(str(membership.get("role", ""))):
        raise HTTPException(status_code=403, detail="Client role cannot create channels")
    channel = create_channel(project_id, payload.kind, payload.name, str(user["id"]))
    write_audit(project_id, user.get("id"), "chat.channel.create", "channel", channel.get("id"), {"kind": payload.kind, "name": payload.name})
    return {"ok": True, "channel": channel}


@app.get("/api/projects/{project_id}/channels/{channel_id}/messages")
def messages_list(project_id: str, channel_id: str, limit: int = 50, before: str | None = None, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    safe_limit = min(200, max(1, int(limit)))
    return {"ok": True, "messages": list_messages(channel_id, safe_limit, before)}


@app.post("/api/projects/{project_id}/channels/{channel_id}/messages")
async def messages_create(project_id: str, channel_id: str, payload: CreateMessageRequest, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    membership = _require_project_member(project_id, str(user["id"]))
    if _role_is_client(str(membership.get("role", ""))):
        raise HTTPException(status_code=403, detail="Client role cannot send messages")
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
    await _hub.broadcast(
        project_id,
        {
            "type": "chat.message.created",
            "projectId": project_id,
            "channelId": channel_id,
            "message": msg,
        },
    )
    return {"ok": True, "message": msg}


@app.post("/api/projects/{project_id}/channels/{channel_id}/read")
async def mark_channel_read(project_id: str, channel_id: str, payload: MarkReadRequest, user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
    _require_project_member(project_id, str(user["id"]))
    rec = upsert_message_read(project_id, channel_id, str(user["id"]), payload.last_read_msg_id)
    await _hub.broadcast(
        project_id,
        {
            "type": "chat.read.updated",
            "projectId": project_id,
            "channelId": channel_id,
            "userId": str(user["id"]),
            "lastReadAt": rec.get("last_read_at"),
            "lastReadMsgId": rec.get("last_read_msg_id"),
        },
    )
    return {"ok": True, "readState": rec}


_ATTACH_ROOT = Path(__file__).resolve().parent / "uploads" / "chat"
_ATTACH_MAX_BYTES = 200 * 1024 * 1024
_ATTACH_ALLOWED_EXT = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff",
    ".pdf",
    ".xls", ".xlsx", ".xlsm", ".csv",
    ".dwg", ".dxf",
    ".cdw", ".spw", ".m3d", ".a3d", ".frw",
    ".rvt", ".rfa",
    ".step", ".stp", ".iges", ".igs", ".stl", ".glb", ".gltf",
}
_ATTACH_ALLOWED_MIME = {
    "application/octet-stream",
    "application/pdf",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "image/bmp",
    "image/tiff",
}
_ATTACH_FALLBACK_EXT_BY_MIME = {
    "application/pdf": ".pdf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel.sheet.macroenabled.12": ".xlsm",
    "text/csv": ".csv",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}


@app.post("/api/projects/{project_id}/attachments/upload")
async def upload_attachment(
    project_id: str,
    file: UploadFile = File(...),
    source: str = Form(default="other"),
    context_json: str = Form(default="{}"),
    user: dict[str, Any] = Depends(_current_user),
) -> dict[str, Any]:
    membership = _require_project_member(project_id, str(user["id"]))
    if _role_is_client(str(membership.get("role", ""))):
        raise HTTPException(status_code=403, detail="Client role cannot upload attachments")
    mime = (file.content_type or "").lower().strip() or "application/octet-stream"
    ext = Path(file.filename or "").suffix.lower().strip()
    if ext and ext not in _ATTACH_ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Unsupported file extension: {ext}")
    if mime not in _ATTACH_ALLOWED_MIME and not ext:
        raise HTTPException(status_code=400, detail=f"Unsupported mime type: {mime}")
    data = await file.read()
    if len(data) > _ATTACH_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Attachment is too large")
    try:
        context = json.loads(context_json) if context_json else {}
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid context_json") from e
    if not ext:
        ext = _ATTACH_FALLBACK_EXT_BY_MIME.get(mime, ".bin")
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


@app.websocket("/api/projects/{project_id}/ws")
async def project_ws(project_id: str, ws: WebSocket) -> None:
    await ws.accept()
    query_token = ws.query_params.get("token", "").strip()
    user_id: str | None = None

    if query_token:
        user_id = _authenticate_ws_user(project_id, query_token)
        if not user_id:
            await ws.close(code=4401)
            return
    else:
        try:
            first = await ws.receive_json()
        except WebSocketDisconnect:
            return
        except Exception:
            await ws.close(code=4400)
            return
        if str(first.get("type", "")) != "ws.auth":
            await ws.close(code=4408)
            return
        auth_token = str(first.get("token", "")).strip()
        user_id = _authenticate_ws_user(project_id, auth_token)
        if not user_id:
            await ws.close(code=4401)
            return

    await _hub.register(project_id, ws)
    try:
        await ws.send_json(
            {
                "type": "ws.connected",
                "projectId": project_id,
                "userId": user_id,
            }
        )
        await _send_yjs_history(ws, project_id)
        while True:
            data = await ws.receive_json()
            action = str(data.get("type", ""))
            if action == "ping":
                await ws.send_json({"type": "pong"})
            elif action == "yjs.update":
                raw = str(data.get("update", "")).strip()
                if raw and await _append_yjs_update(project_id, raw):
                    await _hub.broadcast_except(
                        project_id,
                        {"type": "yjs.update", "update": raw},
                        exclude=ws,
                    )
            elif action == "yjs.awareness":
                raw = str(data.get("update", "")).strip()
                if raw and len(raw) <= _YJS_MAX_UPDATE_B64_CHARS:
                    await _hub.broadcast_except(
                        project_id,
                        {"type": "yjs.awareness", "update": raw},
                        exclude=ws,
                    )
            elif action == "telemost.join":
                join_url = str(data.get("joinUrl", "")).strip()
                title = str(data.get("title", "")).strip() or "Звонок проекта"
                if join_url:
                    await _hub.broadcast_except(
                        project_id,
                        {
                            "type": "telemost.join",
                            "joinUrl": join_url,
                            "title": title,
                            "userId": user_id,
                        },
                        exclude=ws,
                    )
            elif action == "chat.read":
                channel_id = str(data.get("channelId", "")).strip()
                if channel_id:
                    rec = upsert_message_read(project_id, channel_id, user_id, str(data.get("lastReadMsgId") or "") or None)
                    await _hub.broadcast(
                        project_id,
                        {
                            "type": "chat.read.updated",
                            "projectId": project_id,
                            "channelId": channel_id,
                            "userId": user_id,
                            "lastReadAt": rec.get("last_read_at"),
                            "lastReadMsgId": rec.get("last_read_msg_id"),
                        },
                    )
    except WebSocketDisconnect:
        pass
    finally:
        await _hub.disconnect(project_id, ws)

