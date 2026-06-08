@echo off
call "%~dp0build-images-docker.bat" %*
exit /b %ERRORLEVEL%
