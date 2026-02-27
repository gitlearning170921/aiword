@echo off
cd /d %~dp0
python stop_server.py
python start_server_background.py
pause




