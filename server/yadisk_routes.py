"""Яндекс.Диск REST: публичная папка и OAuth (полный диск)."""

from __future__ import annotations

import asyncio
import os
import secrets
import time
from typing import Any
from urllib.parse import quote as url_quote, urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/yadisk", tags=["yadisk"])

DISK_API = "https://cloud-api.yandex.net/v1/disk"
OAUTH_AUTHORIZE = "https://oauth.yandex.ru/authorize"
OAUTH_TOKEN = "https://oauth.yandex.ru/token"

COOKIE_SID = "yadisk_oauth_sid"

_tokens: dict[str, dict[str, Any]] = {}
_tokens_lock = asyncio.Lock()


def _env_redirect_uri() -> str:
    return os.getenv("YANDEX_OAUTH_REDIRECT_URI", "http://localhost:8000/api/yadisk/oauth/callback").strip()


def _env_success_redirect() -> str:
    return os.getenv("YANDEX_OAUTH_SUCCESS_REDIRECT", "http://localhost:5173/?yadisk_oauth=1").strip()


def _client_creds() -> tuple[str, str]:
    cid = (os.getenv("YANDEX_CLIENT_ID") or "").strip()
    sec = (os.getenv("YANDEX_CLIENT_SECRET") or "").strip()
    return cid, sec


def _normalize_embedded_item(raw: dict[str, Any]) -> dict[str, Any]:
    t = str(raw.get("type") or "")
    file_link = raw.get("file")
    if isinstance(file_link, str):
        href = file_link
    elif isinstance(file_link, dict):
        href = str(file_link.get("href") or "")
    else:
        href = ""
    return {
        "type": "dir" if t == "dir" else "file",
        "name": str(raw.get("name") or ""),
        "path": str(raw.get("path") or ""),
        "mime_type": raw.get("mime_type"),
        "size": raw.get("size"),
        "href": href or None,
    }


class PublicListBody(BaseModel):
    public_url: str = Field(..., min_length=8)
    path: str = ""
    limit: int = Field(200, ge=1, le=1000)
    offset: int = Field(0, ge=0)


@router.post("/public/list")
async def public_list(body: PublicListBody) -> dict[str, Any]:
    public_url = body.public_url.strip()
    params: dict[str, Any] = {
        "public_key": public_url,
        "limit": body.limit,
        "offset": body.offset,
    }
    sub_path = body.path.strip()
    if sub_path:
        params["path"] = sub_path
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{DISK_API}/public/resources", params=params)
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"yandex_disk: {r.status_code} {r.text[:500]}")
    data = r.json()
    if isinstance(data, dict) and data.get("type") == "file" and not (data.get("_embedded") or {}).get("items"):
        items = [_normalize_embedded_item(data)]
        total = 1
    else:
        emb = data.get("_embedded") or {}
        items_raw = emb.get("items") if isinstance(emb, dict) else None
        items = [_normalize_embedded_item(x) for x in (items_raw or []) if isinstance(x, dict)]
        total = emb.get("total") if isinstance(emb, dict) else None
    return {
        "items": items,
        "total": total,
        "limit": body.limit,
        "offset": body.offset,
    }


def _get_sid(request: Request) -> str | None:
    v = request.cookies.get(COOKIE_SID)
    return v.strip() if v and v.strip() else None


async def _ensure_valid_access_token(sid: str) -> str | None:
    async with _tokens_lock:
        rec = _tokens.get(sid)
    if not rec:
        return None
    exp = float(rec.get("expires_at") or 0)
    if exp and time.time() < exp - 60:
        return str(rec.get("access_token") or "")
    rt = str(rec.get("refresh_token") or "")
    if not rt:
        return str(rec.get("access_token") or "") if rec.get("access_token") else None
    cid, sec = _client_creds()
    if not cid or not sec:
        return None
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            OAUTH_TOKEN,
            data={
                "grant_type": "refresh_token",
                "refresh_token": rt,
                "client_id": cid,
                "client_secret": sec,
            },
        )
    if r.status_code >= 400:
        async with _tokens_lock:
            _tokens.pop(sid, None)
        return None
    tok = r.json()
    access = str(tok.get("access_token") or "")
    refresh_new = str(tok.get("refresh_token") or rt)
    expires_in = int(tok.get("expires_in") or 3600)
    async with _tokens_lock:
        _tokens[sid] = {
            "access_token": access,
            "refresh_token": refresh_new,
            "expires_at": time.time() + expires_in,
        }
    return access


@router.get("/oauth/url")
async def oauth_url(request: Request) -> JSONResponse:
    cid, sec = _client_creds()
    if not cid or not sec:
        raise HTTPException(
            status_code=503,
            detail="Задайте YANDEX_CLIENT_ID и YANDEX_CLIENT_SECRET на сервере",
        )
    sid = _get_sid(request) or secrets.token_urlsafe(24)
    redir = _env_redirect_uri()
    q = urlencode(
        {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": redir,
            "state": sid,
            "scope": "cloud_api:disk.read",
        }
    )
    url = f"{OAUTH_AUTHORIZE}?{q}"
    out = JSONResponse({"authorize_url": url})
    out.set_cookie(
        COOKIE_SID,
        sid,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,
        path="/",
    )
    return out


def _append_query(url: str, key: str, value: str) -> str:
    sep = "&" if ("?" in url) else "?"
    return f"{url}{sep}{key}={url_quote(value, safe='')}"


@router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> RedirectResponse:
    ok_redirect = _env_success_redirect()
    if error:
        msg = (error_description or error)[:400]
        return RedirectResponse(
            url=_append_query(ok_redirect, "yadisk_err", msg or error),
            status_code=302,
        )
    sid_cookie = _get_sid(request)
    if not code or not state or state != sid_cookie:
        return RedirectResponse(url=_append_query(ok_redirect, "yadisk_err", "state"), status_code=302)
    cid, sec = _client_creds()
    if not cid or not sec:
        return RedirectResponse(url=_append_query(ok_redirect, "yadisk_err", "no_creds"), status_code=302)
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            OAUTH_TOKEN,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": cid,
                "client_secret": sec,
                "redirect_uri": _env_redirect_uri(),
            },
        )
    if r.status_code >= 400:
        return RedirectResponse(url=_append_query(ok_redirect, "yadisk_err", "token"), status_code=302)
    tok = r.json()
    access = str(tok.get("access_token") or "")
    refresh = str(tok.get("refresh_token") or "")
    expires_in = int(tok.get("expires_in") or 3600)
    if not access:
        return RedirectResponse(url=_append_query(ok_redirect, "yadisk_err", "no_access"), status_code=302)
    async with _tokens_lock:
        _tokens[state] = {
            "access_token": access,
            "refresh_token": refresh,
            "expires_at": time.time() + expires_in,
        }
    return RedirectResponse(url=ok_redirect, status_code=302)


@router.get("/oauth/status")
async def oauth_status(request: Request) -> dict[str, Any]:
    sid = _get_sid(request)
    if not sid:
        return {"connected": False}
    token = await _ensure_valid_access_token(sid)
    return {"connected": bool(token)}


@router.post("/oauth/logout")
async def oauth_logout(request: Request, response: Response) -> dict[str, Any]:
    sid = _get_sid(request)
    if sid:
        async with _tokens_lock:
            _tokens.pop(sid, None)
    response.delete_cookie(COOKIE_SID, path="/")
    return {"ok": True}


@router.get("/private/list")
async def private_list(
    request: Request,
    path: str = "disk:/",
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    sid = _get_sid(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Нет сессии OAuth")
    token = await _ensure_valid_access_token(sid)
    if not token:
        raise HTTPException(status_code=401, detail="Нужна повторная авторизация Яндекс")
    limit = max(1, min(1000, limit))
    offset = max(0, offset)
    p = path.strip() or "disk:/"
    params = {"path": p, "limit": limit, "offset": offset}
    headers = {"Authorization": f"OAuth {token}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(f"{DISK_API}/resources", params=params, headers=headers)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="Путь не найден")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"yandex_disk: {r.status_code} {r.text[:500]}")
    data = r.json()
    emb = data.get("_embedded") or {}
    items_raw = emb.get("items") if isinstance(emb, dict) else None
    items = [_normalize_embedded_item(x) for x in (items_raw or []) if isinstance(x, dict)]
    total = emb.get("total") if isinstance(emb, dict) else None
    return {"items": items, "total": total, "path": p, "limit": limit, "offset": offset}
