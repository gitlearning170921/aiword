@echo off
call "%~dp0export-images-docker.bat" %*
exit /b %ERRORLEVEL%
