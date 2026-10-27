# 打包成 Windows EXE

Moneyhelper 可以打包成单个 EXE 文件，用户双击就能跑，不需要装 Python / Node。

## 打包步骤

### 1. 先 build 前端

```bash
cd frontend
npm install
npm run build
# 产物在 frontend/dist/
```

### 2. 安装打包工具

```bash
cd backend
pip install pyinstaller
```

### 3. 打包

```bash
pyinstaller moneyhelper.spec
```

产物在 `dist/moneyhelper.exe`。

### 4. 测试

双击 `dist/moneyhelper.exe`，应该：
1. 弹出控制台窗口显示日志
2. 自动打开浏览器到 http://127.0.0.1:8788
3. 关掉控制台窗口就停服务

## 数据目录

**双击直接运行时**（不设环境变量）：用户数据存在 `~/.moneyhelper/`（Windows 即
`C:/Users/<你>/.moneyhelper`）—— SQLite、备份、LangGraph checkpoint 都在这里。
EXE 本身不存数据，删掉 EXE 不影响用户数据。

**从源码或脚本启动时**：数据在 `backend/data/`（可用 `MONEYHELPER_DATA_DIR` 覆盖）。
这一点在 2.4.2 修过一次：此前代码默认写 `backend/app/data`，与 Docker 卷不一致，
导致容器重建丢账本；现在统一由一个变量控制。

## 已知打包要点

- 必须 `npm run build` 先出前端产物；`moneyhelper.spec` 会断言 `frontend/dist` 存在。
- LiteLLM 有大量**动态导入的子模块**与**非 Python 资源**（模型价格表、tokenizer），
  PyInstaller 静态分析发现不了。spec 里用文件系统递归收集 `litellm.*` 并把整个
  `litellm` 目录作为 data 收集——这两步缺一，启动就会 `ModuleNotFoundError` 或
  `FileNotFoundError`（实测踩过）。
- 产物约 144MB（含 Python 运行时与全部依赖），首次启动解压需数秒。

## 注意事项

- EXE 大概 200-300MB（包含 Python 运行时 + 所有依赖）
- 第一次启动慢一点（要解压临时文件）
- Windows Defender 可能误报，加白名单就行
- 控制台窗口可以改成 GUI 模式（spec 里 `console=False`）
