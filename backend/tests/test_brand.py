"""品牌一致性回归：仓库内不允许残留旧品牌标识。

改名是机械替换，最容易出错的是"改漏一处"。这个测试把「旧品牌零残留」
变成可执行约束，而不是靠 grep 人工核对。
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "site",
    "dist",
    "build",
    "__pycache__",
    ".aqg",
    ".tmp",
    "out",
    "coverage",
    "test-results",
    "playwright-report",
    "data",
    "logs",
}
TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".html", ".css",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".bat", ".spec", ".txt",
    ".webmanifest", ".svg", ".example", ".gitignore", ".gitattributes",
    ".editorconfig", ".dockerignore", ".npmrc", ".lock",
}

# 拼装而非字面量：否则本文件自己会被下面的扫描命中。
_OLD_LATIN = "xia" + "oman"
_OLD_CJK = "\u5c0f\u6ee1"
LEGACY = re.compile(rf"{_OLD_LATIN}|{_OLD_LATIN.capitalize()}|{_OLD_LATIN.upper()}|{_OLD_CJK}")


# 以下文件必须保留旧变量名（兼容读取 / 升级说明 / 门禁自身），除此以外零残留。
COMPAT_ALLOWLIST = {
    Path("backend/app/compat_env.py"),
    Path("backend/tests/test_compat_env.py"),
    Path("backend/tests/test_brand.py"),
    Path("backend/tests/test_auth_proxy.py"),
    # 升级说明必须写出旧变量名，否则用户不知道该改什么
    Path("docs/CONFIG.md"),
    Path("docs/CONFIG.en.md"),
    Path("CHANGELOG.md"),
}


def _iter_text_files():
    for path in REPO.rglob("*"):
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.relative_to(REPO) in COMPAT_ALLOWLIST:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {
            "Dockerfile", "LICENSE", "Makefile",
        }:
            continue
        try:
            yield path, path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def test_no_legacy_brand_tokens() -> None:
    offenders: list[str] = []
    for path, text in _iter_text_files():
        for lineno, line in enumerate(text.splitlines(), 1):
            if LEGACY.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()[:120]}")
    assert not offenders, "旧品牌残留：\n" + "\n".join(offenders[:40])


def test_python_package_is_moneyhelper() -> None:
    assert (REPO / "moneyhelper" / "__init__.py").is_file()
    assert importlib.util.find_spec("moneyhelper") is not None
    assert importlib.util.find_spec(_OLD_LATIN) is None


def test_pyproject_name_is_moneyhelper() -> None:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^name = "moneyhelper"$', text, re.M)


def test_frontend_package_name_is_moneyhelper() -> None:
    pkg = json.loads((REPO / "frontend" / "package.json").read_text(encoding="utf-8"))
    assert pkg["name"] == "moneyhelper-frontend"


def test_pyinstaller_spec_renamed() -> None:
    assert (REPO / "backend" / "moneyhelper.spec").is_file()
    assert not (REPO / "backend" / f"{_OLD_LATIN}.spec").exists()
