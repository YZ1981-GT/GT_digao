@echo off
setlocal EnableDelayedExpansion

echo ========================================
echo   GT Audit Helper - Startup
echo ========================================
echo.

:: Kill existing processes on port 9980 and 3030
echo [0/3] Stopping old processes...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":9980 " ^| findstr "LISTENING"') do (
    echo   Kill backend PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":3030 " ^| findstr "LISTENING"') do (
    echo   Kill frontend PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)
ping -n 2 127.0.0.1 >nul

:: Check venv
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] .venv not found. Run: python -m venv .venv
    pause
    exit /b 1
)

:: Activate venv
call .venv\Scripts\activate.bat

:: Install deps
echo [1/3] Checking backend dependencies...
pip install -r backend\requirements.txt -q

:: Create temp VBS launchers (hidden windows)
echo Set ws = CreateObject("WScript.Shell") > "%TEMP%\_gt_start_backend.vbs"
echo ws.Run "cmd /c cd /d %~dp0 && call .venv\Scripts\activate.bat && cd backend && python run.py", 0, False >> "%TEMP%\_gt_start_backend.vbs"

echo Set ws = CreateObject("WScript.Shell") > "%TEMP%\_gt_start_frontend.vbs"
echo ws.Run "cmd /c cd /d %~dp0\frontend && npm start", 0, False >> "%TEMP%\_gt_start_frontend.vbs"

:: Start backend
echo [2/3] Starting backend (port 9980)...
cscript //nologo "%TEMP%\_gt_start_backend.vbs"

:: Wait for backend
ping -n 4 127.0.0.1 >nul

:: Start frontend
echo [3/3] Starting frontend (port 3030)...
cscript //nologo "%TEMP%\_gt_start_frontend.vbs"

:: Cleanup temp files
del "%TEMP%\_gt_start_backend.vbs" 2>nul
del "%TEMP%\_gt_start_frontend.vbs" 2>nul

echo.
echo ========================================
echo   Backend:  http://127.0.0.1:9980
echo   Frontend: http://localhost:3030
echo ========================================
echo.
echo Services started. You can close this window.
echo.
pause >nul
