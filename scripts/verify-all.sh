#!/usr/bin/env bash
# 全量验收门禁：一条命令跑完所有层，避免"只跑了后端就说完成"。
#
# 层次（任一失败即退出）：
#   1. ruff 静态检查（backend/app+tests、moneyhelper）
#   2. 后端 pytest 全量（并行）
#   3. 前端 vitest 单测
#   4. 前端生产构建
#   5. Playwright E2E（可选，需要浏览器；--with-e2e 开启）
#   6. 真实模型验收（可选，需要 LLM_API_KEY；--with-live 开启）
#
# 用法：
#   bash scripts/verify-all.sh                 # 1-4
#   bash scripts/verify-all.sh --with-e2e      # +5
#   bash scripts/verify-all.sh --with-e2e --with-live
#
# 说明：
# - 端口由各层自己选非默认端口；本脚本不启动常驻服务，E2E 的 webServer
#   由 Playwright 管理并在结束后回收。
# - Chromium 二进制下载受限时，设 PLAYWRIGHT_CHANNEL=msedge 复用本机 Edge。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_E2E=0
WITH_LIVE=0
for arg in "$@"; do
  case "$arg" in
    --with-e2e) WITH_E2E=1 ;;
    --with-live) WITH_LIVE=1 ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/backend/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/backend/.venv/Scripts/python.exe"
elif [ -x "$ROOT/backend/.venv/bin/python" ]; then
  PY="$ROOT/backend/.venv/bin/python"
else
  echo "✗ 找不到虚拟环境解释器" >&2
  exit 1
fi

fail() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

step "1/4 ruff"
bash "$ROOT/scripts/lint.sh" || fail "ruff"
ok "ruff"

step "2/4 后端 pytest"
cd "$ROOT/backend" || fail "cd backend"
# 并发数按 CPU 核数取 min(4, cores)：这台开发机只有 2 核，`-n 4` 会把
# xdist worker 压到 "node down: Not properly terminated"（每次崩的用例都不同，
# 看起来像偶发，其实是资源超卖）。2 核跑 2 worker 实测 1705 项稳定全绿。
# --timeout=120 覆盖 pytest.ini 的 30s：并发下故障转移链等慢用例会超 30s。
CORES="$(python -c 'import os; print(os.cpu_count() or 2)' 2>/dev/null || echo 2)"
WORKERS=$(( CORES < 4 ? CORES : 4 ))
"$PY" -m pytest -n "$WORKERS" -q --timeout=120 || fail "后端 pytest"
ok "后端 pytest（${WORKERS} workers）"

step "3/4 前端 vitest"
cd "$ROOT/frontend" || fail "cd frontend"
npx vitest run || fail "前端 vitest"
ok "前端 vitest"

step "4/4 前端构建"
npm run build || fail "前端构建"
ok "前端构建"

if [ "$WITH_E2E" = "1" ]; then
  step "5/5 Playwright E2E"
  cd "$ROOT/frontend" || fail "cd frontend"
  npx playwright test --reporter=line || fail "Playwright E2E"
  ok "Playwright E2E"
fi

if [ "$WITH_LIVE" = "1" ]; then
  step "6/6 真实模型验收"
  if [ -z "${LLM_API_KEY:-}" ]; then
    fail "未设置 LLM_API_KEY，无法跑真实模型验收"
  fi
  cd "$ROOT" || fail "cd root"
  MONEYHELPER_DB_PATH="${MONEYHELPER_DB_PATH:-$ROOT/.tmp/verify-live.db}" \
    PYTHONPATH="$ROOT/backend" PYTHONIOENCODING=utf-8 \
    "$PY" scripts/verify_live.py || fail "真实模型验收"
  ok "真实模型验收"
fi

printf '\n\033[1;32m全部通过\033[0m\n'
