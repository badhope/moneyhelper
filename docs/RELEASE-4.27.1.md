# Moneyhelper 4.27.1 发布记录（应用内升级）

## 这版做了什么

4.27.0 只有 updater 清单，没有可点的升级入口。4.27.1 把最后一段接上：

1. 设置 → 偏好底部出现「版本更新」卡片，显示当前版本与「检查更新」按钮。
2. 发现新版本后展示目标版本号和发布说明，「立即升级」会下载安装包、校验 minisign 签名、替换当前版本并自动重启。
3. 更新检查与安装放在 Rust 侧（`check_update` / `install_update`），前端只拿版本与说明，不接触下载地址和签名。
4. 主窗口加载本地 sidecar 页面，capability 只放行 `http://127.0.0.1:*` 的基础 IPC，公网页面没有入口。

## 升级边界

- Linux **AppImage** 可以应用内自替换，无需 root。
- Linux `.deb` 的更新由 `dpkg -i` 执行，普通用户权限不足时应改用 `sudo apt install` 或下载新包覆盖安装。
- Windows NSIS 会由 updater 拉起安装器并退出当前进程；macOS 更新后由 updater 重启应用。
- Windows 仍未做 Authenticode、macOS 仍未做公证，首次安装可能出现系统安全提示。

## 验收口径

- 4.27.1 三平台构建成功，`latest.json` 三平台齐全且签名非空。
- Linux AppImage 从 4.27.1 升到后续版本：检查更新能识别新版本，安装后版本号变化，sidecar 正常拉起。
- `.deb` 安装/启动/PDF 提取/退出回收不回退。

## 代码目录里的安装包

`releases/4.27.1/` 会保留本版 `.deb`、AppImage、Windows NSIS、macOS 包、`latest.json` 与 `SHA256SUMS.txt`；二进制不提交 Git，源码与说明随仓库走。
