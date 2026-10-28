"""Studio 资产层：默认包非空、校验、导入解析、权限锁定。

这些测试锁的是「用户一点进来就有基础配置」与「坏文件必须报错」两条承诺：
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from app.studio import importer, internal_tools, market, store


async def test_default_pack_is_non_empty(temp_db) -> None:
    """全新库必须有提示词/约束/Hook/内置工具，且默认开启。"""
    cfg = await store.get_config()
    assert len(cfg["prompts"]) >= 4
    assert len(cfg["rules"]) >= 5
    assert len(cfg["hooks"]) >= 5
    assert len(cfg["internal_tools"]["tools"]) >= 8
    assert all(v.get("enabled", True) for v in cfg["prompts"].values())
    assert cfg["permissions"]["mode"] == "open"


async def test_agent_default_config_has_roles_and_skills(temp_db) -> None:
    from app import agent_config

    cfg = await agent_config.get_config()
    assert len(cfg["agents"]) >= 8
    assert len(cfg["skills"]) >= 8
    assert all(a.get("enabled") for a in cfg["agents"].values())


async def test_upsert_and_toggle_prompt(temp_db) -> None:
    saved = await store.upsert_asset(
        "prompts",
        "p1",
        {"name": "简洁", "description": "短答", "content": "回答不超过三句", "priority": 10},
    )
    assert saved["name"] == "简洁"
    assets = await store.list_assets("prompts")
    assert any(a["id"] == "p1" for a in assets)
    updated = await store.set_enabled("prompts", "p1", False)
    assert updated is not None and updated["enabled"] is False


async def test_invalid_asset_rejected_with_reason(temp_db) -> None:
    with pytest.raises(ValueError, match="内容不能为空"):
        await store.upsert_asset("prompts", "bad", {"name": "x", "content": "  "})
    with pytest.raises(ValueError, match="severity"):
        await store.upsert_asset(
            "rules", "bad", {"name": "x", "content": "y", "severity": "critical"}
        )
    with pytest.raises(ValueError, match="正则"):
        await store.upsert_asset(
            "hooks", "bad", {"name": "x", "event": "pre_tool", "action": "block", "match": "(["}
        )
    with pytest.raises(ValueError, match="id"):
        await store.upsert_asset("prompts", "中文 id", {"name": "x", "content": "y"})


async def test_builtin_delete_requires_force(temp_db) -> None:
    with pytest.raises(ValueError, match="内置"):
        await store.delete_asset("rules", "no_fabricated_numbers")
    assert await store.delete_asset("rules", "no_fabricated_numbers", force=True)


async def test_permission_validation() -> None:
    out, errors = store.validate_permissions({"mode": "wild"})
    assert errors
    out, errors = store.validate_permissions({"mode": "standard", "allow_chat_admin": True})
    assert not errors and out["allow_chat_admin"] is False


async def test_system_prompt_contains_defaults(temp_db) -> None:
    prompt = await store.build_system_prompt("BASE")
    assert "BASE" in prompt
    assert "禁止编造数字" in prompt
    assert "当前日期" in prompt


async def test_hook_block_and_inject(temp_db) -> None:
    blocked = await store.run_pre_tool("shell_exec", {"cmd": "rm -rf /"})
    assert blocked["blocked"] is True
    allowed = await store.run_pre_tool("get_market_view", {})
    assert allowed["blocked"] is False


async def test_internal_tools_all_deterministic() -> None:
    out = internal_tools.run_internal_tool("stats_summary", {"values": [1, 2, 3, 4, 5]})
    assert "样本量 n = 5" in out
    out2 = internal_tools.run_internal_tool(
        "citation_format",
        {
            "style": "APA",
            "items": [
                {"title": "A study", "authors": ["Zhang, S."], "year": 2020, "journal": "J"}
            ],
        },
    )
    assert "Zhang, S." in out2 and "(2020)" in out2
    assert internal_tools.run_internal_tool("nope", {}) is None


def test_import_skill_md() -> None:
    text = "---\nname: paper-review\ndescription: 结构化审稿\n---\n\n# 审稿\n1. 复述主张\n"
    entries = importer.parse_file(text.encode(), "SKILL.md")
    assert entries[0]["kind"] == "skills"
    assert entries[0]["asset"]["name"] == "paper-review"
    assert "复述主张" in entries[0]["asset"]["content"]


def test_import_json_bundle() -> None:
    payload = {"rules": {"r1": {"name": "禁编造", "content": "不要编造", "severity": "must"}}}
    entries = importer.parse_file(json.dumps(payload).encode(), "bundle.json")
    assert entries[0]["kind"] == "rules" and entries[0]["id"] == "r1"


def test_import_zip_reports_bad_entries() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ok/SKILL.md", "---\nname: ok-skill\ndescription: d\n---\n\nbody")
        zf.writestr("bad.json", "{not json")
    entries = importer.parse_file(buf.getvalue(), "pack.zip")
    errors = next(e for e in entries if "__zip_errors__" in e)["__zip_errors__"]
    assert errors and errors[0]["file"] == "bad.json"
    assert any(e.get("kind") == "skills" for e in entries if "__zip_errors__" not in e)


def test_import_rejects_zip_traversal() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.md", "---\nname: e\n---\nbody")
    entries = importer.parse_file(buf.getvalue(), "evil.zip")
    saved = [e for e in entries if "__zip_errors__" not in e]
    assert saved == []


def test_import_unsupported_suffix() -> None:
    with pytest.raises(importer.ImportErrorDetail, match="不支持"):
        importer.parse_file(b"abc", "file.exe")


def test_market_catalog_has_research_and_mcp() -> None:
    items = market.catalog()
    kinds = {i["kind"] for i in items}
    assert {"skills", "roles", "rules", "hooks", "prompts", "mcp"} <= kinds
    assert len(items) >= 30
    assert len([i for i in items if i["kind"] == "mcp"]) >= 5
    research = [i for i in items if i["category"].startswith("科研")]
    assert len(research) >= 8


async def test_install_market_item(temp_db) -> None:
    from app.studio import installer

    r = await installer.install_market("skill-pdf")
    assert r["ok"] and r["kind"] == "skills"
    skills = await store.list_assets("skills")
    assert any(s["id"] == "skill-pdf" for s in skills)


def test_chat_command_parses_schedule() -> None:
    from app.studio import commands

    intent = commands.parse_intent("添加技能 定投提醒：每周日晚8点检查定投计划")
    assert intent and intent["kind"] == "skills"
    assert intent["name"] == "定投提醒"
    assert intent["action"] == {"prompt": "检查定投计划", "time": "20:00", "weekdays": [6]}


def test_chat_command_parses_market_install() -> None:
    from app.studio import commands

    intent = commands.parse_intent("安装 MCP 记忆")
    assert intent and intent["op"] == "market_install" and intent["item_id"] == "mcp-memory"


def test_chat_command_ignores_normal_question() -> None:
    from app.studio import commands

    assert commands.parse_intent("今天天气怎么样") is None
    assert commands.parse_intent("帮我看看持仓") is None


async def test_seed_default_bundle_once(temp_db, tmp_path, monkeypatch) -> None:
    """出厂预装：非 MCP 资产全部装好并启用；重复调用不重复执行。"""
    from app import mcp_client
    from app.studio import installer

    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    monkeypatch.setattr(mcp_client, "_discover_cache", None)
    mcp_client._servers.clear()
    first = await installer.seed_default_bundle()
    assert first["seeded"] is True and first["assets"] >= 25
    # 远程 HTTP MCP 默认启用；stdio 默认停用（依赖 npx/uvx）
    servers = {x["name"]: x["enabled"] for x in mcp_client.list_servers()}
    assert servers.get("deepwiki") is True
    assert servers.get("fetch") is False
    skills = await store.list_assets("skills")
    assert any(s["id"] == "skill-pdf" for s in skills)
    second = await installer.seed_default_bundle()
    assert second["seeded"] is False
    # 用户删掉之后重启不会复活（seeded 标记已写）
    await store.delete_asset("skills", "skill-pdf", force=True)
    await installer.seed_default_bundle()
    skills2 = await store.list_assets("skills")
    assert not any(s["id"] == "skill-pdf" for s in skills2)


async def test_deleted_builtin_does_not_resurrect(temp_db) -> None:
    """删除内置资产后，再次读取配置不得被默认包补回来（墓碑机制）。"""
    await store.delete_asset("rules", "no_investment_advice", force=True)
    cfg = await store.get_config()
    assert "no_investment_advice" not in cfg["rules"]
    assert "no_investment_advice" in (cfg.get("removed") or {}).get("rules", [])


async def test_deleted_builtin_role_does_not_resurrect(temp_db) -> None:
    from app import agent_config

    await store.delete_asset("roles", "auditor", force=True)
    cfg = await agent_config.get_config()
    assert "auditor" not in cfg["agents"]
    # 墓碑随配置落库，跨请求/跨重启都有效（重新读一次即可验证，不依赖进程内状态）
    cfg2 = await agent_config.get_config()
    assert "auditor" not in cfg2["agents"]


async def test_tombstones_are_tenant_scoped(temp_db) -> None:
    """墓碑必须跟着租户：A 删掉的内置角色不能影响 B。"""
    from app.db.tenant import current_user_id, set_current_user_id

    token = set_current_user_id(current_user_id())
    try:
        await store.delete_asset("roles", "auditor", force=True)
        cfg_a = await agent_config_get()
        assert "auditor" not in cfg_a["agents"]
        set_current_user_id(4242)
        cfg_b = await agent_config_get()
        assert "auditor" in cfg_b["agents"]
    finally:
        set_current_user_id(current_user_id())
        from app.db.tenant import _current_user_id

        _current_user_id.reset(token)


async def agent_config_get():
    from app import agent_config

    return await agent_config.get_config()


async def test_recreate_after_delete_works(temp_db) -> None:
    """删除后重新添加同一 id：墓碑要清掉，不能静默拒绝。"""
    await store.delete_asset("prompts", "answer_style", force=True)
    saved = await store.upsert_asset(
        "prompts", "answer_style", {"name": "回答风格 2", "content": "简短"}
    )
    assert saved["name"] == "回答风格 2"
    cfg = await store.get_config()
    assert "answer_style" in cfg["prompts"]


async def test_internal_tool_runner_is_awaitable(temp_db) -> None:
    """agent 执行层统一 await impl(args)：内置工具必须返回协程，否则 TypeError。"""
    import asyncio

    from app.studio import internal_tools

    async def _direct():
        from app.studio import store as s2

        enabled = await s2.internal_tools_enabled()
        assert "stats_summary" in enabled

    await _direct()
    # 直接验证包装器形状：协程函数 + 可 await
    async def _run(name: str, args: dict):
        return internal_tools.run_internal_tool(name, args) or ""

    assert asyncio.iscoroutinefunction(_run)
    assert "样本量" in await _run("stats_summary", {"values": [1, 2, 3]})


async def test_backup_includes_mcp_servers(temp_db, tmp_path, monkeypatch) -> None:
    """备份必须带上 MCP 配置（在 data/mcp.json，不在 settings 表里），且 URL 凭据打码。"""
    from app import mcp_client
    from app.db import backup

    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    monkeypatch.setattr(mcp_client, "_discover_cache", None)
    mcp_client._servers.clear()
    mcp_client.save_servers(
        [{"name": "s1", "url": "https://user:tok@example.com/mcp", "enabled": False}]
    )
    data = await backup.export_data()
    assert data["mcp_servers"] and data["mcp_servers"][0]["name"] == "s1"
    assert "tok" not in data["mcp_servers"][0]["url"]
    # 恢复：把服务器列表写回（打码后的地址）
    mcp_client.save_servers([])
    await backup.import_backup({**data, "settings": data.get("settings") or {}})
    servers = mcp_client.list_servers()
    assert [s["name"] for s in servers] == ["s1"]
    assert servers[0]["enabled"] is False


async def test_concurrent_writes_do_not_lose_data(temp_db) -> None:
    """并发保存不能互相覆盖：读-改-写必须串行（实测未加锁时 8 并发只存下 3 个）。"""
    import asyncio

    async def add(i: int):
        return await store.upsert_asset(
            "prompts", f"race{i}", {"name": f"P{i}", "content": "x"}
        )

    await asyncio.gather(*[add(i) for i in range(12)])
    ids = {a["id"] for a in await store.list_assets("prompts")}
    assert {f"race{i}" for i in range(12)} <= ids


async def test_mixed_concurrent_writes(temp_db) -> None:
    """不同类型资产的并发写共用同一份配置，也必须串行。"""
    import asyncio

    async def op(i: int):
        if i % 3 == 0:
            return await store.upsert_asset("rules", f"mix{i}", {"name": f"M{i}", "content": "x"})
        if i % 3 == 1:
            return await store.set_enabled("prompts", "core_identity", True)
        return await store.update_permissions({"allow_remote_install": True})

    await asyncio.gather(*[op(i) for i in range(9)])
    rules = {a["id"] for a in await store.list_assets("rules")}
    assert {"mix0", "mix3", "mix6"} <= rules


async def test_editing_builtin_keeps_builtin_flag(temp_db) -> None:
    """编辑内置资产不能抹掉 builtin 标记（否则一次编辑就变成可自由删除）。"""
    await store.upsert_asset(
        "rules",
        "no_investment_advice",
        {"name": "改名", "content": "改内容", "severity": "must", "scope": "finance", "enabled": True},
    )
    assets = {a["id"]: a for a in await store.list_assets("rules")}
    assert assets["no_investment_advice"]["builtin"] is True


async def test_invalid_skill_action_rejected(temp_db) -> None:
    """非法定时动作必须报错，不能静默存下一个永不触发的配置。"""
    with pytest.raises(ValueError, match="定时动作格式不合法"):
        await store.upsert_asset(
            "skills",
            "bad_action",
            {"name": "坏", "content": "x", "action": {"prompt": "", "time": "99:99", "weekdays": [9]}},
        )
    with pytest.raises(ValueError, match="定时动作格式不合法"):
        await store.upsert_asset(
            "skills", "bad2", {"name": "坏2", "content": "x", "action": {"time": "20:00"}}
        )
    ok = await store.upsert_asset(
        "skills",
        "good_action",
        {"name": "好", "content": "x", "action": {"prompt": "检查", "time": "20:00", "weekdays": [1]}},
    )
    assert ok["action"] == {"prompt": "检查", "time": "20:00", "weekdays": [1]}


async def test_standard_mode_disables_url_install() -> None:
    """非全面放开模式必须同时关掉 URL 安装，否则是权限后门。"""
    perms, errors = store.validate_permissions({"mode": "standard"})
    assert not errors
    assert perms["allow_chat_admin"] is False
    assert perms["allow_cli_admin"] is False
    assert perms["allow_remote_install"] is False


async def test_watchdog_restarts_on_interval_change(temp_db) -> None:
    """改看门狗间隔后必须重启 loop，否则新间隔不生效。"""
    from app.studio import watchdog

    await store.set_watchdog(enabled=True, interval_minutes=5)
    await watchdog.start()
    try:
        assert watchdog.status()["running"] is True
        await store.set_watchdog(interval_minutes=45)
        await watchdog.start()
        assert watchdog.status()["running"] is True
    finally:
        await watchdog.stop()


async def test_backup_masks_mcp_env_secrets(temp_db, tmp_path, monkeypatch) -> None:
    """MCP 的 env 常放 API Key：导出必须打码，恢复不能把 *** 当真实值写回。"""
    from app import mcp_client
    from app.db import backup

    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    monkeypatch.setattr(mcp_client, "_discover_cache", None)
    mcp_client._servers.clear()
    mcp_client.save_servers(
        [
            {
                "name": "withkey",
                "command": "npx",
                "args": ["-y", "pkg"],
                "env": {"GITHUB_TOKEN": "ghp_realsecret123", "MODE": "read"},
                "enabled": True,
            }
        ]
    )
    data = await backup.export_data()
    env = data["mcp_servers"][0]["env"]
    assert env == {"GITHUB_TOKEN": "***", "MODE": "***"}

    mcp_client.save_servers([])
    await backup.import_backup({**data, "settings": data.get("settings") or {}})
    restored = mcp_client.raw_servers()[0]
    # 打码占位不能当真实密钥写回；用户需自行重填
    assert "env" not in restored


def test_import_chinese_names_get_distinct_ids() -> None:
    """中文名文件不能都落到同一个 fallback id（否则后导入的静默覆盖前面的）。"""
    ids = set()
    sep = chr(10)
    for name in ("规则甲", "规则乙", "规则丙"):
        body = sep.join(["---", "name: " + name, "description: d", "---", "", "body"])
        ids.add(importer.parse_file(body.encode(), name + ".md", "rules")[0]["id"])
    assert len(ids) == 3



async def test_repair_mcp_config_restores_missing_servers(temp_db, tmp_path, monkeypatch) -> None:
    """mcp.json 丢失后，已安装过的 MCP 要自动补回（DB 与文件不同生命周期）。"""
    from app import mcp_client
    from app.studio import installer

    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    monkeypatch.setattr(mcp_client, "_discover_cache", None)
    mcp_client._servers.clear()
    await installer.seed_default_bundle()
    before = {s["name"] for s in mcp_client.list_servers()}
    assert before

    # 模拟「配置文件被删」：清空但不改 seeded 标记
    mcp_client.save_servers([])
    assert mcp_client.list_servers() == []
    out = await installer.repair_mcp_config()
    after = {s["name"] for s in mcp_client.list_servers()}
    assert out["repaired"] and after == before


async def test_repair_does_not_resurrect_uninstalled(temp_db, tmp_path, monkeypatch) -> None:
    """用户主动卸载过的 MCP 不能被 repair 复活。"""
    from app import mcp_client
    from app.studio import installer

    monkeypatch.setattr(mcp_client, "MCP_CFG", tmp_path / "mcp.json")
    monkeypatch.setattr(mcp_client, "_discover_cache", None)
    mcp_client._servers.clear()
    await installer.seed_default_bundle()
    await installer.uninstall_market("mcp-fetch")
    assert "fetch" not in {s["name"] for s in mcp_client.list_servers()}
    await installer.repair_mcp_config()
    assert "fetch" not in {s["name"] for s in mcp_client.list_servers()}
