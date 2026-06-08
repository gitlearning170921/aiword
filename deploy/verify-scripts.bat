@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "FAIL=0"

echo === deploy script self-check ===

where docker >nul 2>&1
if errorlevel 1 (
  echo [FAIL] docker not in PATH
  set "FAIL=1"
) else (
  echo [OK] docker found
)

set "AIWORD_ROOT=%~dp0.."
for %%I in ("%AIWORD_ROOT%") do set "AIWORD_ROOT=%%~fI"
set "AICHECKWORD_ROOT=%AIWORD_ROOT%\..\aicheckword"
for %%I in ("%AICHECKWORD_ROOT%") do set "AICHECKWORD_ROOT=%%~fI"

if exist "%AIWORD_ROOT%\Dockerfile" (echo [OK] aiword Dockerfile) else (echo [FAIL] aiword Dockerfile & set "FAIL=1")
if exist "%AICHECKWORD_ROOT%\Dockerfile" (echo [OK] aicheckword Dockerfile) else (echo [FAIL] aicheckword Dockerfile & set "FAIL=1")

for %%B in (build-images-docker.bat export-images-docker.bat pack-for-server-docker.bat build-all.bat) do (
  if exist "%~dp0%%B" (echo [OK] %%B) else (echo [FAIL] missing %%B & set "FAIL=1")
)

powershell -NoProfile -EP Bypass -Command "exit 0" >nul 2>&1
if errorlevel 1 (
  echo [FAIL] powershell
  set "FAIL=1"
) else (
  echo [OK] powershell
  powershell -NoProfile -EP Bypass -Command "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('%~dp0build-images.ps1', [ref]$null, [ref]$e); if($e){ exit 1 } else { exit 0 }" >nul 2>&1
  if errorlevel 1 (
    echo [WARN] build-images.ps1 syntax check failed - use *-docker.bat
  ) else (
    echo [OK] build-images.ps1 syntax
  )
)

echo.
echo === docker registry (skip slow pull; run build-all when network OK) ===
echo [INFO] if build fails on python:3.11-slim-bookworm, set Docker Desktop registry mirror

echo.
if "%FAIL%"=="1" (
  echo SELF-CHECK FAILED
  exit /b 1
)
echo SELF-CHECK PASSED - run: .\build-all.bat 1.0.0
exit /b 0
