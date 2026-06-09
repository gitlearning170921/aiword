@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VER=%~1"
if "%VER%"=="" set "VER=1.0.0"

set "AIWORD_ROOT=%~dp0.."
for %%I in ("%AIWORD_ROOT%") do set "AIWORD_ROOT=%%~fI"
set "AICHECKWORD_ROOT=%AIWORD_ROOT%\..\aicheckword"
for %%I in ("%AICHECKWORD_ROOT%") do set "AICHECKWORD_ROOT=%%~fI"

if not exist "%AICHECKWORD_ROOT%\Dockerfile" (
  echo ERROR: aicheckword not found: %AICHECKWORD_ROOT%
  exit /b 1
)

where docker >nul 2>&1
if errorlevel 1 (
  echo ERROR: docker not found. Install Docker Desktop and restart terminal.
  exit /b 1
)

set "DOCKER_BUILDKIT=1"
set "PLATFORM=linux/amd64"
set "PROGRESS=%DOCKER_PROGRESS%"
if "%PROGRESS%"=="" set "PROGRESS=plain"

set "TMPDIR=%TEMP%\aiword-docker-build-%RANDOM%"
mkdir "%TMPDIR%" 2>nul

echo ==^> parallel build aiword:%VER% + aicheckword:%VER% platform=%PLATFORM%

start "build-aiword" /MIN cmd /c "set DOCKER_BUILDKIT=1&& docker build --progress=%PROGRESS% --platform %PLATFORM% -t aiword:%VER% -f "%AIWORD_ROOT%\Dockerfile" "%AIWORD_ROOT%" > "%TMPDIR%\aiword.log" 2>&1 && echo OK> "%TMPDIR%\aiword.ok" || echo FAIL> "%TMPDIR%\aiword.fail""

start "build-aicheckword" /MIN cmd /c "set DOCKER_BUILDKIT=1&& docker build --progress=%PROGRESS% --platform %PLATFORM% -t aicheckword:%VER% -f "%AICHECKWORD_ROOT%\Dockerfile" "%AICHECKWORD_ROOT%" > "%TMPDIR%\aicheckword.log" 2>&1 && echo OK> "%TMPDIR%\aicheckword.ok" || echo FAIL> "%TMPDIR%\aicheckword.fail""

:wait_builds
if not exist "%TMPDIR%\aiword.ok" if not exist "%TMPDIR%\aiword.fail" goto wait_builds
if not exist "%TMPDIR%\aicheckword.ok" if not exist "%TMPDIR%\aicheckword.fail" goto wait_builds

set "RC=0"
if exist "%TMPDIR%\aiword.fail" (
  echo ERROR: aiword build failed. See %TMPDIR%\aiword.log
  set "RC=1"
)
if exist "%TMPDIR%\aicheckword.fail" (
  echo ERROR: aicheckword build failed. See %TMPDIR%\aicheckword.log
  set "RC=1"
)
if not "%RC%"=="0" exit /b %RC%

docker tag aiword:%VER% aiword:local
docker tag aicheckword:%VER% aicheckword:local

if not exist "%~dp0dist" mkdir "%~dp0dist"
echo version=%VER%> "%~dp0dist\manifest-%VER%.txt"
echo platform=%PLATFORM%>> "%~dp0dist\manifest-%VER%.txt"
echo buildkit=1>> "%~dp0dist\manifest-%VER%.txt"

echo.
echo BUILD OK version=%VER%
echo Next: .\export-images-docker.bat %VER%
exit /b 0
