Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "             STARTING PHOTOCAD STUDIO                     " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$ROOT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Start FastAPI Backend
Write-Host "[1/2] Launching FastAPI Backend on http://localhost:8000..." -ForegroundColor Green
$backendProcess = Start-Process -FilePath "$ROOT_DIR\backend\.venv\Scripts\python.exe" -ArgumentList "-m uvicorn app.main:app --reload --port 8000" -WorkingDirectory "$ROOT_DIR\backend" -PassThru

# 2. Start Vite Frontend Dev Server
Write-Host "[2/2] Launching Vite Frontend on http://localhost:5173..." -ForegroundColor Green
$frontendProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/c npm run dev" -WorkingDirectory "$ROOT_DIR\frontend" -PassThru

Write-Host "`nPhotoCAD is up and running!" -ForegroundColor Cyan
Write-Host "Frontend Viewport:  http://localhost:5173" -ForegroundColor Yellow
Write-Host "Backend API / Docs: http://localhost:8000/docs" -ForegroundColor Yellow
Write-Host "`nPress Ctrl+C or close the opened windows to stop."
