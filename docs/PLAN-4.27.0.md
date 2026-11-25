# 4.27.0 桌面交付计划

## 目标

把 `desktop/src-tauri` 从“脚手架就绪”变成可安装、可启动、可升级的桌面产物；不新增业务功能，不改账务口径。

## 必须真实实现

1. **sidecar 打包**
   - PyInstaller 产出 `moneyhelper` 单文件；
   - 按 `rustc` target triple 复制为 `desktop/src-tauri/binaries/moneyhelper-server-<triple>`；
   - Tauri `bundle.externalBin` 引用它，安装包内必须能找到。

2. **启动链路**
   - 选空闲端口，不硬编码 8788；
   - 注入 `MONEYHELPER_NO_BROWSER=1` 与 `PORT`；
   - 消费 sidecar stdout/stderr，避免管道堵死；
   - 轮询 `GET /api/health`，200 后再建窗口；
   - 窗口加载 sidecar 根路径，前端与 API 同源；
   - 退出时杀 sidecar。

3. **安装包**
   - Linux：`.deb` + `.AppImage`；安装后能从菜单/命令行启动，卸载后无残留；
   - Windows：NSIS + MSI；
   - macOS：DMG；
   - 三平台由 matrix runner 各自构建，不做不可靠交叉编译。

4. **签名与更新**
   - 生成 minisign 密钥对；
   - `tauri.conf.json` 写公钥，私钥只在本机 `~/.tauri` 与 CI secret；
   - 构建产生的 `.sig` 必须随 Release 上传；
   - 更新端点优先 GitHub，GitCode 兜底。

## 验收

- sidecar 独立启动：`/api/health` 200，版本 4.27.0；
- 桌面程序启动后窗口可见，页面无跨域错误，账本页可用；
- `.deb` `dpkg -i` 安装成功，进程与 sidecar 同生共死；
- `.AppImage` 可执行；
- 安装包内包含 sidecar，不依赖开发机 Python；
- 五远端同一 SHA；
- 文档与截图落库。

## 明确不做

P2 外部资质项不靠假接口“完成”：
- 税局直连申报/缴款需要乐企或服务商准入；
- 银行/券商资金划转需要持牌通道与用户授权；
- 集团法定合并需要审计口径与范围确认；
- 五个内容社区代发需要平台账号与发布授权。

这些只能在资质/授权到位后接真实通道；本轮只交付桌面与可验证的本地能力。
