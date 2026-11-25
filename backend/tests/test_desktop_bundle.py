"""桌面交付的防漂移测试。

这些断言不替代真实打包，但能挡住历史上出现过的三类问题：
版本号三处不一致、externalBin 没配、workflow 只剩 PyInstaller 单文件。
真实产物由 scripts/build-desktop.sh 与 desktop.yml 验证。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"
TAURI = DESKTOP / "src-tauri" / "tauri.conf.json"


def _version() -> str:
    text = (ROOT / "backend" / "app" / "version.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def test_desktop_versions_follow_single_source() -> None:
    assert json.loads(TAURI.read_text(encoding="utf-8"))["version"] == _version()
    assert json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))["version"] == _version()
    assert json.loads((DESKTOP / "package-lock.json").read_text(encoding="utf-8"))["version"] == _version()
    cargo = (DESKTOP / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "([^"]+)"', cargo, re.M).group(1) == _version()


def test_tauri_bundles_sidecar_and_has_updater_key() -> None:
    conf = json.loads(TAURI.read_text(encoding="utf-8"))
    assert conf["bundle"]["externalBin"] == ["binaries/moneyhelper-server"]
    assert conf["app"]["windows"] == []  # 窗口必须等 sidecar 就绪后动态创建
    updater = conf["plugins"]["updater"]
    assert updater["pubkey"].strip()
    assert "PRIVATE KEY" not in updater["pubkey"]


def test_workflow_builds_tauri_on_three_platforms() -> None:
    workflow = (ROOT / ".github" / "workflows" / "desktop.yml").read_text(encoding="utf-8")
    for marker in ("windows-latest", "macos-latest", "ubuntu-latest"):
        assert marker in workflow
    assert "npx tauri build" in workflow
    assert "moneyhelper-server-${TRIPLE}" in workflow
    assert "make-latest-json.py" in workflow
    assert "latest.json" in workflow
