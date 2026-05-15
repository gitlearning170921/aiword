@echo off
cd /d %~dp0
echo 前台模式：日志与 Flask 输出在本窗口；按 Ctrl+C 停止服务
echo.
python run_web.py
pause
