@echo off
cd /d "%~dp0..\.."
echo [local-run] 后台启动 aiword，日志见 server.log
echo 前台调试请用 dev\local-run\start_server_foreground.bat
python start_server_background.py
if errorlevel 1 echo [失败] 见 server.log
pause
