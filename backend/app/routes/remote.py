"""远程控制：一次性配对链接、二维码、设备会话与撤销。

与 ZCode Remote Control 同构：
- 桌面端生成链接/二维码，手机扫码后拿到设备令牌；
- 手机只是一层控制面，所有请求仍由本机服务执行；
- 关闭面板不等于断开，必须显式停止；刷新二维码会让旧链接立即失效；
- 链接里的令牌走 URL fragment，不进服务端日志与 Referer。
"""

from __future__ import annotations

import base64
import io
import urllib.parse
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from .. import auth, db, provenance
from ..auth_guard import require_instance_admin
from ..timeutil import now_iso

try:  # 二维码是可选增强：缺库时仍能复制链接，只是不显示图
    import qrcode
    import qrcode.image.svg

    _QR_OK = True
except Exception:  # noqa: BLE001
    _QR_OK = False

router = APIRouter()

REMOTE_SETTING_KEYS = ("remote_enabled", "remote_public_url", "remote_session_hours")
REMOTE_DEFAULT_HOURS = 12


def _bool_on(value: Any) -> bool:
    return str(value or "").strip().lower() not in ("off", "0", "false", "no", "")


async def _load_settings() -> dict[str, str]:
    raw = await db.get_settings()
    return {
        "enabled": _bool_on(raw.get("remote_enabled", "on")),
        "public_url": str(raw.get("remote_public_url") or "").strip().rstrip("/"),
        "hours": max(1, min(int(raw.get("remote_session_hours") or REMOTE_DEFAULT_HOURS), 168)),
    }


def _request_base(request: Request, public_url: str) -> str:
    if public_url:
        return public_url
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}".rstrip("/")


def _link_warning(base: str) -> str:
    host = urllib.parse.urlsplit(base).hostname or ""
    if host in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        return "当前地址是本机回环，手机扫码访问不到。请先在「对外地址」里填公网域名或局域网 IP。"
    if base.startswith("http://"):
        return "当前是 HTTP，公网传输没有加密。建议在反向代理上启用 HTTPS 后再让手机接入。"
    return ""


def _qr_data_url(url: str) -> str:
    if not _QR_OK:
        return ""
    try:
        img = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
        buf = io.BytesIO()
        img.save(buf)
        raw = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{raw}"
    except Exception:  # noqa: BLE001 — 二维码失败不影响复制链接
        return ""


def _pair_url(base: str, sid: str, token: str) -> str:
    # 令牌放 fragment：浏览器不会把 # 后面发给服务器，也不会进 Referer。
    return f"{base}/remote#s={urllib.parse.quote(sid)}&t={urllib.parse.quote(token)}"


def _payload(request: Request, session: dict[str, Any], token: str, settings: dict[str, Any]) -> dict[str, Any]:
    base = _request_base(request, settings["public_url"])
    url = _pair_url(base, str(session["sid"]), token)
    return {
        **session,
        "pair_url": url,
        "qr_svg": _qr_data_url(url),
        "base_url": base,
        "warning": _link_warning(base),
    }


async def _owner(user: dict | None = Depends(auth.get_current_user)) -> dict[str, Any]:
    """远程控制是实例级能力：必须有本机/管理员身份，不能由普通租户开放。"""
    return await require_instance_admin(user)


@router.get("/api/remote/config")
async def remote_config(request: Request, user: dict = Depends(_owner)) -> dict:
    settings = await _load_settings()
    base = _request_base(request, settings["public_url"])
    return {
        "enabled": settings["enabled"],
        "public_url": settings["public_url"],
        "session_hours": settings["hours"],
        "base_url": base,
        "warning": _link_warning(base),
        "qr_available": _QR_OK,
        "sessions": await db.list_remote_sessions(int(user.get("id") or 0)),
        "active_count": await db.active_remote_count(int(user.get("id") or 0)),
    }


@router.put("/api/remote/config")
async def update_remote_config(request: Request, payload: dict, user: dict = Depends(_owner)) -> Any:
    updates = payload or {}
    public_url = str(updates.get("public_url") or "").strip().rstrip("/")
    if public_url:
        parsed = urllib.parse.urlsplit(public_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return JSONResponse({"error": "对外地址必须是 http(s):// 开头的完整地址"}, status_code=400)
    hours_raw = updates.get("session_hours", updates.get("hours", REMOTE_DEFAULT_HOURS))
    try:
        hours = max(1, min(int(hours_raw), 168))
    except (TypeError, ValueError):
        return JSONResponse({"error": "会话时长必须是 1-168 小时"}, status_code=400)
    await db.set_setting("remote_public_url", public_url)
    await db.set_setting("remote_session_hours", str(hours))
    if "enabled" in updates:
        await db.set_setting("remote_enabled", "on" if _bool_on(updates.get("enabled")) else "off")
    await provenance.record_provenance(
        "remote_config_update",
        "remote_settings",
        "",
        after={"public_url": public_url, "session_hours": hours, "enabled": _bool_on(updates.get("enabled", True))},
        source="api",
    )
    return await remote_config(request, user)


@router.post("/api/remote/sessions")
async def create_remote(request: Request, payload: dict | None = None, user: dict = Depends(_owner)) -> Any:
    settings = await _load_settings()
    if not settings["enabled"]:
        return JSONResponse({"error": "远程控制已关闭"}, status_code=403)
    body = payload or {}
    label = str(body.get("label") or "").strip()[:40]
    hours = body.get("hours", settings["hours"])
    try:
        hours = max(1, min(int(hours), 168))
    except (TypeError, ValueError):
        hours = settings["hours"]
    session = await db.create_remote_session(int(user.get("id") or 0), label=label, hours=hours)
    await provenance.record_provenance(
        "remote_session_create",
        "remote_session",
        session["sid"],
        after={"label": label, "expires_at": session["expires_at"], "hours": hours},
        source="api",
    )
    return _payload(request, {k: v for k, v in session.items() if k != "pair_token"}, session["pair_token"], settings)


@router.get("/api/remote/sessions")
async def list_remote(user: dict = Depends(_owner)) -> dict:
    uid = int(user.get("id") or 0)
    return {
        "sessions": await db.list_remote_sessions(uid),
        "active_count": await db.active_remote_count(uid),
    }


@router.post("/api/remote/sessions/{sid}/refresh")
async def refresh_remote(request: Request, sid: str, user: dict = Depends(_owner)) -> Any:
    settings = await _load_settings()
    rotated = await db.rotate_remote_session(sid, int(user.get("id") or 0), hours=settings["hours"])
    if not rotated:
        return JSONResponse({"error": "会话不存在或已撤销"}, status_code=404)
    await provenance.record_provenance(
        "remote_session_rotate",
        "remote_session",
        sid,
        after={"expires_at": rotated["expires_at"]},
        source="api",
    )
    return _payload(request, {k: v for k, v in rotated.items() if k != "pair_token"}, rotated["pair_token"], settings)


@router.post("/api/remote/sessions/{sid}/stop")
async def stop_remote(sid: str, user: dict = Depends(_owner)) -> dict:
    ok = await db.revoke_remote_session(sid, int(user.get("id") or 0))
    if ok:
        await provenance.record_provenance(
            "remote_session_revoke",
            "remote_session",
            sid,
            after={"revoked_at": now_iso()},
            source="api",
        )
    return {"ok": ok}


@router.post("/api/remote/stop-all")
async def stop_all_remote(user: dict = Depends(_owner)) -> dict:
    count = await db.revoke_all_remote_sessions(int(user.get("id") or 0))
    await provenance.record_provenance(
        "remote_session_revoke_all",
        "remote_session",
        "",
        after={"revoked": count},
        source="api",
    )
    return {"ok": True, "revoked": count}


@router.post("/api/remote/pair")
async def pair_remote(request: Request, payload: dict | None = None) -> Any:
    """手机扫码后的交换入口：一次性令牌换 HttpOnly 设备 cookie。"""
    settings = await _load_settings()
    if not settings["enabled"]:
        return JSONResponse({"error": "远程控制已关闭"}, status_code=403)
    body = payload or {}
    sid = str(body.get("sid") or "").strip()
    token = str(body.get("token") or "").strip()
    if not sid or not token:
        return JSONResponse({"error": "配对信息不完整"}, status_code=400)

    ua = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else ""
    paired = await db.pair_remote_session(sid, token, ua=ua, ip=ip, device_label=str(body.get("name") or ""))
    if not paired:
        await provenance.record_provenance(
            "remote_pair_failed",
            "remote_session",
            sid,
            after={"ip": ip},
            source="remote",
            username="remote-pair",
        )
        return JSONResponse({"error": "链接无效、已使用或已过期，请在电脑上刷新二维码"}, status_code=410)

    row = await db.get_remote_session(sid)
    expires_at = str((row or {}).get("expires_at") or "")
    max_age = 3600 * settings["hours"]
    try:
        max_age = max(60, int((datetime.fromisoformat(expires_at) - datetime.now().astimezone()).total_seconds()))
    except Exception:  # noqa: BLE001
        pass
    secure = request.url.scheme == "https" or (request.headers.get("x-forwarded-proto") or "").lower() == "https"
    resp = JSONResponse(
        {
            "ok": True,
            "redirect": "/?remote=1",
            "sid": sid,
            "device_name": paired["device_name"],
            "expires_at": expires_at,
        }
    )
    resp.set_cookie(
        "mh_remote",
        f"{sid}.{paired['device_token']}",
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    await provenance.record_provenance(
        "remote_pair",
        "remote_session",
        sid,
        after={"device_name": paired["device_name"], "ip": ip, "expires_at": expires_at},
        source="remote",
        username="remote-pair",
    )
    return resp


@router.get("/api/remote/me")
async def remote_me(request: Request) -> dict:
    from ..mw_auth import remote_identity

    ident = await remote_identity(request)
    if not ident:
        return {"remote": False}
    return {"remote": True, **ident}


@router.post("/api/remote/disconnect")
async def disconnect_remote(request: Request) -> dict:
    from ..mw_auth import remote_identity

    ident = await remote_identity(request)
    if ident:
        await db.revoke_remote_session(str(ident["sid"]))
        await provenance.record_provenance(
            "remote_disconnect",
            "remote_session",
            str(ident["sid"]),
            after={"by": "device"},
            source="remote",
            username=f"remote:{ident.get('device_name') or 'phone'}",
        )
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("mh_remote", path="/")
    return resp


@router.get("/remote", include_in_schema=False)
async def remote_page() -> Response:
    """配对页与主应用共用同一份前端构建；前端按 pathname 切到 RemotePairView。"""
    from ..main import FRONTEND_DIST

    index = FRONTEND_DIST / "index.html"
    if not index.is_file():
        return Response("前端未构建：cd frontend && npm run build", media_type="text/plain", status_code=503)
    return Response(index.read_text(encoding="utf-8"), media_type="text/html", headers={"Cache-Control": "no-store"})
