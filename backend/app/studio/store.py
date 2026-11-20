"""Studio 配置存储：提示词 / 约束 / Hook / 权限 / 内置科研工具 / 市场安装记录。

与 agent_config.py 的分工：角色与技能（agents/skills）仍由 agent_config 持有，
Studio 负责其余资产并提供统一的导入/生成/校验入口。所有资产都存在 settings 表
`studio_config` 键下，随备份导出、随租户隔离。

本文件是门面：持久化、权限、资产 CRUD、Hook/提示词、其余设置分居 store_*.py，
调用方仍从 `app.studio.store` 取同一个名字。
"""

# ---------------------------------------------------------------------------
# 配置中心按职责拆分：持久化 / 权限 / 资产 / Hook / 其它设置
# ---------------------------------------------------------------------------
from .store_assets import (  # noqa: F401
    _active,
    delete_asset,
    list_assets,
    normalize_asset,
    set_enabled,
    upsert_asset,
)
from .store_core import (  # noqa: F401
    APPROVAL_FLOOR,
    ASSET_KINDS,
    BUILTIN_PROTECTED_HOOKS,
    CORE_LOCKED,
    DEFAULT_STUDIO,
    HOOK_ACTIONS,
    HOOK_EVENTS,
    PERMISSION_MODES,
    SETTINGS_KEY,
    SEVERITIES,
    _read,
    _write,
    get_config,
    load_default,
    mutate_config,
    new_id,
    now_iso,
)
from .store_extras import (  # noqa: F401
    internal_tools_enabled,
    primary_role,
    set_internal_tool,
    set_internal_tools_enabled,
    set_primary_role,
    set_watchdog,
    watchdog_settings,
)
from .store_hooks import (  # noqa: F401
    build_system_prompt,
    run_post_answer,
    run_pre_tool,
)
from .store_permissions import (  # noqa: F401
    chat_admin_allowed,
    cli_admin_allowed,
    permission_mode,
    permissions,
    update_permissions,
    validate_permissions,
)

# 兼容内部旧调用名
_mutate = mutate_config
