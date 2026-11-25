# Sidecar 放置目录

`scripts/build-desktop.sh` 会把 PyInstaller 产物复制成
`moneyhelper-server-<target-triple>`（例如 `moneyhelper-server-x86_64-unknown-linux-gnu`），
Tauri 的 `externalBin` 会按目标三元组查找它。二进制不入库。
