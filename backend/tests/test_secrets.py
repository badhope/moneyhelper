"""仓库级密钥扫描：防止真实密钥再次被提交进代码树。

只扫工作区文件（不扫 git 历史——历史里的泄漏靠轮换密钥处置，改写历史是破坏性操作）。
命中即 FAIL，模式按各家密钥的典型长度收窄，避免与项目自身的占位符（sk-your-key）
和测试固件（test-key）误报。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

# 高置信度密钥模式：前缀 + 足够长的随机串
SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "OpenAI 风格密钥": re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    "GitHub PAT": re.compile(r"\bghp_[A-Za-z0-9]{30,}"),
    "GitHub 新版 token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}"),
    "AWS Access Key ID": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    "私钥块": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
}

# 不扫描的目录与文件类型（二进制、依赖、构建产物、数据库、本地密钥文件）
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "dist", "build",
    "__pycache__", ".pytest_cache", ".aqg", "data", "preview",
}
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".db", ".db-wal",
    ".db-shm", ".sqlite", ".zip", ".woff", ".woff2", ".ttf", ".pdf",
}
MAX_BYTES = 1_000_000


def _iter_text_files():
    """只枚举 git 已追踪的文本文件（语义=「进入代码树的内容」，且避开 node_modules 等海量目录）。

    用 git ls-files 而非 rglob 全树遍历：SKIP_DIRS 里的目录本就 gitignore，
    全树遍历在 node_modules/dist 存在时会超时，且会把本不该进树的文件也扫一遍。
    """
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=True, cwd=REPO)
    if out.returncode != 0:
        return  # 非 git 环境（CI 快照等）：跳过，避免误伤
    for name in out.stdout.split("\0"):
        if not name:
            continue
        path = REPO / name
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.name in (".env",) or path.name.endswith(".db"):
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # 二进制或不可读：不是密钥落盘的位置
        yield path, text


@pytest.mark.parametrize("label", sorted(SECRET_PATTERNS))
def test_no_secret_in_working_tree(label: str) -> None:
    """工作区内不得出现真实密钥（.env 本地文件与 gitignore 内容不扫）。"""
    pattern = SECRET_PATTERNS[label]
    hits: list[str] = []
    for path, text in _iter_text_files():
        for match in pattern.finditer(text):
            rel = path.relative_to(REPO).as_posix()
            line_no = text.count("\n", 0, match.start()) + 1
            hits.append(f"{rel}:{line_no}")
    assert not hits, f"疑似{label}：{hits}（若为误报请改写为占位符；真实密钥请立即轮换）"


def test_env_example_has_no_real_key() -> None:
    """.env.example 只能是占位符。"""
    p = REPO / "backend" / ".env.example"
    if not p.exists():
        pytest.skip("无 .env.example")
    text = p.read_text(encoding="utf-8")
    for name, pattern in SECRET_PATTERNS.items():
        assert not pattern.search(text), f".env.example 含疑似{name}"
