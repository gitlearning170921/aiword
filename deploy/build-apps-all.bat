@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VER=%~1"
if "%VER%"=="" set "VER=1.0.0"

echo [1/2] build apps only ^(no chroma^)...
call "%~dp0build-apps-docker.bat" %VER%
if errorlevel 1 exit /b 1

echo [2/2] export apps...
call "%~dp0export-apps-docker.bat" %VER%
if errorlevel 1 exit /b 1

echo ALL DONE apps version=%VER%
echo Upload: dist\aiword-%VER%.tar.gz dist\aicheckword-%VER%.tar.gz
echo Server: UPGRADE_APPS_ONLY=1 NEW_IMAGE_VERSION=%VER% ./upgrade.sh
exit /b 0
