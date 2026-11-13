# Isolated local dev launcher for Moneyhelper.
# - Uses only the project-local Python venv and the existing Node install.
# - Keeps caches, data, temp files and logs under D:\Moneyhelper.
# - Refuses to start when a port is already in use (never kills other processes).
# - Binds loopback only.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev-isolated.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev-isolated.ps1 -Prod
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\dev-isolated.ps1 -BackendPort 18789 -FrontendPort 15199

param(
    [int]$BackendPort = 18788,
    [int]$FrontendPort = 15198,
    [switch]$Prod
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
$NodeDir = "C:\Program Files\nodejs"
$Npm = Join-Path $NodeDir "npm.cmd"
$Frontend = Join-Path $Root "frontend"

if (-not (Test-Path $Py)) { throw "Project venv not found: $Py. Run the documented setup first." }
if (-not (Test-Path $Npm)) { throw "npm not found: $Npm" }

function Assert-PortFree([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
    }
    catch {
        throw "Port $Port is already in use. Stop the other program or choose another port with -BackendPort/-FrontendPort."
    }
    finally {
        try { $listener.Stop() } catch { }
    }
}

Assert-PortFree $BackendPort
if (-not $Prod) { Assert-PortFree $FrontendPort }

$Tmp = Join-Path $Root ".tmp"
$Data = Join-Path $Tmp "data"
$Logs = Join-Path $Tmp "logs"
New-Item -ItemType Directory -Force -Path $Tmp, $Data, $Logs | Out-Null

$env:MONEYHELPER_DATA_DIR = $Data
$env:TMP = $Tmp
$env:TEMP = $Tmp
$env:UV_CACHE_DIR = Join-Path $Root ".cache\uv"
$env:npm_config_cache = Join-Path $Root ".cache\npm"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root ".cache\playwright"
$env:PYTHONPATH = (Join-Path $Root "backend") + ";" + $Root
$env:Path = $NodeDir + ";" + $env:Path

if ($Prod) {
    Write-Host "Building frontend..."
    & $Npm --prefix $Frontend run build
    if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." }
}

$BackendLog = Join-Path $Logs "backend-$BackendPort.log"
$BackendErr = Join-Path $Logs "backend-$BackendPort.err.log"
$backend = Start-Process -FilePath $Py `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--app-dir", (Join-Path $Root "backend")) `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $BackendLog `
    -RedirectStandardError $BackendErr `
    -PassThru

Write-Host "Backend started: http://127.0.0.1:$BackendPort (pid $($backend.Id))"
Write-Host "  logs: $BackendLog"

if (-not $Prod) {
    $FrontendLog = Join-Path $Logs "frontend-$FrontendPort.log"
    $FrontendErr = Join-Path $Logs "frontend-$FrontendPort.err.log"
    $frontend = Start-Process -FilePath $Npm `
        -ArgumentList @("--prefix", $Frontend, "run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort") `
        -WorkingDirectory $Frontend `
        -RedirectStandardOutput $FrontendLog `
        -RedirectStandardError $FrontendErr `
        -PassThru

    Write-Host "Frontend started: http://127.0.0.1:$FrontendPort (pid $($frontend.Id))"
    Write-Host "  logs: $FrontendLog"
    Write-Host ""
    Write-Host "Stop with: Stop-Process -Id $($backend.Id),$($frontend.Id)"
}
else {
    Write-Host "Production mode: frontend is served by the backend at http://127.0.0.1:$BackendPort"
    Write-Host "Stop with: Stop-Process -Id $($backend.Id)"
}
