# Moneyhelper · 单容器部署（前端构建产物 + 后端 FastAPI，同端口 8787）
# 多阶段构建：node 出前端 → python 出 venv → 精简运行时合并
#
# 构建：docker build -t moneyhelper .
# 运行：docker run -p 8787:8787 -v moneyhelper-data:/app/backend/data moneyhelper
#       或直接 docker compose up -d --build（见 docker-compose.yml）

# ---------- 阶段 1：前端构建 ----------
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：后端依赖 ----------
FROM python:3.12-slim AS deps
WORKDIR /app
# 只装运行时依赖：测试依赖在 requirements-dev.txt（opencv 111MB 等），不进镜像
COPY backend/requirements.txt ./
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir -r requirements.txt

# ---------- 阶段 3：运行时 ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/venv/bin:$PATH \
    TZ=Asia/Shanghai

WORKDIR /app
COPY --from=deps /venv /venv
COPY --from=web /app/frontend/dist /app/frontend/dist
COPY backend/ /app/backend/

# 非 root 运行（安全最佳实践）：建 xia 用户，只把「运行期可写」的目录给它。
#
# 关键：不能 chown -R /app。源码与前端产物对运行进程应当只读——
# 一旦进程被注入任意写原语，可写源码就等于可持久化后门；
# 配合本仓库的 pathguard（MONEYHELPER_ALLOW_SYSTEM_ACCESS 默认关闭），
# 形成「代码只读 + 数据可写」的双层边界。
RUN useradd --create-home --uid 1000 --user-group xia \
    && mkdir -p /app/backend/data /app/backend/logs \
    && chown -R root:root /app \
    && chown -R xia:xia /app/backend/data /app/backend/logs \
    && chmod -R a+rX /app \
    && chmod -R u+w /app/backend/data /app/backend/logs

WORKDIR /app/backend
# 数据目录持久化（SQLite + 备份 + LangGraph checkpoint），容器重启不丢数据。
# 显式声明 MONEYHELPER_DATA_DIR，与代码里的 data_dir() 默认值保持同一语义；
# 之前代码默认写 app/data、卷挂 backend/data，导致重建即丢账本。
ENV MONEYHELPER_DATA_DIR=/app/backend/data
VOLUME /app/backend/data
EXPOSE 8787

USER xia

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
