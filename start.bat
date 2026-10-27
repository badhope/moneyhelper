@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Moneyhelper · 一键启动
cd /d "%~dp0"

rem 生产模式：start.bat --prod  → 构建前端后由后端单端口伺服，只开一个窗口
set MODE=dev
if /i "%~1"=="--prod" set MODE=prod

echo ============================================
echo    Moneyhelper  ·  一键启动（%MODE%）
echo    后端  http://127.0.0.1:8788
if "%MODE%"=="dev" echo    前端  http://127.0.0.1:5198
echo ============================================
echo.

rem ---- Python 探测（优先 py 启动器，其次 python）--------------------------
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" ( where python >nul 2>nul && set PY=python )
if "%PY%"=="" (
  echo [错误] 未找到 Python（需 3.10+）。请安装后重试：https://www.python.org/downloads/
  echo        安装时请勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)

rem ---- 后端虚拟环境：缺失则自动创建并装依赖 --------------------------------
if not exist "backend\.venv\Scripts\python.exe" (
  echo == 创建后端虚拟环境 ==
  %PY% -m venv backend\.venv
  if errorlevel 1 (
    echo [错误] 创建虚拟环境失败。
    pause
    exit /b 1
  )
)
set VPY=%~dp0backend\.venv\Scripts\python.exe

"%VPY%" -c "import fastapi, uvicorn, aiosqlite, fastmcp" >nul 2>nul
if errorlevel 1 (
  echo == 安装后端依赖（首次约 2-5 分钟）==
  "%VPY%" -m pip install -q --disable-pip-version-check -r backend\requirements.txt
  if errorlevel 1 (
    echo [错误] 后端依赖安装失败，请检查网络或代理后重试。
    pause
    exit /b 1
  )
)

rem ---- 前端依赖 ------------------------------------------------------------
where npm >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 npm（需 Node.js 18+）：https://nodejs.org/
  pause
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo == 安装前端依赖（首次约 1-3 分钟）==
  pushd frontend
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    popd
    echo [错误] 前端依赖安装失败。
    pause
    exit /b 1
  )
  popd
)

if /i "%MODE%"=="prod" goto :prod

echo 正在启动后端（8788）...
start "Moneyhelper 后端-8788" cmd /k ""%VPY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8788 --app-dir backend"

timeout /t 3 /nobreak >nul

echo 正在启动前端（5198）...
start "Moneyhelper 前端-5198" cmd /k "cd /d ""%~dp0frontend"" && npm run dev"

timeout /t 6 /nobreak >nul

echo 正在打开浏览器...
start "" http://127.0.0.1:5198/

echo.
echo 已启动完成。
echo   - 保持两个控制台窗口运行；关掉任一窗口即对应服务停止。
echo   - 若浏览器没自动打开，请手动访问 http://127.0.0.1:5198
echo.
pause
exit /b 0

:prod
echo == 构建前端（生产包）==
pushd frontend
call npm run build
if errorlevel 1 (
  popd
  echo [错误] 前端构建失败。
  pause
  exit /b 1
)
popd
echo 正在启动单端口服务（8788，前端由后端托管）...
start "Moneyhelper-8788" cmd /k ""%VPY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8788 --app-dir backend"
timeout /t 3 /nobreak >nul
start "" http://127.0.0.1:8788/
echo 已启动（生产模式）：http://127.0.0.1:8788
pause
exit /b 0
