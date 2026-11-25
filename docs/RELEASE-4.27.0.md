# Moneyhelper 4.27.0 发布说明（桌面交付）

- 发布日期：2026-11-25
- 版本：4.27.0（上一版 4.26.0）
- 主题：Tauri 桌面包真正可安装、可启动、可升级，不再停留在脚手架

## 一、结论

Linux 桌面链路已在本机真实跑通：PyInstaller sidecar → Tauri `.deb` / `.AppImage` → 安装/启动/同源 API/退出回收/卸载，全部有实测记录。Windows NSIS/MSI 与 macOS DMG 由三平台 GitHub Actions 矩阵构建，配置与签名已落地，但本机是 Linux，不能声称已在 Windows/macOS 上跑过。

**已完成：**
- sidecar 单文件产物能独立启动，`/api/health` 返回 200，版本为 4.27.0。
- `.deb` 可 `dpkg -i` 安装，启动后 11 秒内出现窗口，页面与 API 同源，关闭窗口后进程树全部退出。
- `.AppImage` 在无 FUSE 环境用 `--appimage-extract-and-run` 启动，14 秒内出窗口，关闭后无残留。
- `.deb` / `.AppImage` 均生成 minisign `.sig`，`latest.json` 汇总脚本可用。
- 后端 1993 项测试全部通过；前端 36 个文件 247 项测试全部通过；`tsc --noEmit` 通过。

**不在本版范围：**
- Windows/macOS 安装包的实机验收（需对应 runner，已交给 workflow）。
- P2 税局直连、持牌资金划转、法定合并、社区代发布：仍受外部资质/授权约束，不用假接口冒充。

## 二、产物

| 产物 | 大小 | SHA-256 |
| --- | --- | --- |
| `Moneyhelper_4.27.0_amd64.deb` | 209.3 MiB | `65bfbc87443fbd340ba8521a8fac9e08a84b3f54d5696b57ac214a69727ed9c3` |
| `Moneyhelper_4.27.0_amd64.AppImage` | 283.6 MiB | `d17388415dcbdfa74f37c953c44e330552243eb8b512f47e7156b0e72354bee6` |
| `backend/dist/moneyhelper`（Linux sidecar） | 206 MiB | `71f8896cd9a2981c56e69909cc12a9a53464a7e3b26436ab0f096488bd4a8d37` |

签名文件：`*.deb.sig`、`*.AppImage.sig`，均由 `~/.tauri/moneyhelper.key` 生成，公钥已写入 `tauri.conf.json`。

## 三、实测记录

### 1. sidecar 独立启动

```bash
MONEYHELPER_NO_BROWSER=1 PORT=8899 MONEYHELPER_DATA_DIR=/tmp/mh-sidecar-4270 ./backend/dist/moneyhelper
```

- 首次冷启动 33 秒后 `/api/health` 返回 200。
- 返回体：`{"ok":true,"llm_configured":false,"model":"","auth_mode":"local"}`。
- 启动横幅版本：`Moneyhelper v4.27.0`。

### 2. `.deb` 安装与桌面启动

```bash
sudo dpkg -i Moneyhelper_4.27.0_amd64.deb
MONEYHELPER_DATA_DIR=/tmp/mh-desktop-4270b /usr/bin/moneyhelper-desktop
```

- `dpkg` 安装成功，包版本 4.27.0；安装清单包含 `/usr/bin/moneyhelper-desktop`、`/usr/bin/moneyhelper-server`、桌面文件与多尺寸图标。
- 窗口 1280×860，11 秒内出现（文件已缓存时的热启动）。
- sidecar 环境变量实测：`MONEYHELPER_NO_BROWSER=1`、`PORT=46793`，只监听 `127.0.0.1`。
- `curl http://127.0.0.1:46793/api/health` 返回 200；首页标题正常加载。
- 关闭窗口后 `moneyhelper-desktop` 与两段 `moneyhelper-server` 全部退出，无孤儿进程。
- `sudo dpkg -r moneyhelper` 后两个可执行文件均被删除。

### 3. `.AppImage` 启动

```bash
MONEYHELPER_DATA_DIR=/tmp/mh-appimage-4270 \
  ./Moneyhelper_4.27.0_amd64.AppImage --appimage-extract-and-run
```

- 14 秒内出现窗口，sidecar 健康检查 200，页面资源正常加载。
- 关闭窗口后无 `Moneyhelper` / `moneyhelper-server` 进程残留。

### 4. 自动化回归

| 项 | 结果 |
| --- | --- |
| 后端 pytest | 1993 passed，344.77s |
| 前端 vitest | 36 files / 247 tests passed |
| 前端类型检查 | `tsc --noEmit` 通过 |
| 桌面防漂移测试 | 版本三处一致、externalBin、空 windows、三平台 workflow、latest.json 汇总 |
| workflow YAML | `yaml.safe_load` 通过 |

## 四、构建中修掉的真问题

1. **Tauri 编译失败**：`WebviewWindowBuilder` 闭包移动了 `AppHandle`，改为先 `clone()` 再传入。
2. **sidecar 不在安装包**：补 `bundle.externalBin`，构建脚本按 `rustc -vV` 的 host triple 复制 `moneyhelper-server-<triple>`。
3. **窗口先于后端出现**：改为轮询 `/api/health` 返回 200 后再建窗，超时放宽到 90 秒。
4. **跨域失败**：窗口加载 `http://127.0.0.1:<port>/`，前端与 API 同源，不再用 `tauri://localhost`。
5. **PyInstaller 缺 LiteLLM 数据**：从只带价格表改为按扩展名收齐 LiteLLM 数据，补上 `containers/endpoints.json` 与 anthropic tokenizer。
6. **缺第三方包数据**：补 `rfc3987_syntax/*.lark`、`jsonschema_specifications` schema、`openapi_spec_validator`、`certifi` CA、`tzdata`。
7. **关闭窗口残留 sidecar**：PyInstaller onefile 是「bootloader + 真实子进程」两段，退出时按进程树 `TERM` → `KILL`，不再只杀 bootloader。
8. **updater 清单缺失**：新增 `scripts/make-latest-json.py` 与 workflow `manifest` job，三平台构建成功后汇总 `latest.json`。

## 五、桌面启动链路

1. `TcpListener` 绑定 `127.0.0.1:0` 取空闲端口。
2. Tauri shell sidecar 启动 `moneyhelper-server`，注入 `MONEYHELPER_NO_BROWSER=1` 与 `PORT`。
3. 持续消费 stdout/stderr，避免管道堵死；PyInstaller 启动错误可见。
4. `GET /api/health` 返回 200 后，在主线程动态创建 1280×860 窗口。
5. 窗口加载同源地址；退出时按进程树回收 sidecar。

## 六、三平台 workflow

`.github/workflows/desktop.yml` 在 `v*` tag 或手动触发时：

- Windows：`nsis,msi`，另保留原 NSIS 单文件安装包与静默装卸冒烟。
- macOS：`dmg`，按 arm64 假定。
- Linux：`deb,appimage`。
- 统一先打 PyInstaller sidecar，再 `npx tauri build --bundles`。
- 三平台成功后 `manifest` job 汇总 `latest.json` 并附加到 Release。

需要仓库 secret：`TAURI_SIGNING_PRIVATE_KEY`、`TAURI_SIGNING_PRIVATE_KEY_PASSWORD`（当前私钥密码为空）。

## 七、已知边界

- Windows/macOS 未在本机实跑；`macos-latest` 若为 x64，需把 manifest 平台键改为 `darwin-x86_64` 并调整 sidecar triple。
- PyInstaller 单文件冷启动需解压约 200 MB，机械盘/低配机器可能超过 35 秒，已把窗口等待放宽到 90 秒，但用户仍会感知启动慢。
- `.deb` 未做代码签名（Linux 桌面生态通常不要求）；Windows 未做 Authenticode，SmartScreen 可能提示未知发布者。
- P2 外部资质项仍未实现：税局直连需乐企/服务商，银行划款需持牌授权，法定合并需审计口径，社区代发布需平台授权。

## 八、截图

- `docs/screenshots/222-desktop-4270-onboarding.png`：首次启动三步引导。
- `docs/screenshots/223-desktop-4270-deb.png`：`.deb` 安装版主界面。
- `docs/screenshots/224-desktop-4270-appimage.png`：`.AppImage` 主界面。
