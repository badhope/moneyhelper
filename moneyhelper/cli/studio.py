"""CLI `moneyhelper studio` 子命令：与设置页共用同一存储与校验。

设计：不复制业务逻辑——本地直连 `app.studio.*`，远程走 HTTP `/api/studio/*`，
两条路径都落在同一套资产与权限规则上。
"""

from __future__ import annotations

import json
from typing import Any

from . import _die, _out, _remote


def _fmt_asset(a: dict[str, Any]) -> str:
    flag = "开" if a.get("enabled", True) else "关"
    return f"{a.get('id'):<28} [{flag}] {a.get('name', '')} — {str(a.get('description', ''))[:60]}"


def _asset_body(args: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"name": args.name, "description": args.description or ""}
    if args.content:
        body["content"] = args.content
        if args.kind == "roles":
            body["instructions"] = args.content
    if args.kind == "rules":
        body["severity"] = args.severity or "should"
        body["scope"] = args.scope or "all"
    if args.kind == "prompts":
        body["priority"] = args.priority or 50
    if not body.get("content"):
        _die("add 需要 --content（提示词/约束/技能正文；角色为指令正文）")
    return body


async def run(args: Any) -> int:
    from app import db
    from app.studio import installer, market, store

    if args.url:
        return await _remote_mode(args)

    await db.init_db()
    try:
        if args.action not in ("list", "show", "market") and not await store.cli_admin_allowed():
            _die("当前权限模式不允许 CLI 修改配置（请到设置 → 权限切换到「全面放开」）")
        if args.action == "list":
            if args.kind:
                assets = await store.list_assets(args.kind)
                _out(assets, args.json, "\n".join(_fmt_asset(a) for a in assets))
                return 0
            overview = {k: await store.list_assets(k) for k in store.ASSET_KINDS}
            if args.json:
                _out(overview, True, "")
            else:
                for k, items in overview.items():
                    print(f"[{k}] {len(items)} 项")
                    for a in items:
                        print("  " + _fmt_asset(a))
            return 0
        if args.action == "show":
            if not args.kind or not args.id:
                _die("show 需要 --kind 与 --id")
            assets = {a["id"]: a for a in await store.list_assets(args.kind)}
            if args.id not in assets:
                _die(f"资产不存在：{args.id}")
            _out(assets[args.id], args.json, json.dumps(assets[args.id], ensure_ascii=False, indent=2))
            return 0
        if args.action == "add":
            if not args.kind:
                _die("add 需要 --kind")
            body = _asset_body(args)
            asset_id = args.id or store.new_id(args.kind[:-1])
            saved = await store.upsert_asset(args.kind, asset_id, body)
            _out(saved, args.json, f"已添加 {args.kind}：{saved.get('name')}（id: {asset_id}）")
            return 0
        if args.action == "remove":
            if not args.kind or not args.id:
                _die("remove 需要 --kind 与 --id")
            await store.delete_asset(args.kind, args.id, force=bool(args.force))
            _out({"ok": True}, args.json, f"已删除 {args.kind}：{args.id}")
            return 0
        if args.action == "toggle":
            if not args.kind or not args.id:
                _die("toggle 需要 --kind 与 --id")
            updated = await store.set_enabled(args.kind, args.id, not args.off)
            if updated is None:
                _die(f"资产不存在：{args.id}")
            _out(updated, args.json, f"{args.id} → {'关闭' if args.off else '启用'}")
            return 0
        if args.action == "import":
            return await _import_local(args)
        if args.action == "market":
            items = market.catalog()
            if not args.install:
                if args.json:
                    _out(items, True, "")
                else:
                    for item in items:
                        print(f"{item['id']:<30} [{item['kind']}] {item['name']} — {item['description'][:50]}")
                    print("\n安装：moneyhelper studio market --install <id>")
                return 0
            result = await installer.install_market(args.install)
            _out(result, args.json, f"已安装：{args.install}")
            return 0
        if args.action == "ai":
            return await _ai_local(args)
        _die(f"未知动作：{args.action}")
    finally:
        await db.close_db()
    return 0


async def _import_local(args: Any) -> int:
    from pathlib import Path

    from app.studio import importer, store

    if not args.file:
        _die("import 需要 --file（.md/.json/.yaml/.zip）")
    path = Path(args.file)
    if not path.is_file():
        _die(f"文件不存在：{path}")
    try:
        entries = importer.parse_file(path.read_bytes(), path.name, args.kind or None)
    except importer.ImportErrorDetail as exc:
        _die(str(exc))
    saved: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for entry in entries:
        if "__zip_errors__" in entry:
            errors.extend(entry["__zip_errors__"])
            continue
        try:
            asset = await store.upsert_asset(entry["kind"], entry["id"], entry["asset"])
            saved.append({"kind": entry["kind"], "id": entry["id"], "name": asset.get("name", "")})
        except Exception as exc:  # noqa: BLE001 — 逐条回报
            errors.append({"file": entry.get("source", path.name), "error": str(exc)})
    if errors and not saved:
        _die("; ".join(f"{e['file']}: {e['error']}" for e in errors))
    text = f"已导入 {len(saved)} 项"
    if errors:
        text += f"，{len(errors)} 项失败：" + "; ".join(f"{e['file']}: {e['error']}" for e in errors[:3])
    _out({"saved": saved, "errors": errors}, args.json, text)
    return 0


async def _ai_local(args: Any) -> int:
    from app import llm
    from app.studio import commands

    if not args.prompt:
        _die("ai 需要 --prompt 描述（例如：每周日提醒我检查定投）")
    if not await llm.llm_available():
        _die("未接入模型：先在设置 → AI 回答配置模型端点")
    text = args.prompt
    if args.kind and not commands.detect_kind(text):
        label = {
            "prompts": "提示词",
            "rules": "约束",
            "hooks": "Hook",
            "roles": "角色",
            "skills": "技能",
        }[args.kind]
        text = f"添加{label} {text}"
    result = await commands.handle_question(text)
    if result is None:
        _die("无法识别为配置指令，请用「添加技能 名称：描述」格式")
    _out(result, args.json, str(result.get("answer") or result.get("error") or ""))
    return 0 if result.get("ok") else 1


async def _remote_mode(args: Any) -> int:
    if args.action == "list":
        if args.kind:
            data = await _remote("GET", args.url, args.token, f"/api/studio/{args.kind}", None)
            _out(data, args.json, "\n".join(_fmt_asset(a) for a in data.get("assets", [])))
            return 0
        data = await _remote("GET", args.url, args.token, "/api/studio/overview", None)
        _out(data, args.json, json.dumps(data.get("counts", {}), ensure_ascii=False, indent=2))
        return 0
    if args.action == "add":
        body = _asset_body(args)
        data = await _remote("POST", args.url, args.token, f"/api/studio/{args.kind}", body)
        if not data.get("ok"):
            _die(str(data.get("error") or "添加失败"))
        _out(data, args.json, f"已添加：{data['asset'].get('name')}")
        return 0
    if args.action == "remove":
        suffix = "?force=true" if args.force else ""
        await _remote(
            "DELETE", args.url, args.token, f"/api/studio/{args.kind}/{args.id}{suffix}", None
        )
        return 0
    _die("远程模式暂仅支持 list / add / remove；其余动作请在本地或设置页执行")
    return 1
