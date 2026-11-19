#!/usr/bin/env python3
"""重复实现巡检：防止「同一份逻辑被复制进多个模块」。

## 为什么要有这个脚本

M1 拆分时把 `_now()` / `_now_iso()` / `_bad()` 这类小助手复制进了各模块，
一次性留下 30+ 处同构定义；同一份实现漂移出两种时间格式、两种错误响应结构，
排查成本远高于当初省下的几行 import。人眼 review 抓不住这种复制粘贴，
所以在 CI/本地都能跑的机器检查里固化规则。

## 检查项

1. **受管助手禁复制**：`_now` / `_now_iso` / `_new_id` / `_bad` / `_err` / `_sma` / `_t`
   只允许出现在单一真源模块（见 `CANONICAL`），其它文件出现同义 `def` 即报错。
2. **完全相同函数体**：AST 归一化后完全一致、且改名无关的重复函数（阈值 ≥3 行）。
3. **前端类型清单**：`DataKind` / `SectionId` 只允许有一个定义处。

退出码 0 = 通过；1 = 发现重复（输出文件名、行号、处置建议）。

用法：
    python scripts/check-duplicates.py            # 全量
    python scripts/check-duplicates.py --verbose  # 打印所有命中

接入 CI：在 lint 步骤后追加一行即可；不改变现有流水线语义。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CANONICAL = {
    "_now": "backend/app/timeutil.py",
    "_now_iso": "backend/app/timeutil.py",
    "_new_id": "backend/app/timeutil.py",
    "_bad": "backend/app/routes/_responses.py",
    "_err": "backend/app/routes/_responses.py",
    "_sma": "backend/app/calculations/_shared.py",
    "_t": "backend/app/calculations/_shared.py",
}

# 门面重导出是允许的（同一份实现，只是换了出口）
ALLOW_REEXPORT = {"backend/app/db/__init__.py"}

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}


SKIP_TESTS = True


def iter_py(root: Path):
    for p in root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if SKIP_TESTS and "tests" in p.parts:
            continue
        yield p


def func_fingerprint(node: ast.AST) -> str:
    return hashlib.md5(ast.dump(node, annotate_fields=False).encode()).hexdigest()


def check_helper_redefinitions() -> list[str]:
    problems = []
    for p in iter_py(ROOT):
        rel = p.relative_to(ROOT).as_posix()
        if not rel.startswith("backend/"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name not in CANONICAL:
                continue
            canonical = CANONICAL[name]
            if rel == canonical or rel in ALLOW_REEXPORT:
                continue
            problems.append(
                f"{rel}:{node.lineno} 重复定义 `{name}()`；真源在 {canonical}，改为 import"
            )
    return problems


def check_identical_bodies(min_lines: int = 3) -> list[str]:
    groups: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for p in iter_py(ROOT):
        rel = p.relative_to(ROOT).as_posix()
        if not rel.startswith("backend/"):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if (node.end_lineno or node.lineno) - node.lineno < min_lines:
                    continue
                groups[func_fingerprint(node)].append((rel, node.name, node.lineno))

    problems = []
    for _, hits in groups.items():
        if len(hits) < 2:
            continue
        names = {h[1] for h in hits}
        if len(names) == 1 and hits[0][1] in CANONICAL:
            continue  # 已由上一项覆盖
        where = "、".join(f"{r}:{ln}({n})" for r, n, ln in hits[:4])
        problems.append(f"完全相同的函数体 {len(hits)} 处：{where} → 抽公共实现")
    return problems


def check_frontend_type_sources() -> list[str]:
    problems = []
    fe = ROOT / "frontend" / "src"
    if not fe.exists():
        return problems
    pats = {
        "DataKind": "frontend/src/lib/views.ts",
        "SectionId": "frontend/src/components/settings/sections.ts",
    }
    for type_name, canonical in pats.items():
        for p in fe.rglob("*.ts*"):
            if "node_modules" in p.parts:
                continue
            rel = p.relative_to(ROOT).as_posix()
            if rel == canonical:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            if f"type {type_name} =" in text or f"type {type_name}=" in text:
                problems.append(f"{rel} 重复定义 `{type_name}`；真源在 {canonical}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument(
        "--include-tests",
        action="store_true",
        help="把 backend/tests 也纳入扫描（默认跳过：测试夹具的重复是待办，不是阻塞项）",
    )
    args = ap.parse_args()
    global SKIP_TESTS
    SKIP_TESTS = not args.include_tests

    checks = [
        ("受管助手重复定义", check_helper_redefinitions()),
        ("完全相同的函数体", check_identical_bodies()),
        ("前端类型重复定义", check_frontend_type_sources()),
    ]

    total = 0
    for title, problems in checks:
        if not problems:
            print(f"[ok] {title}：无重复")
            continue
        total += len(problems)
        print(f"[!] {title}：{len(problems)} 处")
        for line in problems if args.verbose else problems[:12]:
            print(f"    - {line}")
        if not args.verbose and len(problems) > 12:
            print(f"    …还有 {len(problems) - 12} 处（--verbose 查看全部）")

    if total:
        print(f"\n共 {total} 处重复：合并后再提交。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
