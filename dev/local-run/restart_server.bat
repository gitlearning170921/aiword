@echo off
cd /d "%~dp0..\.."
call "%~dp0stop_server.bat"
call "%~dp0start_server.bat"
