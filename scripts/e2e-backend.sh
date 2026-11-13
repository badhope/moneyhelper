#!/usr/bin/env bash
# 后端 e2e 启动脚本：把数据库指向 backend/data/e2e.db，由 Playwright webServer 调用。
# 测试库每次跑都被 globalSetup 重新种入演示数据（见 frontend/e2e/global-setup.ts），
# 保证测试可重复；研发者日常 wealth.db 不受影响。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"

# 优先用项目 venv；缺则回退到系统 python（未装 requirements 时给明白的提示）
# Windows 的 venv 在 Scripts/，且解释器名是 python.exe（没有 python3）
# 本项目 venv 在仓库根 .venv（不是 backend/.venv），两处都要探测；
# 只找 backend/.venv 会静默回退到系统 Python，报出与项目无关的"uvicorn 未安装"。
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif [ -x "$BACKEND/.venv/bin/python" ]; then
  PY="$BACKEND/.venv/bin/python"
elif [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then
  PY="$BACKEND/.venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
else
  echo "[e2e] 未找到 Python，请安装 3.10+" >&2
  exit 7
fi

if ! "$PY" -c "import uvicorn" 2>/dev/null; then
  echo "[e2e] uvicorn 未安装，请先在 backend 执行: $PY -m pip install -r requirements.txt" >&2
  exit 7
fi

cd "$BACKEND"
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8788
