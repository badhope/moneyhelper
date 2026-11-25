# Moneyhelper Desktop (Tauri 2)

## 状态

4.27.0 起，桌面壳不再是“脚手架”：本地 Linux 会真实产出 `.deb` 与 `.AppImage`，
Windows/macOS 由 `.github/workflows/desktop.yml` 在对应 runner 上产出 NSIS/MSI 与 DMG。
产物都带签名后的 updater 元数据，升级链路不再留空公钥。

## 结构

```
desktop/
├── package.json              # @tauri-apps/cli
└── src-tauri/
    ├── Cargo.toml            # tauri 2 + shell + updater
    ├── build.rs
    ├── tauri.conf.json       # 窗口、bundle、externalBin、updater
    ├── binaries/             # 构建时放入 sidecar（二进制不入库）
    └── src/main.rs           # 拉起 sidecar、等 /api/health、再开窗口
```

## 启动链路

1. 选一个空闲端口（不再硬编码 8788，避免和本地开发服务抢端口）。
2. 通过 Tauri sidecar 启动 `moneyhelper-server`，注入 `PORT` 与 `MONEYHELPER_NO_BROWSER=1`。
3. 轮询 `GET /api/health`，只有返回 200 才创建窗口，避免初始化期间白屏。
4. 窗口直接加载 `http://127.0.0.1:<port>/`，前端与 API 同源，不存在跨域。
5. 应用退出时先按进程树杀掉 sidecar（PyInstaller onefile 是 bootloader + 子进程两段），不留后台占端口。
6. PyInstaller 单文件冷启动要解压约 200 MB，实测首次 20–35 秒；窗口在健康检查通过后才出现，不会白屏。

## 本地构建

```bash
bash scripts/build-desktop.sh            # 当前平台，deb + appimage
bash scripts/build-desktop.sh deb        # 只打 deb
```

脚本会先 PyInstaller 打 sidecar，复制成
`desktop/src-tauri/binaries/moneyhelper-server-<target-triple>`，再调用 `tauri build`。
Rust、`libwebkit2gtk-4.1-dev`、`patchelf` 等依赖需预装。

Linux 最终用户装 `.deb` 时需要运行时 `libwebkit2gtk-4.1-0`；Ubuntu 22.04 先 `sudo apt update`，再 `sudo apt install ./Moneyhelper_4.27.0_amd64.deb`，让 apt 自动补齐依赖。只用 `dpkg -i` 会在缺依赖时留下未配置状态。

## 签名与自动更新

- 公钥已写入 `src-tauri/tauri.conf.json` 的 `plugins.updater.pubkey`。
- 私钥只在构建机 `~/.tauri/moneyhelper.key`，CI 用仓库 secret
  `TAURI_SIGNING_PRIVATE_KEY` / `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。
- 更新端点优先 GitHub Release 的 `latest.json`，GitCode 作为第二来源。
- 私钥丢失后旧版本无法验证新包，必须换公钥并让用户重装。

## 跨平台边界

PyInstaller 与 Tauri 都不能可靠交叉编译安装包：Windows 需 MSVC/WiX/NSIS，
macOS 需 Xcode，Linux 需 webkit2gtk。三平台产物必须在对应系统构建，
因此由 `desktop.yml` 的 matrix 负责；本地 Linux 只验证 Linux 链路。
