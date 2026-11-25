# Moneyhelper 4.27.2 桌面安装包

本目录是当前版本（4.27.2）的本地成品目录，安装包已放在代码仓库里，下载后可直接安装。

| 文件 | 平台 | 用途 |
|---|---|---|
| `Moneyhelper_4.27.2_amd64.deb` | Linux x64 / Ubuntu 22.04+ | Debian/Ubuntu 安装包 |
| `Moneyhelper_4.27.2_amd64.AppImage` | Linux x64 | 免安装，支持应用内自更新 |
| `Moneyhelper_4.27.2_x64-setup.exe` | Windows x64 | NSIS 安装包 |
| `Moneyhelper.app.tar.gz` | macOS arm64 | 应用包 / updater 产物 |
| `latest.json` | 全平台 | Tauri updater 清单 |
| `SHA256SUMS.txt` | - | 完整性校验 |

Linux 首次安装建议：

```bash
sudo apt update
sudo apt install ./Moneyhelper_4.27.2_amd64.deb
```

只执行 `dpkg -i` 时，缺少 `libwebkit2gtk-4.1-0` 会留下未配置状态；apt 会自动补齐依赖。

校验：

```bash
sha256sum -c SHA256SUMS.txt
```

## 应用内升级实测

- 起点：`4.27.1` AppImage，SHA256 `d642caf6717feb250760a8880403285a26b52725b01118f1c7d224aa06db5e56`。
- 在设置页检查到 `4.27.2`，点击「Install now」，下载并安装成功。
- 升级后原文件 SHA256 变为 `0aa3ad0b87f927282b24485c661cca0e627494bb15be0dd9c3eafbecb951dada`，与 Release 的 `4.27.2` AppImage 完全一致。
- 应用自动重启，设置页显示 `Version 4.27.2`，更新卡片为 `Up to date`，sidecar 正常拉起。

> 安装包单文件均超过 GitHub 100MB 限制，因此 `.gitignore` 排除了这些二进制；源码、`README.md`、`latest.json` 与校验文件仍随仓库提交。完整资产同时保留在 GitHub Release。
