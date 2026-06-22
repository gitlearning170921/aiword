@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem Export aiword + aicheckword only (daily upgrade; no chroma)

if "%~1"=="" (
  echo Usage: export-apps-docker.bat ^<version^>
  exit /b 1
)

set "VER=%~1"
if not exist "%~dp0dist" mkdir "%~dp0dist"

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: docker not found
  exit /b 1
)

set "USE_GZIP=0"
where gzip >nul 2>&1
if not errorlevel 1 set "USE_GZIP=1"

if "%USE_GZIP%"=="1" (
  echo ==^> save gzip aiword:%VER%
  docker save aiword:%VER% | gzip -1 > "%~dp0dist\aiword-%VER%.tar.gz"
  if errorlevel 1 exit /b 1

  echo ==^> save gzip aicheckword:%VER%
  docker save aicheckword:%VER% | gzip -1 > "%~dp0dist\aicheckword-%VER%.tar.gz"
  if errorlevel 1 exit /b 1

  echo EXPORT OK: dist\aiword-%VER%.tar.gz dist\aicheckword-%VER%.tar.gz
) else (
  echo WARN: gzip not found, exporting uncompressed .tar
  echo ==^> save aiword:%VER%
  docker save -o "%~dp0dist\aiword-%VER%.tar" aiword:%VER%
  if errorlevel 1 exit /b 1

  echo ==^> save aicheckword:%VER%
  docker save -o "%~dp0dist\aicheckword-%VER%.tar" aicheckword:%VER%
  if errorlevel 1 exit /b 1

  echo EXPORT OK: dist\aiword-%VER%.tar dist\aicheckword-%VER%.tar
  echo NOTE: server-load-apps-only.sh accepts .tar or .tar.gz
)
exit /b 0
