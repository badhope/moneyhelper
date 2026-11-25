#!/usr/bin/env python3
"""把三平台桌面包与签名汇总成 Tauri updater 的 latest.json。

Tauri 自己只产出 `<installer>.sig`，不会跨 job 汇总清单；没有 latest.json，
应用里的「检查更新」永远拿不到新版本。这个脚本只读本地文件，不联网，
便于在 CI 的 manifest job 和本地打包后复用。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

# Tauri updater 的平台键是固定的；每个键对应一种安装包。
PLATFORM_SUFFIX = {
    "linux-x86_64": (".AppImage", ".deb"),
    "windows-x86_64": ("-setup.exe", ".msi"),
    "darwin-aarch64": (".dmg",),
}


def pick(files: list[Path], suffixes: tuple[str, ...]) -> Path | None:
    for suffix in suffixes:
        for file in files:
            if file.name.lower().endswith(suffix.lower()):
                return file
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True, help="安装包目录，可重复")
    parser.add_argument("--base-url", required=True, help="Release 下载前缀，不含文件名")
    parser.add_argument("--version", required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--allow-missing", action="store_true", help="本地只打一个平台时用")
    args = parser.parse_args()

    files = [p for root in args.root for p in Path(root).rglob("*") if p.is_file()]
    platforms: dict[str, dict[str, str]] = {}
    for key, suffixes in PLATFORM_SUFFIX.items():
        target = pick(files, suffixes)
        if target is None:
            continue
        sig = target.with_name(target.name + ".sig")
        if not sig.is_file():
            # 没有签名的包不能进 updater；否则客户端会拒绝安装。
            continue
        platforms[key] = {
            "signature": sig.read_text(encoding="utf-8").strip(),
            "url": f"{args.base_url.rstrip('/')}/{target.name}",
        }

    if not platforms:
        raise SystemExit("没有找到「安装包 + .sig」组合，无法生成 latest.json")
    missing = sorted(set(PLATFORM_SUFFIX) - set(platforms))
    if missing and not args.allow_missing:
        raise SystemExit(f"缺少平台：{', '.join(missing)}（本地验收可用 --allow-missing）")

    payload = {
        "version": args.version,
        "notes": args.notes,
        "pub_date": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platforms": platforms,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
