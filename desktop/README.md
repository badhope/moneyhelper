# Moneyhelper Desktop (Tauri 2)

## 状态

脚手架已就绪，**未在本仓库 CI 中构建**：桌面产物需要目标平台的系统依赖
（Windows MSI/WiX、macOS Xcode、Linux webkit2gtk），不适合在通用 CI 里默认跑。

## 结构

```
desktop/
├── package.json            # @tauri-apps/cli
└── src-tauri/
    ├── Cargo.toml          # tauri 2 + shell + updater
    ├── build.rs
    ├── tauri.conf.json     # 窗口、bundle 目标、updater 端点
    └── src/main.rs         # 启动 sidecar（moneyhelper-server）并在退出时回收
```

## 本地构建

```bash
# 1. 先产出 sidecar（PyInstaller 单文件）
python scripts/build_server.py          # 输出 dist/moneyhelper-server(.exe)

# 2. 构建桌面包
cd desktop && npm install
cp ../dist/moneyhelper-server* src-tauri/   # 放到 sidecar 同目录
npm run build                            # 产物在 src-tauri/target/release/bundle/
```

## 首跑行为

- 启动时拉起 `moneyhelper-server serve --host 127.0.0.1 --port 8788`；
- 窗口加载内嵌前端（`frontend/dist`）；
- 关闭窗口时结束 sidecar，避免后台残留；
- 自动更新端点指向 GitCode Releases；`pubkey` 需在首次发布时用 `tauri signer generate` 生成并填入。

## 已知阻塞

| 项 | 原因 |
|---|---|
| 未在本机产出安装包 | 需要 WiX/NSIS 与完整 Tauri 工具链，本机当前内存不足以稳定跑完整 Rust 构建 |
| updater 公钥为空 | 需发布方生成密钥对后填入 `tauri.conf.json` 的 `plugins.updater.pubkey` |
| 三平台产物 | 需在对应平台 runner 上分别构建（macOS 必须 macOS，Linux 需 webkit2gtk） |
