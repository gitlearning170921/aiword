@echo off
setlocal EnableExtensions
cd /d "%~dp0"
rem Build aiword + aicheckword only (skip chroma)

rem 打包机本地配置（不进 Git）：复制 build-machine.env.bat.example 为 d:\aicode\build-machine.env.bat
if exist "d:\aicode\build-machine.env.bat" call "d:\aicode\build-machine.env.bat"
if exist "%~dp0build-machine.env.bat" call "%~dp0build-machine.env.bat"
if exist "%~dp0SKIP_DOCKER_JS_CHECK" set "SKIP_DOCKER_JS_CHECK=1"

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
if defined DOCKER_MACHINE_NAME if "%DOCKER_LEGACY_BUILD%"=="" set "DOCKER_LEGACY_BUILD=1"
if /I "%DOCKER_LEGACY_BUILD%"=="1" (
  set "DOCKER_BUILDKIT=0"
  echo [INFO] DOCKER_LEGACY_BUILD=1 ^(Docker Toolbox 兼容模式^)
)
set "PLATFORM=linux/amd64"
set "PROGRESS=%DOCKER_PROGRESS%"
if "%PROGRESS%"=="" set "PROGRESS=plain"

echo ==^> release gate (JS orphan / template parity / py_compile)...
python "%AIWORD_ROOT%\scripts\validate_release_gate.py"
if errorlevel 1 exit /b 1

echo ==^> JS syntax check... SKIP_DOCKER_JS_CHECK=%SKIP_DOCKER_JS_CHECK%
if /I "%SKIP_DOCKER_JS_CHECK%"=="1" (
  where node >nul 2>&1
  if errorlevel 1 (
    echo ERROR: SKIP_DOCKER_JS_CHECK=1 but node not in PATH. Install Node.js LTS or unset SKIP_DOCKER_JS_CHECK.
    exit /b 1
  )
  echo     using local node ^(SKIP_DOCKER_JS_CHECK=1^)
  node "%AIWORD_ROOT%\scripts\check_js_syntax.js"
  if errorlevel 1 exit /b 1
) else (
  call :JsDockerCheck
  if errorlevel 1 exit /b 1
)

echo ==^> build aiword:%VER% platform=%PLATFORM%
docker build --progress=%PROGRESS% --platform %PLATFORM% --build-arg APP_VERSION=%VER% -t aiword:%VER% -f "%AIWORD_ROOT%\Dockerfile" "%AIWORD_ROOT%"
if errorlevel 1 exit /b 1

echo.
echo ==^> build aicheckword:%VER% platform=%PLATFORM%
docker build --progress=%PROGRESS% --platform %PLATFORM% --build-arg APP_VERSION=%VER% -t aicheckword:%VER% -f "%AICHECKWORD_ROOT%\Dockerfile" "%AICHECKWORD_ROOT%"
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

:JsDockerCheck
docker image inspect node:20-alpine >nul 2>&1
if errorlevel 1 (
  echo     pulling node:20-alpine ^(slow Hub: set SKIP_DOCKER_JS_CHECK=1 and use local node^)...
)
if /I "%DOCKER_LEGACY_BUILD%"=="1" (
  call :WinPathToDockerVol "%AIWORD_ROOT%" DOCKER_JS_VOL
) else (
  set "DOCKER_JS_VOL=%AIWORD_ROOT%"
)
echo     volume %DOCKER_JS_VOL%:/app:ro
docker run --rm -v "%DOCKER_JS_VOL%:/app:ro" -w /app node:20-alpine node scripts/check_js_syntax.js
if errorlevel 1 (
  where node >nul 2>&1
  if not errorlevel 1 (
    echo [WARN] docker JS check failed, fallback to local node...
    node "%AIWORD_ROOT%\scripts\check_js_syntax.js"
    if errorlevel 1 exit /b 1
  ) else (
    echo ERROR: JS check failed.
    echo   - Install Node.js LTS and set SKIP_DOCKER_JS_CHECK=1 in build-machine.env.bat
    exit /b 1
  )
)
exit /b 0

rem Docker Toolbox vol path: d:\foo\bar -^> /d/foo/bar
:WinPathToDockerVol
set "_WP=%~1"
set "_WP=%_WP:\=/%"
set "_DRV=%_WP:~0,1%"
set "%~2=/%_DRV%%_WP:~2%"
exit /b 0
