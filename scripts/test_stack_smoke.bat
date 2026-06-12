@echo off
chcp 65001 >nul
cd /d "%~dp0\.."
python scripts\test_stack_smoke.py
if errorlevel 1 py -3 scripts\test_stack_smoke.py
pause
