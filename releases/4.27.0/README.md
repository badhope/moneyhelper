# Moneyhelper 4.27.0 桌面安装包

本目录是本地成品目录，安装包已放在代码仓库里，方便直接取用。

| 文件 | 平台 | 用途 |
|---|---|---|
| `Moneyhelper_4.27.0_amd64.deb` | Linux x64 / Ubuntu 22.04+ | Debian/Ubuntu 安装包 |
| `Moneyhelper_4.27.0_amd64.AppImage` | Linux x64 | 免安装、可自更新 |
| `Moneyhelper_4.27.0_x64-setup.exe` | Windows x64 | NSIS 安装包 |
| `Moneyhelper.app.tar.gz` | macOS arm64 | 应用包 / updater 产物 |
| `latest.json` | 全平台 | Tauri updater 清单 |
| `SHA256SUMS.txt` | - | 完整性校验 |

Linux 首次安装建议：

```bash
sudo apt update
sudo apt install ./Moneyhelper_4.27.0_amd64.deb
```

只执行 `dpkg -i` 时，缺少 `libwebkit2gtk-4.1-0` 会留下未配置状态；apt 会自动补齐依赖。

校验：

```bash
sha256sum -c SHA256SUMS.txt
```

> 安装包单文件均超过 GitHub 100MB 限制，因此 `.gitignore` 排除了这些二进制；源码、`README.md`、`latest.json` 与校验文件仍随仓库提交。完整资产同时保留在 GitHub Release。
