@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem 仅构建 aiword + aicheckword（日常升级用，不 pull/tag chroma）

set "VER=%~1"
if "%VER%"=="" (
  echo Usage: build-apps-docker.bat ^<version^>
  exit /b 1
)

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
  echo ERROR: docker not found
  exit /b 1
)

set "DOCKER_BUILDKIT=1"
set "PLATFORM=linux/amd64"
set "PROGRESS=%DOCKER_PROGRESS%"
if "%PROGRESS%"=="" set "PROGRESS=plain"

echo ==^> build aiword:%VER% platform=%PLATFORM%
docker build --progress=%PROGRESS% --platform %PLATFORM% -t aiword:%VER% -f "%AIWORD_ROOT%\Dockerfile" "%AIWORD_ROOT%"
if errorlevel 1 exit /b 1

echo.
echo ==^> build aicheckword:%VER% platform=%PLATFORM%
docker build --progress=%PROGRESS% --platform %PLATFORM% -t aicheckword:%VER% -f "%AICHECKWORD_ROOT%\Dockerfile" "%AICHECKWORD_ROOT%"
if errorlevel 1 exit /b 1

docker tag aiword:%VER% aiword:local
docker tag aicheckword:%VER% aicheckword:local

if not exist "%~dp0dist" mkdir "%~dp0dist"
echo version=%VER%> "%~dp0dist\manifest-%VER%.txt"
echo platform=%PLATFORM%>> "%~dp0dist\manifest-%VER%.txt"
echo apps_only=1>> "%~dp0dist\manifest-%VER%.txt"

echo.
echo APPS BUILD OK version=%VER% ^(chroma skipped^)
echo Next: .\export-apps-docker.bat %VER%
exit /b 0
