@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VER=%~1"
if "%VER%"=="" set "VER=1.0.0"

echo [1/3] build...
call "%~dp0build-images-docker.bat" %VER%
if errorlevel 1 exit /b 1

echo [2/3] export...
call "%~dp0export-images-docker.bat" %VER%
if errorlevel 1 exit /b 1

echo [3/3] pack...
call "%~dp0pack-for-server-docker.bat" %VER%
if errorlevel 1 exit /b 1

echo ALL DONE version=%VER%
exit /b 0
