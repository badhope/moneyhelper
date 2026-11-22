"""个人财务数字身份证与月度结账复盘路由。

两条都是只读接口：身份证不落库、不复写账号；复盘不改流水、不冻结月份。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .. import auth, personal_review
from ._responses import bad as _bad

router = APIRouter(dependencies=[Depends(auth.get_current_user)])


@router.get("/api/identity/card")
async def get_identity_card(
    lang: str = "zh",
    user: dict[str, Any] | None = Depends(auth.get_current_user),
) -> Any:
    display_name = str((user or {}).get("display_name") or "").strip()
    return await personal_review.identity_card(lang=lang or "zh", display_name=display_name)


@router.get("/api/review/monthly/{month}")
async def get_monthly_review(month: str, lang: str = "zh") -> Any:
    try:
        return await personal_review.monthly_review(month, lang=lang or "zh")
    except ValueError as exc:
        return _bad(str(exc))


__all__ = ["router"]
