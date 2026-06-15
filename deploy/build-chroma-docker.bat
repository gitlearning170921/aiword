@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem 本机 pull chromadb/chroma 并打 tag chroma:<version>，供 export / 离线 load

set "VER=%~1"
if "%VER%"=="" set "VER=1.0.0"

set "CHROMA_TAG="
if exist "%~dp0chroma-image.tag" (
  set /p CHROMA_TAG=<"%~dp0chroma-image.tag"
)
if "%CHROMA_TAG%"=="" set "CHROMA_TAG=0.6.3"
set "CHROMA_UPSTREAM=chromadb/chroma:%CHROMA_TAG%"

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: docker not found. Install Docker Desktop and restart terminal.
  exit /b 1
)

set "PLATFORM=linux/amd64"

echo ==^> pull %CHROMA_UPSTREAM% platform=%PLATFORM%
echo     tip: needs Docker Hub on build PC; server only docker load, no pull
docker pull --platform %PLATFORM% %CHROMA_UPSTREAM%
if errorlevel 1 (
  echo ERROR: pull failed. Configure Docker Desktop registry-mirror or VPN on build PC.
  exit /b 1
)

docker tag %CHROMA_UPSTREAM% chroma:%VER%
docker tag chroma:%VER% chroma:local

echo.
echo CHROMA BUILD OK chroma:%VER% ^(from %CHROMA_UPSTREAM%^)
echo Next: .\export-images-docker.bat %VER%
exit /b 0
