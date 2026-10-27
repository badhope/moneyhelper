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

# 非 root 运行（安全最佳实践）：建 xia 用户，应用文件与数据目录归其所有
RUN useradd --create-home --uid 1000 --user-group xia \
    && mkdir -p /app/backend/data \
    && chown -R xia:xia /app \
    && chmod -R a+rX /app

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
