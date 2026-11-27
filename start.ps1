Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "             STARTING PHOTOCAD STUDIO (v1.0)              " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$ROOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path "$ROOT_DIR\.env") -and (Test-Path "$ROOT_DIR\.env.example")) {
    Write-Host "[!] No .env detected - running in Zero-Heat Local Fallback mode." -ForegroundColor Yellow
    Write-Host "    Copy .env.example to .env to enable Modal L4 GPU & live Gemini/Claude models." -ForegroundColor DarkGray
}

# 1. Start FastAPI Backend
Write-Host "[1/2] Launching FastAPI + LangGraph Backend on http://localhost:8000..." -ForegroundColor Green
$backendProcess = Start-Process -FilePath "$ROOT_DIR\backend\.venv\Scripts\python.exe" -ArgumentList "-m uvicorn app.main:app --reload --port 8000" -WorkingDirectory "$ROOT_DIR\backend" -PassThru

# 2. Start Vite Frontend Dev Server
Write-Host "[2/2] Launching React Three Fiber Studio on http://localhost:5173..." -ForegroundColor Green
$frontendProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory "$ROOT_DIR\frontend" -PassThru

Write-Host "`nPhotoCAD Studio v1.0 is up and running!" -ForegroundColor Cyan
Write-Host "3D CAD Studio:      http://localhost:5173" -ForegroundColor Yellow
Write-Host "FastAPI Swagger:    http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host "Cloud Tier Health:  http://localhost:8000/api/health/cloud" -ForegroundColor Yellow
Write-Host "`nPress Ctrl+C or close the opened windows to stop."
