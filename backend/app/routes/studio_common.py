"""Studio 路由公共件：资产类型标签、变更审计、管理员/权限校验。"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from ..logging_utils import get_logger
from ..studio import store
from ._responses import fail as _err

log = get_logger(__name__)

KIND_LABELS = {
    "prompts": "提示词",
    "rules": "约束",
    "hooks": "Hook",
    "roles": "角色",
    "skills": "技能",
}


async def _audit(
    action: str, entity_type: str, before: dict | None, after: dict | None
) -> None:
    """Studio 变更审计（失败只记日志，不影响主流程）。"""
    try:
        from ..provenance import record_provenance

        await record_provenance(
            action=action,
            entity_type=entity_type,
            entity_id=entity_type,
            before=before,
            after=after,
            source="studio",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("studio audit failed (%s): %s", action, exc)


async def _require_admin(kind: str = "write") -> JSONResponse | None:
    if await store.chat_admin_allowed():
        return None
    return _err(
        "当前权限模式不允许修改 Studio 配置。请到「设置 → 权限」切换到「全面放开」。", 403
    )


def _check_kind(kind: str) -> JSONResponse | None:
    if kind not in store.ASSET_KINDS:
        return _err(f"未知资产类型：{kind}（可选 {'/'.join(store.ASSET_KINDS)}）")
    return None


# ---------------------------------------------------------------------------
# 概览与模板
# ---------------------------------------------------------------------------
