#!/usr/bin/env bash
# Moneyhelper 发版脚本：从 conventional commits 推导下一版版本号并完成发版准备。
#
# 用法：
#   ./scripts/release.sh --dry-run     # 只看会做什么，不改文件
#   ./scripts/release.sh               # 执行：改版本号 + 生成 CHANGELOG 条目 + 提交 + 打 tag
#
# 设计原则：
# - **版本号单一真源**：只改 backend/app/version.py，其余（pyproject / package.json /
#   前端注入）都由它派生或由脚本同步，避免三处漂移（历史上出现过 1.0.0/1.4.0/2.1.0 并存）
# - **提交即发布依据**：版本号从 git log 推导，不靠人记账
# - **可预演**：--dry-run 不修改任何文件
#
# 不做的事（有意留给 CI）：
# - 不 push：推送由人决定，避免脚本误把未审阅的提交推上去
# - 不创建 GitHub Release：tag 推送后由 .github/workflows/release.yml 处理

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$arg（用 --help 看用法）" >&2; exit 1 ;;
  esac
done

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m警告:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 前置检查
# ---------------------------------------------------------------------------
[ -f backend/app/version.py ] || die "找不到 backend/app/version.py（版本单一真源）"

if [ -n "$(git status --porcelain)" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    warn "工作区有未提交改动；--dry-run 只做预演，不会改动任何文件"
  else
    die "工作区有未提交改动，先提交或 stash 再发版"
  fi
fi

CURRENT=$(grep -m1 '^__version__' backend/app/version.py | sed -E 's/.*"([^"]+)".*/\1/')
[ -n "$CURRENT" ] || die "无法从 version.py 读取当前版本"

LAST_TAG=$(git tag --sort=-v:refname | head -1)
if [ -z "$LAST_TAG" ]; then
  warn "没有历史 tag，将把整个历史计入本次变更"
  RANGE=""
else
  RANGE="${LAST_TAG}..HEAD"
fi

COMMITS=$(git log $RANGE --format='%s' 2>/dev/null || git log --format='%s')
[ -n "$COMMITS" ] || die "自 $LAST_TAG 以来没有新提交，无需发版"

# ---------------------------------------------------------------------------
# 版本推导（SemVer + conventional commits）
# ---------------------------------------------------------------------------
# 规则：BREAKING CHANGE / type! → major；feat → minor；其余 → patch
if echo "$COMMITS" | grep -qE '^[a-z]+(\([^)]*\))?!:|BREAKING CHANGE'; then
  BUMP="major"
elif echo "$COMMITS" | grep -qE '^feat(\([^)]*\))?:'; then
  BUMP="minor"
else
  BUMP="patch"
fi

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
case "$BUMP" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
esac
NEXT="${MAJOR}.${MINOR}.${PATCH}"

say "当前版本 $CURRENT → 下一版本 $NEXT（$BUMP 变更）"
echo
echo "  自 ${LAST_TAG:-起点} 以来的提交："
echo "$COMMITS" | sed 's/^/    /'
echo

# ---------------------------------------------------------------------------
# CHANGELOG 条目（按类型分组）
# ---------------------------------------------------------------------------
section() {
  local pattern="$1" title="$2"
  local lines
  lines=$(echo "$COMMITS" | grep -E "$pattern" | sed 's/^/- /' || true)
  if [ -n "$lines" ]; then
    printf '\n### %s\n\n%s\n' "$title" "$lines"
  fi
}

ENTRY="## [${NEXT}] - $(date +%F)

$(section '^feat(\([^)]*\))?:' '新功能')
$(section '^fix(\([^)]*\))?:' '修复')
$(section '^refactor(\([^)]*\))?:' '重构')
$(section '^perf(\([^)]*\))?:' '性能')
$(section '^docs(\([^)]*\))?:' '文档')
$(section '^(test|chore|ci)(\([^)]*\))?:' '其他')
"

if [ "$DRY_RUN" = "1" ]; then
  say "预演模式：以下内容会写入 CHANGELOG.md"
  echo "----------------------------------------"
  echo "$ENTRY"
  echo "----------------------------------------"
  say "预演结束，未修改任何文件"
  exit 0
fi

# ---------------------------------------------------------------------------
# 执行：改版本号 + 写 CHANGELOG + 提交 + 打 tag
# ---------------------------------------------------------------------------
say "更新版本号（单一真源 + 派生文件）"
python3 - "$CURRENT" "$NEXT" <<'PY'
import pathlib
import re
import sys

cur, nxt = sys.argv[1], sys.argv[2]
root = pathlib.Path(".")

# 1) 单一真源
p = root / "backend/app/version.py"
s = p.read_text(encoding="utf-8")
s = re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{nxt}"', s, count=1, flags=re.M)
s = re.sub(r'^PREVIOUS_VERSION = "[^"]+"', f'PREVIOUS_VERSION = "{cur}"', s, count=1, flags=re.M)
p.write_text(s, encoding="utf-8")

# 2) pyproject（打包元数据需要静态版本）
p = root / "pyproject.toml"
s = p.read_text(encoding="utf-8")
s = re.sub(r'^version = "[^"]+"', f'version = "{nxt}"', s, count=1, flags=re.M)
p.write_text(s, encoding="utf-8")

# 3) 前端 package.json（仅 version 字段，避免误改依赖版本）
p = root / "frontend/package.json"
s = p.read_text(encoding="utf-8")
s = re.sub(r'"version": "[^"]+"', f'"version": "{nxt}"', s, count=1)
p.write_text(s, encoding="utf-8")

print(f"version.py / pyproject.toml / package.json → {nxt}")
PY

say "写入 CHANGELOG"
python3 - "$ENTRY" <<'PY'
import pathlib
import sys

entry = sys.argv[1]
p = pathlib.Path("CHANGELOG.md")
s = p.read_text(encoding="utf-8")
# 插在文件头部说明之后（第一个 "## [" 之前）
marker = s.find("## [")
if marker < 0:
    s = s.rstrip() + "\n\n" + entry
else:
    s = s[:marker] + entry + "\n" + s[marker:]
p.write_text(s, encoding="utf-8")
print("CHANGELOG.md 已更新")
PY

say "提交并发 tag"
git add backend/app/version.py pyproject.toml frontend/package.json CHANGELOG.md
git commit -q -m "chore(release): v${NEXT}"
git tag -a "v${NEXT}" -m "v${NEXT}"

echo
say "完成：v${NEXT} 已提交并打 tag"
echo
echo "  推送（确认无误后手动执行）："
echo "    git push origin main --follow-tags"
echo
echo "  tag 推送后 .github/workflows/release.yml 会自动创建 GitHub Release。"
