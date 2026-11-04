"""执行层路由（v4.6）：券商适配器探测 / 交易状态 / 预检 / 确认 / 报单 / 对账。

安全模型（与 broker_adapter.guarded_submit 一致）：
- 默认 NullBroker + dry_run=true，**不会产生任何真实委托**；
- 真实开启需要环境变量三件套（ENABLED + DRY_RUN=false + BROKER=白名单），
  并且每笔报单必须先 preview 拿 token，再带 token 提交；
- 所有报单与拒绝都写 provenance，便于事后追责。
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from .. import db
from ..auth import get_current_user
from ..broker_adapter import (
    ALLOWED_BROKERS,
    OrderRequest,
    OrderSide,
    build_adapter,
    default_guardrails,
    guarded_submit,
    issue_confirmation,
    trading_status,
)
from ..db.tenant import current_user_id
from ..provenance import record_provenance

router = APIRouter(dependencies=[Depends(get_current_user)])

# 适配器按「租户+券商」缓存：连接 QMT/客户端是重操作不能每请求重连，
# 但缓存键绝不能只有券商名——此前用户 B 首次访问会直接拿到用户 A 的连接
# （含 A 的账户、资金、持仓），属于跨租户越权。键改为 (user_id, name)。
_adapters: dict[tuple[int, str], Any] = {}
_lock = asyncio.Lock()


def _bad(msg: str, code: int = 400) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=code)


async def _get_adapter(name: str) -> Any:
    if name not in ALLOWED_BROKERS:
        raise ValueError(f"未知适配器：{name}")
    key = (current_user_id(), name)
    if key not in _adapters:
        credentials = await db.broker_get_secret(name)
        _adapters[key] = build_adapter(name, credentials)
    return _adapters[key]


async def _clear_adapter(name: str) -> None:
    adapter = _adapters.pop((current_user_id(), name), None)
    if adapter is not None:
        try:
            await asyncio.to_thread(adapter.disconnect)
        except Exception:  # noqa: BLE001 — 清理失败不阻断重新配置
            pass


def _parse_request(payload: dict[str, Any]) -> OrderRequest:
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not (symbol.isdigit() and len(symbol) == 6):
        raise ValueError("代码需为 6 位数字")
    side_raw = str(payload.get("side") or "").strip().lower()
    if side_raw not in ("buy", "sell"):
        raise ValueError("方向只能是 buy / sell")
    try:
        quantity = int(float(payload.get("quantity") or payload.get("shares") or 0))
        price = Decimal(str(payload.get("limit_price") or payload.get("price") or 0))
    except (TypeError, ValueError, InvalidOperation):
        raise ValueError("价格与数量必须是数字") from None
    if quantity <= 0 or price <= 0:
        raise ValueError("价格与数量必须大于 0")
    return OrderRequest(
        symbol=symbol,
        side=OrderSide(side_raw),
        quantity=quantity,
        limit_price=price,
        client_order_id=str(payload.get("client_order_id") or ""),
        reason=str(payload.get("reason") or "")[:200],
    )


# ---------------------------------------------------------------------------
# 状态 / 探测
# ---------------------------------------------------------------------------


@router.get("/api/execute/status")
async def execute_status() -> dict[str, Any]:
    """交易状态：开关、dry-run、各适配器本机可用性与问题清单（不回传秘密）。"""
    out = trading_status()
    configured = {row["broker_id"]: row for row in await db.broker_list_credentials()}
    for adapter in out.get("adapters", []):
        row = configured.get(adapter["id"])
        adapter["configured"] = bool(row and row.get("configured"))
        adapter["configured_enabled"] = bool(row and row.get("enabled"))
        if row and row.get("meta"):
            adapter["meta"] = row["meta"]
    out["configured"] = list(configured.values())
    return out


@router.get("/api/execute/brokers")
async def execute_brokers() -> dict[str, Any]:
    """券商通道清单：SDK 探测 + 加密凭据配置状态。"""
    return {"items": (await execute_status()).get("adapters", [])}


@router.put("/api/execute/brokers/{name}/credentials")
async def configure_broker(name: str, payload: dict[str, Any]) -> Any:
    """保存券商凭据：secret 整体进入 vault；API 只返回配置状态与元信息。"""
    if name not in ALLOWED_BROKERS:
        return _bad(f"未知适配器：{name}")
    secret = payload.get("secret")
    if not isinstance(secret, dict) or not secret:
        return _bad("secret 必须是非空对象（只提交券商要求的 API Key/Token，不要提交登录密码）")
    try:
        saved = await db.broker_save_credentials(
            name,
            secret,
            label=str(payload.get("label") or name),
            meta=payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
            enabled=bool(payload.get("enabled", False)),
        )
    except RuntimeError as exc:
        return _bad(str(exc), 503)
    except ValueError as exc:
        return _bad(str(exc))
    await _clear_adapter(name)
    return {"ok": True, "broker": saved}


@router.get("/api/execute/brokers/configured")
async def configured_brokers() -> dict[str, Any]:
    return {"items": await db.broker_list_credentials()}


@router.delete("/api/execute/brokers/{name}/credentials")
async def delete_broker_credentials(name: str) -> Any:
    if name not in ALLOWED_BROKERS:
        return _bad(f"未知适配器：{name}")
    await _clear_adapter(name)
    return {"deleted": name, "ok": await db.broker_delete_credentials(name)}


@router.post("/api/execute/adapters/{name}/connect")
async def connect_adapter(name: str) -> Any:
    """连接适配器：使用 vault 解密的配置或环境变量，成功后读取真实资金/持仓。"""
    if name not in ALLOWED_BROKERS:
        return _bad(f"未知适配器：{name}")
    adapter = await _get_adapter(name)
    info = adapter.probe()
    if not info.get("available"):
        return _bad(f"该适配器本机不可用：{info.get('note') or '环境不满足'}")
    try:
        async with _lock:
            await asyncio.to_thread(adapter.connect)
    except Exception as exc:  # noqa: BLE001 — 连接失败给可读错误
        return _bad(f"连接失败：{type(exc).__name__}: {exc}", 502)
    return {
        "ok": True,
        "adapter": name,
        "connected": adapter.is_connected(),
        "cash": float(adapter.get_cash()),
        "positions": adapter.get_positions(),
    }


@router.post("/api/execute/adapters/{name}/disconnect")
async def disconnect_adapter(name: str) -> Any:
    if name not in ALLOWED_BROKERS:
        return _bad(f"未知适配器：{name}")
    adapter = await _get_adapter(name)
    async with _lock:
        await asyncio.to_thread(adapter.disconnect)
    return {"ok": True, "adapter": name, "connected": adapter.is_connected()}


# ---------------------------------------------------------------------------
# 预检 → 确认 → 报单
# ---------------------------------------------------------------------------


@router.post("/api/execute/preview")
async def execute_preview(payload: dict[str, Any]) -> Any:
    """预检：跑护栏 + 适配器预检，返回 token（dry_run 时不出 token，直接返回模拟结果）。"""
    try:
        req = _parse_request(payload)
    except ValueError as exc:
        return _bad(str(exc))

    g = default_guardrails()
    adapter = await _get_adapter(g["broker"])
    positions = await db.list_positions()
    total_value = sum(float(p.get("shares", 0)) * float(p.get("last", 0)) for p in positions)
    held = next((p for p in positions if str(p.get("symbol", "")).upper() == req.symbol), None)
    position_value = float(held.get("shares", 0)) * float(held.get("last", 0)) if held else 0.0
    intents = await db.list_intents(limit=200) if hasattr(db, "list_intents") else []
    daily_used = sum(float(i.get("price", 0)) * float(i.get("shares", 0)) for i in intents)

    check = guarded_submit(
        adapter=adapter,
        req=req,
        guardrails=g,
        daily_used_amount=daily_used,
        portfolio_value=total_value,
        position_value=position_value,
    )
    token = ""
    if check["ok"] and not g["dry_run"]:
        token = issue_confirmation(req, int(g["confirmation_ttl_seconds"])).token
    return {
        "ok": check["ok"],
        "stage": check["stage"],
        "message": check["message"],
        "result": check["result"],
        "confirmation_token": token,
        "guardrails": g,
        "request": req.to_dict(),
    }


@router.post("/api/execute/submit")
async def execute_submit(payload: dict[str, Any]) -> Any:
    """报单：必须带 preview 返回的 token（dry_run 除外）。"""
    try:
        req = _parse_request(payload)
    except ValueError as exc:
        return _bad(str(exc))

    g = default_guardrails()
    adapter = await _get_adapter(g["broker"])
    positions = await db.list_positions()
    total_value = sum(float(p.get("shares", 0)) * float(p.get("last", 0)) for p in positions)
    held = next((p for p in positions if str(p.get("symbol", "")).upper() == req.symbol), None)
    position_value = float(held.get("shares", 0)) * float(held.get("last", 0)) if held else 0.0

    result = guarded_submit(
        adapter=adapter,
        req=req,
        guardrails=g,
        confirmation_token=str(payload.get("confirmation_token") or ""),
        portfolio_value=total_value,
        position_value=position_value,
    )
    await record_provenance(
        action="execute_order",
        entity_type="order",
        entity_id=req.client_order_id or req.symbol,
        before=None,
        after={
            "request": req.to_dict(),
            "stage": result["stage"],
            "ok": result["ok"],
            "broker": g["broker"],
            "dry_run": g["dry_run"],
        },
        source="execute",
    )
    return result


@router.get("/api/execute/orders")
async def execute_orders() -> dict[str, Any]:
    """对账：拉当前适配器的当日委托（实盘返回券商状态，默认适配器返回空）。"""
    g = default_guardrails()
    adapter = await _get_adapter(g["broker"])
    try:
        rows = await asyncio.to_thread(adapter.poll_orders)
    except Exception as exc:  # noqa: BLE001
        return {"items": [], "error": f"{type(exc).__name__}: {exc}"}
    return {"items": rows, "broker": g["broker"], "dry_run": g["dry_run"]}


__all__ = ["router"]
