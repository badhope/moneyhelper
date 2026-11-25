#!/usr/bin/env bash
# 构建当前平台可安装的桌面产物：PyInstaller sidecar + Tauri 安装包。
#
# 用法：bash scripts/build-desktop.sh [deb|appimage|all]
# 输出：desktop/src-tauri/target/release/bundle/
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TARGET="${1:-all}"
case "$TARGET" in deb|appimage|all) ;; *) echo "用法：$0 [deb|appimage|all]" >&2; exit 2 ;; esac

PATH="$HOME/.cargo/bin:$PATH"
command -v cargo >/dev/null || { echo "缺 Rust/cargo，先装 rustup" >&2; exit 1; }
command -v python3 >/dev/null || { echo "缺 python3" >&2; exit 1; }

VERSION=$(python3 - <<'PY'
import re
from pathlib import Path
s=Path('backend/app/version.py').read_text(encoding='utf-8')
m=re.search(r'^__version__ = "([^"]+)"', s, re.M)
print(m.group(1) if m else '')
PY
)
[ -n "$VERSION" ] || { echo "读不到版本号" >&2; exit 1; }
TRIPLE=$(rustc -vV | sed -n 's/^host: //p')
echo "==> Moneyhelper $VERSION / $TRIPLE"

echo "==> 构建后端 sidecar（PyInstaller 单文件）"
( cd backend && python3 -m PyInstaller moneyhelper.spec --noconfirm --clean )
mkdir -p desktop/src-tauri/binaries
cp backend/dist/moneyhelper "desktop/src-tauri/binaries/moneyhelper-server-$TRIPLE"
chmod +x "desktop/src-tauri/binaries/moneyhelper-server-$TRIPLE"
ls -lh "desktop/src-tauri/binaries/moneyhelper-server-$TRIPLE"

echo "==> 构建 Tauri 安装包"
BUNDLES="deb,appimage"
[ "$TARGET" = deb ] && BUNDLES="deb"
[ "$TARGET" = appimage ] && BUNDLES="appimage"
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ] && [ -f "$HOME/.tauri/moneyhelper.key" ]; then
  export TAURI_SIGNING_PRIVATE_KEY="$HOME/.tauri/moneyhelper.key"
  export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}"
fi
( cd desktop && npm install --no-audit --no-fund >/dev/null && npx tauri build --bundles "$BUNDLES" )

echo "==> 完成"
find desktop/src-tauri/target/release/bundle -maxdepth 3 -type f \( -name '*.deb' -o -name '*.AppImage' -o -name '*.sig' \) -printf '%p %k KB\n' 2>/dev/null
