@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem 仅构建并导出 chroma 镜像（服务器无法 docker pull 时用）

set "VER=%~1"
if "%VER%"=="" set "VER=1.0.0"

call "%~dp0build-chroma-docker.bat" %VER%
if errorlevel 1 exit /b 1

where gzip >nul 2>&1
if errorlevel 1 (
  echo ==^> save chroma:%VER% .tar
  docker save -o "%~dp0dist\chroma-%VER%.tar" chroma:%VER%
) else (
  echo ==^> save chroma:%VER% .tar.gz
  if not exist "%~dp0dist" mkdir "%~dp0dist"
  docker save chroma:%VER% | gzip -1 > "%~dp0dist\chroma-%VER%.tar.gz"
)

echo.
echo CHROMA PACK OK - upload dist\chroma-%VER%.tar.gz to server images/
echo Server: gunzip -c chroma-%VER%.tar.gz ^| docker load
exit /b 0
