#!/usr/bin/env bash
# 全仓库静态检查：与 CI 完全同一套命令，避免"本地过了 CI 挂"。
# CI 查 app/tests 与 moneyhelper 两处；本地只跑一处就会漏（历史上漏过一次）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Windows 的 venv 在 Scripts/，Unix 在 bin/：按存在性选择
if [ -x "$ROOT/backend/.venv/bin/python" ]; then
  PY="$ROOT/backend/.venv/bin/python"
elif [ -x "$ROOT/backend/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/backend/.venv/Scripts/python.exe"
else
  echo "✗ 找不到虚拟环境解释器（先跑 scripts/dev.sh 初始化）" >&2
  exit 1
fi

fail() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }
ok()   { printf '\033[1;32m✓\033[0m %s\n' "$*"; }

cd "$ROOT/backend"
"$PY" -m ruff check app tests || fail "ruff: backend/app + tests"
ok "ruff: backend/app + tests"

cd "$ROOT"
"$PY" -m ruff check moneyhelper || fail "ruff: moneyhelper 分层包"
ok "ruff: moneyhelper 分层包"
