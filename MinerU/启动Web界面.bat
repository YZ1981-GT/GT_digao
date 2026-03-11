@echo off
chcp 65001 >nul
cd /d E:\MinerU
call mineru_env\Scripts\activate.bat

echo.
echo ========================================
echo 正在启动 MinerU Web 界面...
echo ========================================
echo.
echo 启动后请访问: http://localhost:7860
echo.
echo 按 Ctrl+C 可以停止服务
echo ========================================
echo.

python web_ui.py

pause
