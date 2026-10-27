#!/usr/bin/env bash
# 本地一键多仓推送：main + tags 推到 5 个远端（GitCode / Gitee / GitHub 三仓）。
#
# 拓扑（2026-10 现状）：
#   - 本地 remote：origin(GitCode) / gitee / gh-api(GitHub badhope)
#   - GitHub 另两个镜像仓（Morningstar202604/moneyhelper、X33834/moneyhelper）不入 remote，按 URL 直推
#   - GitHub 推送走本机代理 127.0.0.1:18888；代理不可达时明确报错并跳过该仓，不影响其他仓
#
# 凭据：从 ~/.zcode/secrets/accounts_cli.py env 读取，不写死在脚本里，也不打印。
#   GITCODE_TOKEN / GITEE_TOKEN / GH_BADHOPE_TOKEN / GH_MORNINGSTAR_TOKEN / GH_X33834_TOKEN
#
# 用法：
#   scripts/push-all.sh                    # 推送全部 5 个远端
#   scripts/push-all.sh --only gitee       # 只推一个（gitcode/gitee/gh-api/morningstar/x33834）
#   scripts/push-all.sh --dry-run          # 只打印将要执行的命令（token 打码）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# 非交互：缺凭据时直接失败，不要卡在用户名/口令提示上
export GIT_TERMINAL_PROMPT=0
export GCM_INTERACTIVE=never

DRY_RUN=0
ONLY=""
VALID_NAMES="gitcode gitee gh-api morningstar x33834"

normalize_name() {
  case "$1" in
    origin) echo gitcode ;;
    *) echo "$1" ;;
  esac
}

usage() {
  cat <<'EOF'
用法：
  scripts/push-all.sh                    # 推送全部 5 个远端
  scripts/push-all.sh --only gitee       # 只推一个（gitcode/gitee/gh-api/morningstar/x33834）
  scripts/push-all.sh --dry-run          # 只打印将要执行的命令（token 打码）
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --only)
      shift
      ONLY="$(normalize_name "${1:-}")"
      [ -n "$ONLY" ] || { echo "错误：--only 需要仓库名（$VALID_NAMES）" >&2; exit 2; }
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "未知参数：$1（用 --help 查看用法）" >&2; exit 2 ;;
  esac
  shift
done

if [ -n "$ONLY" ]; then
  case " $VALID_NAMES " in
    *" $ONLY "*) ;;
    *) echo "错误：未知仓库名 $ONLY（可选：$VALID_NAMES）" >&2; exit 2 ;;
  esac
fi

# ---- 凭据：只注入当前 shell 环境，不回显 ----------------------------------
ACCOUNTS_CLI="${MONEYHELPER_ACCOUNTS_CLI:-$HOME/.zcode/secrets/accounts_cli.py}"
PY=""
for cand in python3 python py; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done

if [ -f "$ACCOUNTS_CLI" ]; then
  if [ -n "$PY" ]; then
    eval "$("$PY" "$ACCOUNTS_CLI" env)"
  else
    echo "警告：未找到 Python，跳过凭据库加载（只能用已导出的环境变量）" >&2
  fi
else
  echo "警告：凭据库不存在（$ACCOUNTS_CLI），只能用已导出的环境变量" >&2
fi

# ---- 目标定义 --------------------------------------------------------------
# URL 里的用户名是平台要求：GitCode/Gitee 必须 oauth2，X33834 必须小写 x33834。
build_url() {
  local name="$1" token="$2"
  case "$name" in
    gitcode)     printf 'https://oauth2:%s@gitcode.com/badhope/moneyhelper.git' "$token" ;;
    gitee)       printf 'https://oauth2:%s@gitee.com/badhope/moneyhelper.git' "$token" ;;
    gh-api)      printf 'https://badhope:%s@github.com/badhope/moneyhelper.git' "$token" ;;
    morningstar) printf 'https://x-access-token:%s@github.com/Morningstar202604/moneyhelper.git' "$token" ;;
    x33834)      printf 'https://x33834:%s@github.com/X33834/moneyhelper.git' "$token" ;;
  esac
}

token_var() {
  case "$1" in
    gitcode)     echo GITCODE_TOKEN ;;
    gitee)       echo GITEE_TOKEN ;;
    gh-api)      echo GH_BADHOPE_TOKEN ;;
    morningstar) echo GH_MORNINGSTAR_TOKEN ;;
    x33834)      echo GH_X33834_TOKEN ;;
  esac
}

token_value() {
  case "$1" in
    gitcode)     printf '%s' "${GITCODE_TOKEN:-}" ;;
    gitee)       printf '%s' "${GITEE_TOKEN:-}" ;;
    gh-api)      printf '%s' "${GH_BADHOPE_TOKEN:-}" ;;
    morningstar) printf '%s' "${GH_MORNINGSTAR_TOKEN:-}" ;;
    x33834)      printf '%s' "${GH_X33834_TOKEN:-}" ;;
  esac
}

label_of() {
  case "$1" in
    gitcode)     echo "GitCode origin" ;;
    gitee)       echo "Gitee" ;;
    gh-api)      echo "GitHub badhope" ;;
    morningstar) echo "GitHub Morningstar202604" ;;
    x33834)      echo "GitHub X33834" ;;
  esac
}

# GitHub 走代理；GitCode/Gitee 直连
needs_proxy() {
  case "$1" in
    gitcode|gitee) return 1 ;;
    *) return 0 ;;
  esac
}

# 打码：把 URL 里第一个冒号后的口令段替换为 ***
mask_url() {
  sed -E 's#(https://[^:/@]+:)[^@]+@#\1***@#g'
}

# 代理连通性：bash 的 /dev/tcp 在 Windows Git Bash / macOS / Linux 都可用
proxy_ready() {
  (exec 3<>/dev/tcp/127.0.0.1/18888) 2>/dev/null
}

# ---- 推送 ------------------------------------------------------------------
OK_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0
RESULTS=""

push_one() {
  local name="$1"
  local label token var url git_opts status detail
  label="$(label_of "$name")"
  var="$(token_var "$name")"
  token="$(token_value "$name")"

  if [ -z "$token" ]; then
    echo "跳过 $label：缺少 $var（先运行 accounts_cli.py sync）" >&2
    SKIP_COUNT=$((SKIP_COUNT + 1))
    RESULTS="${RESULTS}${label}|跳过|缺少 ${var}
"
    return 0
  fi

  if needs_proxy "$name" && ! proxy_ready; then
    echo "错误：GitHub 代理 127.0.0.1:18888 不可达，跳过 $label（其他仓继续）" >&2
    SKIP_COUNT=$((SKIP_COUNT + 1))
    RESULTS="${RESULTS}${label}|跳过|代理 127.0.0.1:18888 不可达
"
    return 0
  fi

  url="$(build_url "$name" "$token")"
  git_opts=""
  if needs_proxy "$name"; then
    git_opts="-c http.proxy=http://127.0.0.1:18888 -c http.sslVerify=false"
  fi

  echo "── $label ──"
  # 两个 GitHub 镜像仓是单向副本，按镜像语义覆盖推送；三个主仓正常快进推送。
  local force=""
  case "$name" in
    morningstar|x33834) force="--force" ;;
  esac

  if [ "$DRY_RUN" = "1" ]; then
    echo "  git ${git_opts:+$git_opts }push $force $(printf '%s' "$url" | mask_url) main"
    echo "  git ${git_opts:+$git_opts }push $force $(printf '%s' "$url" | mask_url) --tags"
    SKIP_COUNT=$((SKIP_COUNT + 1))
    RESULTS="${RESULTS}${label}|dry-run|未执行
"
    return 0
  fi

  # 输出统一过滤凭据，避免远端报错把 URL 里的 token 带出来。
  # 用临时变量取退出码：管道最后一段是 sed，直接看管道状态会把失败吞掉。
  local out rc
  out="$(git $git_opts push $force "$url" main 2>&1)" && rc=0 || rc=$?
  printf '%s\n' "$out" | mask_url
  if [ "$rc" -ne 0 ]; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    RESULTS="${RESULTS}${label}|失败|main 推送失败（rc=$rc）
"
    return 0
  fi

  out="$(git $git_opts push $force "$url" --tags 2>&1)" && rc=0 || rc=$?
  printf '%s\n' "$out" | mask_url
  if [ "$rc" -ne 0 ]; then
    FAIL_COUNT=$((FAIL_COUNT + 1))
    RESULTS="${RESULTS}${label}|失败|tags 推送失败（rc=$rc）
"
    return 0
  fi

  OK_COUNT=$((OK_COUNT + 1))
  RESULTS="${RESULTS}${label}|成功|main + tags
"
}

echo "推送目标：$([ -n "$ONLY" ] && echo "$ONLY" || echo "$VALID_NAMES")"
[ "$DRY_RUN" = "1" ] && echo "模式：dry-run（只打印命令，不执行）"

for name in $VALID_NAMES; do
  if [ -n "$ONLY" ] && [ "$ONLY" != "$name" ]; then continue; fi
  push_one "$name"
done

# ---- 汇总 ------------------------------------------------------------------
echo
echo "汇总"
printf '%-26s %-8s %s\n' "仓库" "结果" "说明"
printf '%s\n' "$RESULTS" | while IFS='|' read -r label status detail; do
  [ -n "$label" ] || continue
  printf '%-26s %-8s %s\n' "$label" "$status" "$detail"
done

echo
if [ "$DRY_RUN" = "1" ]; then
  echo "dry-run 结束：未执行任何推送。"
  exit 0
fi
if [ "$FAIL_COUNT" -gt 0 ] || [ "$SKIP_COUNT" -gt 0 ]; then
  echo "未全部成功：成功 $OK_COUNT，失败 $FAIL_COUNT，跳过 $SKIP_COUNT。"
  exit 1
fi
echo "全部完成：成功 $OK_COUNT 个远端。"
