## 跨平台说明（Windows / Linux / macOS）

- **启动脚本自动适配**：`scripts/dev.sh`、`scripts/lint.sh`、`scripts/e2e-backend.sh`、`deploy/one-click.sh` 会探测 `backend/.venv/Scripts/python.exe`（Windows）或 `backend/.venv/bin/python`（Unix），并按 `python3 → python → py` 回退。
- **Windows 双击启动**：`start.bat` 自动创建 venv、安装依赖、开两个控制台窗口；`start.bat --prod` 构建前端后单端口运行。
- **换行符**：`.gitattributes` 固定 `.bat/.cmd/.ps1` 为 CRLF、`.sh` 为 LF。用 Windows 编辑器改脚本时不要顺手改成 CRLF，否则 Linux 侧会报 `bad interpreter`。
- **文件名大小写**：仓库内不再存在仅大小写不同的同名文件（`ARCHITECTURE-detail.md` / `architecture.md`），Windows 克隆不会出现"已修改"假象。
- **路径**：数据库与备份路径全部经 `Path` 处理，支持 Windows 盘符、UNC 与 Linux 绝对路径；`MONEYHELPER_DB_PATH` 为相对路径时按启动目录解析。

# 部署配置指南

> 适用版本：2026-10 收尾版（空库首启 · 对话中枢 · 本地加密备份）。部署前建议先看根目录 `README.zh.md`（中文版）/ `README.md`（English）的快速开始。

## 1. 本地运行（默认方式）

环境要求：Python 3.10+、Node.js 20.19+ / 22.12+。

```bash
# 后端（必须在 backend 目录内启动）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # 可选：按需填模型/口令（不填也能跑，确定性模板兜底）
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8787

# 前端（两种模式任选）
cd frontend && npm install && npm run dev     # 开发模式 http://127.0.0.1:5198（/api 反代 8788）
cd frontend && npm run build                  # 生产模式：构建后由后端单端口托管 http://127.0.0.1:8787
```

一键启动：根目录执行 `scripts/dev.sh`（后端 8788 + 前端 dev 5198，Ctrl-C 一起退出）。

## 2. Docker 部署（单容器）

```bash
docker compose up -d --build     # http://<服务器IP>:8787
```

- 服务名 `moneyhelper`，同端口 8787；数据卷 `moneyhelper-data` 挂载 `/app/backend/data`（SQLite + 备份包持久化）。
- 环境变量经 `docker-compose.yml` 透传：`API_TOKEN` / `ALLOWED_HOSTS` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`，也可全部留空、启动后在应用内设置页配置 AI。
- 健康检查：`/api/health`，30s 间隔，失败自动重启（`restart: unless-stopped`）。

## 3. 外网 / 局域网访问（安全配置）

应用默认**只放行本机访问**，对外暴露前必须配置访问口令：

| 场景 | 配置 |
|---|---|
| 局域网（NAS / 内网主机名） | 设 `ALLOWED_HOSTS=nas.local,10.0.0.5`（逗号分隔），不设口令 |
| 公网 / 反代 / 多用户 | **必须设 `API_TOKEN`**：所有 `/api/*` 需 `Authorization: Bearer <口令>` 或 `?token=<口令>`；前端首次访问弹出口令输入框 |

```bash
# 反代示例（nginx，端口 8787，口径一致）
location / { proxy_pass http://127.0.0.1:8787; }
```

## 4. 数据与备份

- 全部个人数据存 `backend/data/wealth.db`（SQLite，WAL）；备份包写 `backend/data/backups/`（在 Docker 数据卷内，容器重建不丢）。
- **备份**：设置 → 数据与状态 → 导出。**推荐设备份口令**——带口令导出为加密包（PBKDF2 派生密钥 + Fernet 加密），口令不落盘、只显示一次、忘记无法找回；无口令导出为明文（导出前有强提示）。
- **恢复**：设置 → 数据与状态 → 恢复备份，选择加密包并输入同一口令；口令错误会整体拒绝并回滚。
- 迁移：备份包为单文件 JSON，复制到新环境后用「恢复备份」导入即可（AI Key 除外，需重新填写）。

## 5. 升级 / 更新

- 后端 schema 变更由 `db.py` 增量迁移自动完成，历史数据保留；备份包格式带版本号（`version` 字段），恢复时校验。
- 前端升级后执行 `npm run build`（自动 bump Service Worker 缓存版本，避免旧 SW 拦截新产物）。

## 6. 定时任务

每日晨报由后端 APScheduler 驱动，默认 08:00 生成并归档（设置 → 每日晨报可改时间/立即生成）。调度状态：`GET /api/scheduler`。注意：晨报依赖 AI 或确定性模板，均不中断服务。
