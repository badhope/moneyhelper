# 快速开始（15 分钟）
## 1. 后端
```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env && $EDITOR .env   # 至少配一个模型的 key
.venv/bin/python -m uvicorn app.main:app --port 8000
```
## 2. 前端
```bash
cd frontend && npm install && npm run build   # 产物由后端同域托管
```
打开 http://127.0.0.1:8000 —— 空账本起步，先记第一笔：「午饭 28 元」。
## 3. 测试基线
```bash
.venv/bin/python -m pytest tests/ -q -n 4   # 546 个用例全绿
```
