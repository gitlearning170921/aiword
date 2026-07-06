@echo off
cd /d "%~dp0..\.."
echo [local-run] 前台启动，Ctrl+C 停止
python run_web.py
pause
