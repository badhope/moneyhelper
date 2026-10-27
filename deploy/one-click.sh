#!/usr/bin/env bash
# Moneyhelper · 一键部署（本地或服务器）
#
# 用法：
#   ./deploy/one-click.sh              # Docker 部署（推荐，含前端构建）
#   ./deploy/one-click.sh --local      # 本机直跑（venv + npm，不装 Docker）
#   ./deploy/one-click.sh --port 9000  # 自定义端口
#
# 脚本会：
#   1. 检查端口占用（避免旧进程导致静默失败）
#   2. 未配置 .env 时提示从 .env.example 复制（不覆盖已有配置）
#   3. Docker 模式：docker compose up -d --build 并等待健康检查
#      本机模式：建 venv、装依赖、构建前端、起 uvicorn
#   4. 打印访问地址与后续排障命令
#
# 设计原则：**失败要吼出来**。任何一步失败立即非零退出并给出可执行的下一步，
# 而不是留下一个"看起来启动了但打不开"的服务。

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="docker"
PORT="8787"
for arg in "$@"; do
  case "$arg" in
    --local) MODE="local" ;;
    --docker) MODE="docker" ;;
    --port) shift_next=1 ;;
    --port=*) PORT="${arg#--port=}" ;;
    -h|--help)
      sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      if [ "${shift_next:-0}" = "1" ]; then PORT="$arg"; shift_next=0
      else
        echo "未知参数：$arg（用 --help 看用法）" >&2
        exit 1
      fi
      ;;
  esac
done

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m警告:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 端口预检
# ---------------------------------------------------------------------------
port_busy() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -i ":$port" -sTCP:LISTEN -t >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | grep -q ":$port"
  else
    return 1
  fi
}

if port_busy "$PORT"; then
  die "端口 $PORT 已被占用。先停止占用进程（lsof -i :$PORT），或用 --port 换一个端口。"
fi

# ---------------------------------------------------------------------------
# 环境变量文件
# ---------------------------------------------------------------------------
if [ ! -f .env ] && [ -f backend/.env.example ]; then
  say "未发现 .env，已从 backend/.env.example 复制一份（可留空，全部可选）"
  cp backend/.env.example .env
fi

# ---------------------------------------------------------------------------
# Docker 模式
# ---------------------------------------------------------------------------
if [ "$MODE" = "docker" ]; then
  command -v docker >/dev/null 2>&1 || die "未安装 Docker。用 --local 走本机直跑，或先装 Docker。"

  say "构建并启动容器（首次构建约 3-8 分钟）"
  docker compose up -d --build || die "docker compose 失败，查看上方日志"

  say "等待服务就绪"
  for i in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
      say "服务已就绪：http://127.0.0.1:${PORT}"
      echo
      echo "  查看日志：docker compose logs -f moneyhelper"
      echo "  停止服务：docker compose down"
      echo "  数据卷：  docker volume inspect moneyhelper_moneyhelper-data"
      exit 0
    fi
    sleep 2
  done
  die "等待 120 秒后 /api/health 仍不可用。查看：docker compose logs --tail=100 moneyhelper"
fi

# ---------------------------------------------------------------------------
# 本机模式
# ---------------------------------------------------------------------------
say "检查依赖"
# Python 命令按平台探测：Windows 常只有 python，没有 python3
PYCMD=""
for c in python3 python py; do
  if command -v "$c" >/dev/null 2>&1; then PYCMD="$c"; break; fi
done
[ -n "$PYCMD" ] || die "缺少 Python（需 3.10+）"
command -v node >/dev/null 2>&1 || die "缺少 node（需 18+）"

BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

venv_py() {
  if [ -x "$BACKEND/.venv/bin/python" ]; then echo "$BACKEND/.venv/bin/python"
  elif [ -x "$BACKEND/.venv/Scripts/python.exe" ]; then echo "$BACKEND/.venv/Scripts/python.exe"
  else echo ""; fi
}

if [ -z "$(venv_py)" ]; then
  say "创建虚拟环境"
  "$PYCMD" -m venv "$BACKEND/.venv"
fi
VPY="$(venv_py)"

if ! "$VPY" -c "import fastapi, uvicorn, aiosqlite" >/dev/null 2>&1; then
  say "安装后端依赖（国内镜像）"
  "$VPY" -m pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r "$BACKEND/requirements.txt"
fi

if [ ! -d "$FRONTEND/node_modules" ]; then
  say "安装前端依赖"
  (cd "$FRONTEND" && npm install --no-audit --no-fund)
fi

say "构建前端（同域单端口托管）"
(cd "$FRONTEND" && npm run build)

say "启动服务：http://127.0.0.1:${PORT}"
echo
echo "  按 Ctrl+C 停止"
echo "  API 文档：http://127.0.0.1:${PORT}/docs"
echo
cd "$BACKEND"
exec "$VPY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
