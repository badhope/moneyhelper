"""安全边界回归：程序不能被自己改掉（切片 9）。

覆盖四条真实漏洞：
- M-1：只提交 allow_chat_admin=true 不得把权限隐式升到 open；
- M-2：内置安全 Hook 不能停用；
- M-4：parse_invoice 会写库，不能当只读工具直通；
- M-3：备份里的 settings 不能改写行为配置；
- pathguard：数据目录/数据库不能指向程序源码目录。
"""

from __future__ import annotations

import pytest
from app import tool_policy
from app.pathguard import assert_not_protected, is_protected
from app.studio import store


def test_permissions_do_not_implicitly_open() -> None:
    out, errors = store.validate_permissions({"allow_chat_admin": True})
    assert errors, "单独打开 allow_chat_admin 必须被拒绝"
    assert "mode" not in out, "缺失 mode 时不能补成 open"


def test_permissions_explicit_open_still_works() -> None:
    out, errors = store.validate_permissions(
        {"mode": "open", "allow_chat_admin": True, "allow_cli_admin": True}
    )
    assert not errors
    assert out["allow_chat_admin"] is True


def test_standard_mode_forces_programmatic_writes_off() -> None:
    out, errors = store.validate_permissions({"mode": "standard"})
    assert not errors
    assert out["allow_chat_admin"] is False
    assert out["allow_cli_admin"] is False
    assert out["allow_remote_install"] is False


async def test_builtin_hook_cannot_be_disabled(temp_db) -> None:
    """内置命令拦截 Hook 停用必须被拒；普通 Hook 仍可停用。"""
    with pytest.raises(PermissionError, match="内置安全 Hook"):
        await store.set_enabled("hooks", "block_shell_tools", False)

    cfg = await store.get_config()
    assert cfg["hooks"]["block_shell_tools"]["enabled"] is True

    # 非内置 Hook（默认包里 warn_long_answer 默认停用）可以切换
    out = await store.set_enabled("hooks", "warn_long_answer", True)
    assert out is not None and out["enabled"] is True


def test_parse_invoice_is_not_readonly() -> None:
    """parse_invoice 会写 invoices 表；必须是 ASK，不能直通。"""
    assert tool_policy.resolve("parse_invoice") == tool_policy.ASK


def test_pathguard_blocks_program_source() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert is_protected(root / "app" / "main.py")
    assert is_protected(root.parent / ".git" / "config")
    with pytest.raises(PermissionError):
        assert_not_protected(root / "app" / "main.py")

    # 数据目录不在保护范围
    assert not is_protected(root / "data" / "wealth.db")


async def test_data_dir_rejects_source_path(temp_db, monkeypatch) -> None:
    from pathlib import Path

    from app.db import _core

    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("MONEYHELPER_DATA_DIR", str(root / "app" / "data"))
    with pytest.raises(PermissionError):
        _core.data_dir()


async def test_backup_settings_whitelist_blocks_behavior_config(temp_db) -> None:
    """备份恢复不得写回 studio_config / agent_config / 系统提示词 / 模型端点。"""
    from app import db
    from app.db import backup

    await db.set_setting("studio_config", '{"permissions":{"mode":"open"}}')
    await db.set_setting("custom_system_prompt", "被注入的提示词")
    await db.set_setting("monthly_income", "10000")

    await backup.import_backup(
        {
            "settings": {
                "studio_config": '{"permissions":{"mode":"strict"}}',
                "agent_config": '{"skills":{"x":{}}}',
                "custom_system_prompt": "恶意提示词",
                "ai_base_url": "http://evil.example/v1",
                "monthly_income": "25000",
                "data_note": "restored",
            }
        }
    )

    settings = await db.get_settings()
    # 行为配置保持原值（白名单里的用户偏好会恢复）
    assert settings["studio_config"] == '{"permissions":{"mode":"open"}}'
    assert settings["custom_system_prompt"] == "被注入的提示词"
    assert settings["monthly_income"] == "25000"
    assert settings.get("ai_base_url", "") == ""
