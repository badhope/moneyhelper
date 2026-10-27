#!/usr/bin/env bash
# Moneyhelper · 一键开发启动（后端 8788 + 前端 dev 5198，Ctrl-C 一起退出）。
#
# 跨平台：macOS / Linux / Windows（Git Bash、MSYS2、WSL 均可用）。
#   - venv 解释器自动探测：Unix 是 .venv/bin/python，Windows 是 .venv/Scripts/python.exe
#   - Python 命令按 python3 → python → py 顺序探测（Windows 常只有 python）
#   - 端口预检兼容 lsof / ss / netstat（Windows 原生没有前两个）
#
# 用法：scripts/dev.sh          # 开发模式（热更新）
#       scripts/dev.sh --prod   # 生产模式：构建前端后由后端单端口 8788 伺服
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
MODE="dev"
for arg in "$@"; do
  case "$arg" in
    --prod) MODE="prod" ;;
    -h|--help) sed -n '9,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 1 ;;
  esac
done

# ---- 解释器与 venv 路径（按平台选） ----------------------------------------
PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
[ -n "$PY" ] || { echo "✗ 缺少 Python（需 3.10+）"; exit 1; }

# Windows 的 venv 在 Scripts/，其它平台在 bin/
venv_py() {
  if [ -x "$BACKEND/.venv/bin/python" ]; then
    echo "$BACKEND/.venv/bin/python"
  elif [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then
    echo "$BACKEND/.venv/Scripts/python.exe"
  else
    echo ""
  fi
}

command -v node >/dev/null 2>&1 || { echo "✗ 缺少 node（需 18+）"; exit 1; }
command -v npm  >/dev/null 2>&1 || { echo "✗ 缺少 npm"; exit 1; }

# ---- 端口占用预检 ----------------------------------------------------------
port_busy() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -i ":$port" -sTCP:LISTEN -t >/dev/null 2>&1 && return 0
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | grep -q ":$port" && return 0
  elif command -v netstat >/dev/null 2>&1; then
    netstat -ano 2>/dev/null | grep -E "[.:]$port[[:space:]]" | grep -qi "LISTEN" && return 0
  fi
  return 1
}

PORTS="8788"
[ "$MODE" = "dev" ] && PORTS="8788 5198"
for _p in $PORTS; do
  if port_busy "$_p"; then
    echo "✗ 端口 $_p 已被占用，请先释放后重试"
    exit 1
  fi
done

# ---- 后端依赖 --------------------------------------------------------------
if [ -z "$(venv_py)" ]; then
  echo "== 创建后端虚拟环境 =="
  "$PY" -m venv "$BACKEND/.venv"
fi
VPY="$(venv_py)"
[ -n "$VPY" ] || { echo "✗ 虚拟环境创建失败"; exit 1; }
if ! "$VPY" -c "import fastapi, uvicorn, aiosqlite, fastmcp" >/dev/null 2>&1; then
  echo "== 安装后端依赖 =="
  "$VPY" -m pip install -q --disable-pip-version-check -r "$BACKEND/requirements.txt"
fi

# ---- 前端依赖 --------------------------------------------------------------
if [ ! -d "$FRONTEND/node_modules" ]; then
  echo "== 安装前端依赖 =="
  (cd "$FRONTEND" && npm install --no-audit --no-fund)
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [ "$MODE" = "prod" ]; then
  echo "== 构建前端 =="
  (cd "$FRONTEND" && npm run build)
  echo "== 启动后端（单端口）http://127.0.0.1:8788 =="
  cd "$BACKEND" && exec "$VPY" -m uvicorn app.main:app --host 127.0.0.1 --port 8788
fi

echo "== 启动后端 http://127.0.0.1:8788 =="
(cd "$BACKEND" && "$VPY" -m uvicorn app.main:app --host 127.0.0.1 --port 8788) &
echo "== 启动前端 dev http://127.0.0.1:5198 =="
(cd "$FRONTEND" && npm run dev) &
wait
