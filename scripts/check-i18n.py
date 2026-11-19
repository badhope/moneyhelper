#!/usr/bin/env python3
"""i18n 硬编码守卫 —— 只准变少，不准变多。

## 为什么不用 ESLint

前端没有 ESLint（也不打算为一条规则引入 ~100 个包、拖慢 CI）。这里用零依赖的
正则做「棘轮」：记录当前每个文件的硬编码中文条数（`scripts/i18n-baseline.json`），
任何人新增硬编码中文 → 该文件计数上升 → 本脚本失败。要迁移就先迁移、再 `--update`
把新基线写回，于是数字只会往下走。

## 什么算「硬编码中文」

只统计**会显示给用户**的文本：字符串字面量、模板字符串、JSX 文本节点。
注释里写中文不算（代码注释本来就该用中文）；`lib/lang/` 是词条表本身，跳过。

## 已知的合法中文

- `lib/level.ts` 这类「后端代号 → i18n key」的映射表：键是后端的**数据值**
  （如 `"L2 建议"`），不是界面文案，改成英文会让映射失配。
- 这类文件不必解释，棘轮只要求「不增长」。

用法：
    python3 scripts/check-i18n.py           # 校验（失败返回 1）
    python3 scripts/check-i18n.py --update  # 迁移后刷新基线
    python3 scripts/check-i18n.py -v        # 列出欠账最多的文件
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
BASELINE = Path(__file__).resolve().parent / "i18n-baseline.json"

CJK = re.compile(r"[\u4e00-\u9fff]")
# 字符串字面量 / 模板字符串（含跨行模板）
LITERAL = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`(?:[^`\\]|\\.)*`')
# JSX 文本节点：`>` 与 `<` 之间、且不含 `{}` 的一段
JSX_TEXT = re.compile(r">([^<>{}]+)<")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)//[^\n]*", "", src)
    return src


def count_hardcoded(path: Path) -> int:
    code = strip_comments(path.read_text(encoding="utf-8"))
    n = sum(1 for m in LITERAL.finditer(code) if CJK.search(m.group(0)))
    n += sum(1 for m in JSX_TEXT.finditer(code) if CJK.search(m.group(1)))
    return n


def collect() -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in sorted(SRC.rglob("*")):
        if p.suffix not in (".ts", ".tsx"):
            continue
        rel = p.relative_to(SRC).as_posix()
        if rel.startswith("lib/lang/"):
            continue
        if ".test." in rel:
            continue
        n = count_hardcoded(p)
        if n:
            counts[rel] = n
    return counts


def main(argv: list[str]) -> int:
    update = "--update" in argv
    verbose = "-v" in argv or "--verbose" in argv

    current = collect()
    if update:
        BASELINE.write_text(
            json.dumps(dict(sorted(current.items())), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        total = sum(current.values())
        print(f"✓ 基线已更新：{len(current)} 个文件、{total} 条硬编码中文")
        return 0

    if not BASELINE.exists():
        print("✗ 缺少 scripts/i18n-baseline.json，先跑 --update", file=sys.stderr)
        return 1
    baseline: dict[str, int] = json.loads(BASELINE.read_text(encoding="utf-8"))

    grew: list[str] = []
    for rel, n in sorted(current.items()):
        allowed = baseline.get(rel, 0)
        if n > allowed:
            grew.append(f"  {rel}: {allowed} → {n}（+{n - allowed}）")

    total_now = sum(current.values())
    total_base = sum(baseline.values())
    if grew:
        print("✗ 新增硬编码中文（请改用 t() 词条）：", file=sys.stderr)
        print("\n".join(grew), file=sys.stderr)
        print("\n若确实无法避免（如后端代号映射表），请说明理由后用 --update 刷新基线。", file=sys.stderr)
        return 1

    print(f"✓ i18n 守卫通过：{total_now} 条硬编码中文（基线 {total_base}）")
    if verbose:
        for rel, n in sorted(current.items(), key=lambda kv: -kv[1])[:12]:
            print(f"   {n:4d}  {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
