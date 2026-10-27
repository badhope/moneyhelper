"""Studio 导入器：把官方格式的文件解析成 Studio 资产。

支持的形态（与各生态官方格式对齐）：
- SKILL.md（Anthropic Agent Skills / Claude Code）：YAML frontmatter 的 name/description + 正文
- 单文件 Markdown（角色 / 规则 / 提示词）：标题/正文；可选 frontmatter
- JSON / YAML：资产对象或 {"prompts": {...}} 批量包；也接受 Claude Code 的 agent 定义
- ZIP：逐条解析内部文件，单个失败不拖累其余（返回 errors 明细）

校验失败一律给出「哪个文件、哪个字段、为什么」的错误，不静默丢弃。
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from typing import Any

try:
    import yaml
except Exception:  # noqa: BLE001 — PyYAML 缺失时退回 JSON-only（不阻塞导入主流程）
    yaml = None

MAX_FILE_BYTES = 512 * 1024
MAX_ZIP_FILES = 100
MAX_ZIP_TOTAL = 8 * 1024 * 1024
TEXT_SUFFIXES = (".md", ".markdown", ".txt", ".json", ".yaml", ".yml")
SKIP_PARTS = ("__MACOSX/", ".DS_Store", "/node_modules/", "/.git/")
DANGEROUS_PATH = re.compile(r"(^/|^[A-Za-z]:|\.\./)")


class ImportErrorDetail(Exception):
    """单条导入失败：携带文件名与字段级原因。"""


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ImportErrorDetail("文件不是 UTF-8 / GB18030 文本")


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """拆 YAML frontmatter（--- ... ---）。没有 frontmatter 返回 ({}, 原文)。"""
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return {}, text
    raw = m.group(1)
    body = text[m.end() :]
    if yaml is not None:
        try:
            meta = yaml.safe_load(raw) or {}
            if isinstance(meta, dict):
                return meta, body
        except Exception as exc:  # noqa: BLE001 — frontmatter 坏了按无 meta 处理，正文仍可导入
            raise ImportErrorDetail(f"frontmatter YAML 解析失败：{exc}") from exc
    meta: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip("'\"")
    return meta, body


def _slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(text or "").strip()).strip("-._").lower()
    return s[:64] or fallback


def _title_from_body(body: str) -> str:
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            return line.lstrip("#").strip()[:60]
    return ""


def parse_skill_md(text: str, filename: str) -> dict[str, Any]:
    meta, body = split_frontmatter(text)
    name = str(meta.get("name") or _title_from_body(body) or "").strip()
    desc = str(meta.get("description") or "").strip()
    if not name:
        raise ImportErrorDetail("SKILL.md 缺少 name（frontmatter 或一级标题）")
    if not body.strip():
        raise ImportErrorDetail("SKILL.md 正文为空")
    return {
        "kind": "skills",
        "id": _slug(meta.get("id") or name, "skill"),
        "asset": {
            "name": name[:60],
            "description": (desc or body.strip().splitlines()[0])[:300],
            "enabled": True,
            "content": body.strip()[:4000],
            "builtin": False,
        },
        "source": filename,
    }


def parse_markdown_asset(text: str, filename: str, kind: str) -> dict[str, Any]:
    meta, body = split_frontmatter(text)
    name = str(meta.get("name") or _title_from_body(body) or filename.rsplit("/", 1)[-1]).strip()
    content = body.strip()
    if not content:
        raise ImportErrorDetail("正文为空")
    if kind == "roles":
        return {
            "kind": "roles",
            "id": _slug(meta.get("id") or name, "role"),
            "asset": {
                "name": name[:60],
                "description": str(meta.get("description") or content.splitlines()[0])[:300],
                "enabled": True,
                "instructions": content[:8000],
                "tools": meta.get("tools") or "all",
                "temperature": float(meta.get("temperature") or 0.2),
                "builtin": False,
            },
            "source": filename,
        }
    if kind == "prompts":
        return {
            "kind": "prompts",
            "id": _slug(meta.get("id") or name, "prompt"),
            "asset": {
                "name": name[:60],
                "description": str(meta.get("description") or "")[:300],
                "enabled": True,
                "content": content[:8000],
                "category": str(meta.get("category") or "custom")[:24],
                "priority": int(meta.get("priority") or 50),
                "builtin": False,
            },
            "source": filename,
        }
    if kind == "rules":
        sev = str(meta.get("severity") or "should")
        return {
            "kind": "rules",
            "id": _slug(meta.get("id") or name, "rule"),
            "asset": {
                "name": name[:60],
                "description": str(meta.get("description") or "")[:300],
                "enabled": True,
                "content": content[:4000],
                "severity": sev if sev in ("must", "should", "may") else "should",
                "scope": str(meta.get("scope") or "all"),
                "builtin": False,
            },
            "source": filename,
        }
    raise ImportErrorDetail(f"Markdown 不能直接导入为 {kind}")


_KIND_ALIASES = {
    "prompt": "prompts",
    "prompts": "prompts",
    "rule": "rules",
    "rules": "rules",
    "hook": "hooks",
    "hooks": "hooks",
    "agent": "roles",
    "agents": "roles",
    "role": "roles",
    "roles": "roles",
    "skill": "skills",
    "skills": "skills",
}


def _asset_from_mapping(kind: str, aid: str, raw: dict[str, Any], filename: str) -> dict[str, Any]:
    asset = dict(raw)
    if kind == "roles" and "instructions" not in asset and "content" in asset:
        asset["instructions"] = asset.get("content")
    if kind == "skills" and "content" not in asset and "description" in asset:
        asset["content"] = asset.get("description")
    asset.setdefault("builtin", False)
    return {"kind": kind, "id": _slug(aid or asset.get("name") or "", kind[:-1]), "asset": asset, "source": filename}


def parse_json_like(text: str, filename: str, default_kind: str | None) -> list[dict[str, Any]]:
    """解析 JSON/YAML：单资产、资产包或 Claude Code agent 定义。"""
    try:
        if filename.lower().endswith((".yaml", ".yml")):
            if yaml is None:
                raise ImportErrorDetail("缺少 PyYAML，无法解析 YAML；请改用 JSON")
            data = yaml.safe_load(text)
        else:
            data = json.loads(text)
    except ImportErrorDetail:
        raise
    except Exception as exc:  # noqa: BLE001 — 语法错误要指到行
        raise ImportErrorDetail(f"JSON/YAML 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ImportErrorDetail("顶层必须是 JSON 对象")
    out: list[dict[str, Any]] = []
    named_kind = None
    for key in ("prompts", "rules", "hooks", "agents", "roles", "skills"):
        if isinstance(data.get(key), dict):
            named_kind = key
            kind = _KIND_ALIASES[key]
            for aid, raw in data[key].items():
                if not isinstance(raw, dict):
                    raise ImportErrorDetail(f"{key}.{aid} 必须是对象")
                out.append(_asset_from_mapping(kind, str(aid), raw, filename))
            break
    if named_kind is None:
        kind = _KIND_ALIASES.get(str(data.get("kind") or "").lower().strip())
        if kind is None and default_kind:
            kind = default_kind
        if kind is None and ("instructions" in data or "system_prompt" in data):
            kind = "roles"
        if kind is None and "name" in data and "description" in data:
            kind = "skills"
        if kind is None:
            raise ImportErrorDetail(
                "无法判断资产类型：请提供 kind 字段（prompts/rules/hooks/roles/skills）或在文件名中体现"
            )
        asset = dict(data)
        asset.setdefault("instructions", data.get("system_prompt"))
        aid = str(data.pop("id", "") or data.get("name") or "")
        out.append(_asset_from_mapping(kind, aid, asset, filename))
    return out


def parse_file(data: bytes, filename: str, default_kind: str | None = None) -> list[dict[str, Any]]:
    if len(data) > MAX_FILE_BYTES:
        raise ImportErrorDetail(f"文件超过 {MAX_FILE_BYTES // 1024} KB 上限")
    if filename.endswith((".zip",)):
        return parse_zip(data, filename, default_kind)
    text = _decode(data)
    lower = filename.lower()
    if lower.endswith("skill.md"):
        return [parse_skill_md(text, filename)]
    if lower.endswith((".json", ".yaml", ".yml")):
        return parse_json_like(text, filename, default_kind)
    if lower.endswith((".md", ".markdown", ".txt")):
        meta, _ = split_frontmatter(text)
        kind = _KIND_ALIASES.get(str(meta.get("kind") or "").lower().strip()) or default_kind
        if kind == "skills":
            # 目标类型就是技能：按 SKILL.md 官方语义解析（frontmatter name/description + 正文）
            return [parse_skill_md(text, filename)]
        if kind is None:
            if "instructions" in meta:
                kind = "roles"
            elif "severity" in meta:
                kind = "rules"
            else:
                # 无 frontmatter 的普通 md：按 SKILL.md 官方语义作为技能导入（Anthropic 默认形态）
                return [parse_skill_md(text, filename)]
        return [parse_markdown_asset(text, filename, kind)]
    raise ImportErrorDetail(f"不支持的文件类型：{filename}（支持 .md/.json/.yaml/.yml/.txt/.zip）")


def parse_zip(data: bytes, filename: str, default_kind: str | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportErrorDetail(f"不是合法的 zip 压缩包：{exc}") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if len(infos) > MAX_ZIP_FILES:
        raise ImportErrorDetail(f"压缩包内文件过多（{len(infos)} > {MAX_ZIP_FILES}）")
    total = sum(i.file_size for i in infos)
    if total > MAX_ZIP_TOTAL:
        raise ImportErrorDetail(f"压缩包解压后超过 {MAX_ZIP_TOTAL // 1024 // 1024} MB 上限")
    for info in infos:
        name = info.filename
        if any(part in name for part in SKIP_PARTS) or DANGEROUS_PATH.search(name):
            continue
        if not name.lower().endswith(TEXT_SUFFIXES):
            continue
        try:
            chunk = zf.read(info)
            results.extend(parse_file(chunk, name, default_kind))
        except ImportErrorDetail as exc:
            errors.append({"file": name, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — 单文件异常不影响其余
            errors.append({"file": name, "error": f"{type(exc).__name__}: {exc}"})
    return [{"__zip_errors__": errors}] if not results else [*results, {"__zip_errors__": errors}]
