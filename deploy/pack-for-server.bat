@echo off
call "%~dp0pack-for-server-docker.bat" %*
exit /b %ERRORLEVEL%
