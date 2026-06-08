@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if "%~1"=="" (
  echo Usage: export-images-docker.bat ^<version^>
  exit /b 1
)

set "VER=%~1"
if not exist "%~dp0dist" mkdir "%~dp0dist"

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: docker not found
  exit /b 1
)

echo ==^> save aiword:%VER%
docker save -o "%~dp0dist\aiword-%VER%.tar" aiword:%VER%
if errorlevel 1 exit /b 1

echo ==^> save aicheckword:%VER%
docker save -o "%~dp0dist\aicheckword-%VER%.tar" aicheckword:%VER%
if errorlevel 1 exit /b 1

echo EXPORT OK: dist\aiword-%VER%.tar dist\aicheckword-%VER%.tar
exit /b 0
