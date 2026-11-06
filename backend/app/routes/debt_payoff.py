"""债务清偿规划路由（v4.14）：雪崩 / 雪球 / 自定义顺序 + 方法对比。

与 `/api/debts` 的区别：那是负债 CRUD（记「欠了多少」），这里回答
「按这个预算，先还哪笔、几月能还清、总共省多少利息」——是决策，不是台账。

设计取舍：
- 计划默认从账本已有的负债取数（balance/rate 已存在库里），
  只要求用户补两项库里没有的信息：每笔的最低月供、每月能多拿出多少。
  不让用户重新录一遍负债，避免两份数据漂移。
- 也允许完全从请求体传入 debts（试算「如果我再借一笔」的场景），
  传了就以请求体为准，不与库混合——混合会让用户搞不清用的是哪份数。
- 任何输入错误返回 400 并带上具体字段，不吞成 500。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from .. import db
from ..auth import get_current_user
from ..calculations import compare_methods, plan_payoff

router = APIRouter(dependencies=[Depends(get_current_user)])

MAX_DEBTS = 50
MAX_EXTRA = 10_000_000.0


def _bad(msg: str) -> JSONResponse:
    return JSONResponse({"error": msg}, status_code=400)


def _num(payload: dict[str, Any], key: str, default: float = 0.0) -> float:
    raw = (payload or {}).get(key, default)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{key} 必须是数字") from None


def _normalize_rate(raw: Any) -> float:
    """把账本里的年利率归一化到 0~1（小数口径）。

    1 以下按原值；1~100 之间视为百分数（18 → 0.18）；超出范围钳到 1.0。
    """
    try:
        v = float(raw or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if v != v or v in (float("inf"), float("-inf")):
        return 0.0
    if v < 0:
        return 0.0
    if v > 100:
        return 1.0
    return v / 100.0 if v > 1.0 else v


async def _debts_from_ledger(min_payments: dict[str, float]) -> list[dict[str, Any]]:
    """把账本里的负债转成规划输入。

    库里的 debts 只有 name/balance/rate/monthly/due_day：`monthly` 是**月供**
    （用于 DTI），正好可以当最低还款的默认值。用户在界面改过的值优先，
    因为实际账单的月供可能和记账时填的不一样。
    """
    rows = await db.list_debts()
    out: list[dict[str, Any]] = []
    for r in rows:
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        base_payment = float(r.get("monthly") or 0)
        override = min_payments.get(name)
        out.append(
            {
                "name": name,
                "balance": float(r.get("balance") or 0),
                # 账本表的 rate 没有范围约束：外部 API / 备份导入可能写进 18（本意 18%）。
                # 这里归一化到 0~1，而不是让规划页直接 400 打不开——数据脏不该让功能不可用。
                "rate": _normalize_rate(r.get("rate")),
                "min_payment": float(override) if override is not None else base_payment,
            }
        )
    return out


@router.get("/api/finance/debts/payoff")
async def get_payoff_plan(
    extra_payment: float = 0.0,
    method: Literal["avalanche", "snowball"] = "avalanche",
    include_schedule: bool | None = None,
) -> Any:
    """按账本当前负债生成清偿计划（GET 便于直接分享链接与书签）。"""
    if extra_payment < 0 or extra_payment > MAX_EXTRA:
        return _bad("额外还款额需在 0 ~ 10,000,000 之间")
    debts = await _debts_from_ledger({})
    if not debts:
        return {
            "available": False,
            "reason": "账本里还没有负债记录：先在「记账 → 负债」里录入欠款本金、利率与月供",
            "debts": [],
        }
    try:
        # 逐月明细：默认不返回。50 笔 × 600 月实测 1.16MB，而前端只用里程碑；
        # 需要明细的调用方显式要 ?include_schedule=true。
        want_schedule = include_schedule if include_schedule is not None else False
        plan = plan_payoff(
            debts, extra_payment=extra_payment, method=method, include_schedule=want_schedule
        )
    except (TypeError, OverflowError):
        return _bad("负债数据的字段类型不合法（金额/利率必须是数字）")
    except ValueError as exc:
        return _bad(str(exc))
    return {
        "available": True,
        "debts": debts,
        **plan.to_dict(include_schedule=want_schedule),
    }


@router.post("/api/finance/debts/payoff")
async def post_payoff_plan(payload: dict[str, Any] = Body(...)) -> Any:
    """试算：可完全用请求体传入负债，也可用账本负债 + 覆盖最低月供。"""
    body = payload or {}
    method = str(body.get("method") or "avalanche").strip().lower()
    if method not in ("avalanche", "snowball", "custom"):
        return _bad("method 只能是 avalanche / snowball / custom")

    try:
        extra = _num(body, "extra_payment")
    except ValueError as exc:
        return _bad(str(exc))
    if extra < 0 or extra > MAX_EXTRA:
        return _bad("额外还款额需在 0 ~ 10,000,000 之间")

    raw_debts = body.get("debts")
    if raw_debts is not None:
        if not isinstance(raw_debts, list):
            return _bad("debts 必须是数组")
        if len(raw_debts) > MAX_DEBTS:
            return _bad(f"一次最多规划 {MAX_DEBTS} 笔负债")
        # 不能静默丢弃非对象元素：用户少传一笔却看到 200，会以为方案已包含它
        if any(not isinstance(d, dict) for d in raw_debts):
            return _bad("debts 的每一项都必须是对象（含 name / balance / rate / min_payment）")
        debts = list(raw_debts)
    else:
        overrides_raw = body.get("min_payments") or {}
        if not isinstance(overrides_raw, dict):
            return _bad("min_payments 必须是对象（名称 → 月供）")
        overrides: dict[str, float] = {}
        for k, v in overrides_raw.items():
            try:
                overrides[str(k)] = float(v)
            except (TypeError, ValueError, OverflowError):
                return _bad(f"min_payments.{k} 必须是数字")
        debts = await _debts_from_ledger(overrides)

    if not debts:
        return {
            "available": False,
            "reason": "没有可规划的负债：请传入 debts 或先在账本里录入负债",
            "debts": [],
        }

    custom_order = body.get("custom_order")
    if custom_order is not None and not isinstance(custom_order, list):
        return _bad("custom_order 必须是名称数组")

    compare = bool(body.get("compare"))
    try:
        if compare and method != "custom":
            result = compare_methods(debts, extra)
            return {"available": True, "debts": debts, **result}
        plan = plan_payoff(
            debts,
            extra_payment=extra,
            method=method,  # type: ignore[arg-type]
            custom_order=[str(x) for x in custom_order] if custom_order else None,
            include_schedule=bool(body.get("include_schedule", False)),
        )
    except ValueError as exc:
        return _bad(str(exc))
    return {
        "available": True,
        "debts": debts,
        **plan.to_dict(include_schedule=bool(body.get("include_schedule", False))),
    }
