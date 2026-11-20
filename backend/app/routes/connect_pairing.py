"""配对码与书签回传：签发配对码、生成 bookmarklet、页面文本入账抽取。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..connect import service, store
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(get_current_user)])

# ---------------------------------------------------------------------------
# 配对码（浏览器代登录 / 书签脚本）
# ---------------------------------------------------------------------------


@router.post("/api/connect/pairing")
async def issue_pairing(payload: dict[str, Any]) -> Any:
    try:
        return await store.issue_pairing_code(str((payload or {}).get("connector_id") or ""))
    except ValueError as exc:
        return _bad(str(exc))


@router.get("/api/connect/pairing/{cid}/bookmarklet")
async def pairing_bookmarklet(cid: str, lang: str = "zh") -> Any:
    """为该连接器生成书签脚本（含新配对码），用户拖到书签栏即可一键回传。"""
    try:
        pairing = await store.issue_pairing_code(cid)
    except ValueError as exc:
        return _bad(str(exc), 404)
    from ..compat_env import getenv

    base = getenv("MONEYHELPER_PUBLIC_URL").strip() or "http://127.0.0.1:8788"
    return {
        "pairing": pairing,
        "bookmarklet": service.build_bookmarklet(base, pairing["code"], cid, lang),
        "ingest_endpoint": f"{base.rstrip('/')}/api/connect/ingest",
        "how_to": "把 bookmarklet 拖到浏览器书签栏 → 打开官方页面并登录 → 点该书签 → 页面数据自动回传",
    }


@router.post("/api/connect/ingest")
async def ingest_page(payload: dict[str, Any]) -> Any:
    """书签脚本回传入口：校验配对码 → 解析页面文本里的账单行 → 入账。

    只接受文本；不保存原始页面快照（避免把用户隐私页面整页留库）。
    """
    code = str((payload or {}).get("code") or "").strip()
    connector_id = str((payload or {}).get("connector_id") or "").strip()
    text = str((payload or {}).get("text") or "")
    title = str((payload or {}).get("title") or "")[:120]
    if not code:
        return _bad("缺少配对码")
    if not text.strip():
        return _bad("页面没有可解析的文本")
    try:
        redeemed = await store.redeem_pairing_code(code, connector_id)
    except ValueError as exc:
        return _bad(str(exc), 403)

    # 免登录通道：租户由配对码决定（配对码只能写、不能读，且用后即焚）
    from ..db.tenant import reset_current_user_id, set_current_user_id

    tenant_token = set_current_user_id(int(redeemed.get("user_id") or 0))
    try:
        return await _ingest_rows(text, title, connector_id)
    finally:
        reset_current_user_id(tenant_token)


async def _ingest_rows(text: str, title: str, connector_id: str) -> Any:
    # 页面文本里通常夹着导航/页脚：只保留看起来像账单的行，交给通用 CSV 解析器会失败，
    # 因此这里按「日期 + 金额」的宽松规则抽取。
    rows = _extract_rows(text)
    if not rows:
        return {
            "ok": True,
            "imported": 0,
            "message": f"已收到页面「{title}」，但没有识别到账单行；可改用官方导出 CSV 导入",
        }
    from .. import db
    from ..provenance import record_provenance

    existing = {(r["date"], round(float(r["amount"]), 2), r["item"]) for r in await db.list_transactions()}
    imported = 0
    for r in rows:
        key = (r["date"], round(r["amount"], 2), r["item"])
        if key in existing:
            continue
        await db.add_transaction(r["date"], r["item"][:40], r["category"], r["amount"])
        existing.add(key)
        imported += 1
    if imported:
        await record_provenance(
            action="connect_ingest_page",
            entity_type="transaction",
            entity_id=f"batch:{imported}",
            before=None,
            after={"imported": imported, "connector_id": connector_id, "title": title},
            source="connect",
        )
    return {"ok": True, "imported": imported, "title": title, "message": f"已从页面入账 {imported} 笔"}


def _extract_rows(text: str) -> list[dict[str, Any]]:
    """从任意页面文本抽取账单行：日期 + 描述 + 金额（±）。"""
    import re

    date_re = re.compile(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})")
    # 千分位分组必须是「至少一组逗号」，否则 12000.00 会被截成 120 —— 旧写法实测漏了整行
    amount_re = re.compile(
        r"([+-]?)\s*[¥￥]?\s*(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    )
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        raw = line.strip()
        if not raw or len(raw) < 8 or len(raw) > 300:
            continue
        m = date_re.search(raw)
        if not m:
            continue
        amounts = amount_re.findall(raw[m.end():])
        if not amounts:
            continue
        sign, num = amounts[-1]
        try:
            value = float(num.replace(",", ""))
        except ValueError:
            continue
        if value <= 0:
            continue
        # 描述 = 日期之后的片段，去掉金额与常见状态词
        desc = raw[m.end():]
        desc = amount_re.sub(" ", desc)
        desc = re.sub(r"\s+", " ", desc).strip(" ,，|") or "页面回传"
        from ..csvimport import classify as auto_classify

        out.append(
            {
                "date": f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}",
                "item": desc[:80],
                "amount": -value if sign != "+" else value,
                "category": auto_classify(desc) or "其他",
            }
        )
        if len(out) >= 500:
            break
    return out
