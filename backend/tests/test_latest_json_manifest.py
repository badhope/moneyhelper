"""latest.json 生成器的行为测试。

Tauri 只产 `.sig`，清单必须由我们自己汇总；没有签名或清单的平台键写错，
客户端会静默拒绝更新，所以这里把可执行脚本当黑盒跑一遍。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "make-latest-json.py"


def test_manifest_requires_signature_and_maps_platforms(tmp_path: Path) -> None:
    for name, sig in [
        ("Moneyhelper_4.27.0_amd64.AppImage", "linux-signature"),
        ("Moneyhelper_4.27.0_amd64.AppImage.sig", "linux-signature"),
        ("Moneyhelper_4.27.0_x64-setup.exe", "win-signature"),
        ("Moneyhelper_4.27.0_x64-setup.exe.sig", "win-signature"),
        ("Moneyhelper_4.27.0_aarch64.dmg", "mac-signature"),
        ("Moneyhelper_4.27.0_aarch64.dmg.sig", "mac-signature"),
    ]:
        (tmp_path / name).write_text(sig, encoding="utf-8")
    # 没签名的包不能进清单
    (tmp_path / "Moneyhelper_4.27.0_amd64.deb").write_text("deb", encoding="utf-8")

    out = tmp_path / "latest.json"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "--base-url",
            "https://example.com/releases/download/v4.27.0",
            "--version",
            "4.27.0",
            "--out",
            str(out),
        ],
        check=True,
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["version"] == "4.27.0"
    assert payload["platforms"]["linux-x86_64"]["signature"] == "linux-signature"
    assert payload["platforms"]["windows-x86_64"]["url"].endswith("-setup.exe")
    assert payload["platforms"]["darwin-aarch64"]["url"].endswith(".dmg")
    assert not any(item["url"].endswith(".deb") for item in payload["platforms"].values())
