@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

echo ========================================
echo   GT 审计助手 - 一键启动
echo ========================================
echo.

:: 记录脚本所在目录（保留末尾反斜杠）
set "ROOT=%~dp0"

:: ─── 0. 停止旧进程 ───
echo [0/4] 停止旧进程...
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":9980 " ^| findstr "LISTENING"') do (
    echo   停止后端 PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":3030 " ^| findstr "LISTENING"') do (
    echo   停止前端 PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

:: 再次确认端口已释放
for /f "tokens=5" %%a in ('netstat -aon 2^>nul ^| findstr ":9980 " ^| findstr "LISTENING"') do (
    echo   强制停止残留进程 PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: ─── 1. 检测 Python ───
echo [1/4] 检测 Python 环境...
set "PYTHON_CMD="
if exist "%ROOT%.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%ROOT%.venv\Scripts\python.exe"
    echo   使用虚拟环境: %ROOT%.venv
) else if exist "%ROOT%backend\.venv\Scripts\python.exe" (
    set "PYTHON_CMD=%ROOT%backend\.venv\Scripts\python.exe"
    echo   使用虚拟环境: %ROOT%backend\.venv
) else (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python"
        echo   使用系统 Python
    ) else (
        echo [错误] 未找到 Python，请安装 Python 3.10+
        pause
        exit /b 1
    )
)
!PYTHON_CMD! --version

:: ─── 2. 检测 Node.js ───
echo [2/4] 检测 Node.js 环境...
where node >nul 2>&1
if !errorlevel! neq 0 (
    echo [错误] 未找到 Node.js，请安装 Node.js 16+
    pause
    exit /b 1
)
node --version

:: 检查前端依赖
if not exist "%ROOT%frontend\node_modules" (
    echo   安装前端依赖...
    pushd "%ROOT%frontend"
    call npm install
    popd
)

:: ─── 3. 生成启动脚本并启动后端 ───
echo [3/4] 启动后端 (port 9980)...

:: 写一个临时 bat 来启动后端（避免路径引号嵌套问题）
> "%TEMP%\_gt_backend.bat" (
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo cd /d "%ROOT%backend"
    echo !PYTHON_CMD! run.py
    echo pause
)
start "GT-Backend" /min "%TEMP%\_gt_backend.bat"

:: 等待后端就绪
echo   等待后端启动...
set "READY=0"
for /l %%i in (1,1,20) do (
    if !READY! equ 0 (
        timeout /t 1 /nobreak >nul
        curl -s -o nul -w "" http://127.0.0.1:9980/health >nul 2>&1
        if !errorlevel! equ 0 (
            set "READY=1"
            echo   后端已就绪
        )
    )
)
if !READY! equ 0 (
    echo   [警告] 后端未在20秒内响应，继续启动前端...
)

:: ─── 4. 启动前端 ───
echo [4/4] 启动前端 (port 3030)...

> "%TEMP%\_gt_frontend.bat" (
    echo @echo off
    echo chcp 65001 ^>nul 2^>^&1
    echo cd /d "%ROOT%frontend"
    echo set PORT=3030
    echo call npm start
    echo pause
)
start "GT-Frontend" /min "%TEMP%\_gt_frontend.bat"

:: 等待前端就绪
timeout /t 6 /nobreak >nul

:: ─── 完成 ───
echo.
echo ========================================
echo   后端: http://127.0.0.1:9980
echo   前端: http://localhost:3030
echo ========================================
echo.
echo 正在打开浏览器...
start http://localhost:3030
echo.
echo 服务已启动，关闭此窗口不影响运行。
echo 按任意键关闭此窗口...
pause >nul
