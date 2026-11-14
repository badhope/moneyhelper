#!/usr/bin/env bash
# 一键构建 Windows 单文件 EXE + NSIS 安装包（全部使用项目内工具链）。
#
# 为什么要有这个脚本：
# 之前发行产物只有 PyInstaller 单文件，没有安装器、没有开始菜单快捷方式，
# 用户拿到 exe 只能自己建目录。这里补上「能双击安装」的完整链路。
#
# 依赖（都装在项目内，不动系统）：
#   - PyInstaller：backend/requirements-dev.txt
#   - NSIS 便携版：下载解压到 .tools/nsis/
#
# 用法：
#   bash scripts/build-installer.sh              # 构建
#   bash scripts/build-installer.sh --skip-exe   # 只重打安装包（EXE 已存在）
#
# 产物：
#   backend/dist/moneyhelper.exe                       单文件（免安装）
#   backend/dist/Moneyhelper-Setup-<version>.exe       安装包
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SKIP_EXE=0
for arg in "$@"; do
  case "$arg" in
    --skip-exe) SKIP_EXE=1 ;;
    -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数：$arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2; exit 1; }

# --- 解释器 ---
PY=""
for cand in ".venv/Scripts/python.exe" ".venv/bin/python" "backend/.venv/Scripts/python.exe"; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done
[ -n "$PY" ] || die "找不到项目 venv（先跑 scripts/dev.sh）"

# 只匹配行首的赋值，避免撞上注释里的示例 `__version__ = "x.y.z"`
VERSION=$("$PY" - <<'PYEOF'
import pathlib, re
text = pathlib.Path("backend/app/version.py").read_text(encoding="utf-8")
m = re.search(r'^__version__ = "([^"]+)"', text, re.M)
print(m.group(1) if m else "")
PYEOF
)
[ -n "$VERSION" ] || die "无法从 backend/app/version.py 读取版本号"
say "版本 $VERSION"

# --- 前端产物（EXE 内嵌静态资源）---
if [ "$SKIP_EXE" -eq 0 ]; then
  say "构建前端"
  ( cd frontend && npm run build ) || die "前端构建失败"

  say "PyInstaller 打包单文件"
  "$PY" -c "import PyInstaller" 2>/dev/null || die "缺 PyInstaller：$PY -m pip install -r backend/requirements-dev.txt"
  ( cd backend && "../$PY" -m PyInstaller moneyhelper.spec --noconfirm --distpath dist --workpath build ) \
    || die "PyInstaller 失败"
fi

[ -f backend/dist/moneyhelper.exe ] || die "找不到 backend/dist/moneyhelper.exe"

# --- NSIS ---
MAKENSIS=""
for cand in ".tools/nsis/nsis-3.11/makensis.exe" ".tools/nsis/makensis.exe"; do
  if [ -x "$cand" ]; then MAKENSIS="$cand"; break; fi
done
if [ -z "$MAKENSIS" ]; then
  say "下载 NSIS 便携版（约 2.3 MB）"
  mkdir -p .tools/nsis
  curl -sSL --fail --max-time 300 -o .tools/nsis/nsis.zip \
    "https://downloads.sourceforge.net/project/nsis/NSIS%203/3.11/nsis-3.11.zip" \
    || die "NSIS 下载失败（离线环境请手动放到 .tools/nsis/nsis-3.11/）"
  ( cd .tools/nsis && unzip -q -o nsis.zip )
  MAKENSIS=".tools/nsis/nsis-3.11/makensis.exe"
fi
[ -x "$MAKENSIS" ] || die "找不到 makensis"

say "构建安装包"
"$MAKENSIS" -DVERSION="$VERSION" -DSRCEXE="..\\backend\\dist\\moneyhelper.exe" installer/moneyhelper.nsi \
  || die "NSIS 编译失败"

OUT="backend/dist/Moneyhelper-Setup-${VERSION}.exe"
[ -f "$OUT" ] || die "未生成 $OUT"

say "完成"
ls -lh backend/dist/moneyhelper.exe "$OUT"
echo
echo "  免安装：backend/dist/moneyhelper.exe"
echo "  安装包：$OUT"
echo "  安装包为每用户安装（无需管理员），数据在 %LOCALAPPDATA%\\Moneyhelper"
