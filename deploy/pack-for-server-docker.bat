@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if "%~1"=="" (
  echo Usage: pack-for-server-docker.bat ^<version^>
  exit /b 1
)

set "VER=%~1"
set "DIST=%~dp0dist"
set "BUNDLE=aiword-stack-%VER%"
set "STAGE=%DIST%\%BUNDLE%"
set "ZIP=%DIST%\%BUNDLE%.zip"

set "AIWORD_IMG="
set "AICHECKWORD_IMG="
if exist "%DIST%\aiword-%VER%.tar.gz" (
  set "AIWORD_IMG=%DIST%\aiword-%VER%.tar.gz"
) else if exist "%DIST%\aiword-%VER%.tar" (
  set "AIWORD_IMG=%DIST%\aiword-%VER%.tar"
)
if exist "%DIST%\aicheckword-%VER%.tar.gz" (
  set "AICHECKWORD_IMG=%DIST%\aicheckword-%VER%.tar.gz"
) else if exist "%DIST%\aicheckword-%VER%.tar" (
  set "AICHECKWORD_IMG=%DIST%\aicheckword-%VER%.tar"
)

if "%AIWORD_IMG%"=="" (
  echo ERROR: missing aiword image export for version %VER%
  exit /b 1
)
if "%AICHECKWORD_IMG%"=="" (
  echo ERROR: missing aicheckword image export for version %VER%
  exit /b 1
)

if exist "%STAGE%" rd /s /q "%STAGE%"
mkdir "%STAGE%"
mkdir "%STAGE%\images"

for %%F in (
  docker-compose.prod.yml
  .env.example
  server-deploy.sh
  server-load-images.sh
  backup.sh
  upgrade.sh
  build-images.bat
  build-images-docker.bat
  export-images.bat
  export-images-docker.bat
  pack-for-server.bat
  pack-for-server-docker.bat
  build-all.bat
  README.md
) do if exist "%~dp0%%F" copy /y "%~dp0%%F" "%STAGE%\" >nul

if exist "%~dp0nginx" xcopy /E /I /Y /Q "%~dp0nginx" "%STAGE%\nginx\" >nul

copy /y "%AIWORD_IMG%" "%STAGE%\images\" >nul
copy /y "%AICHECKWORD_IMG%" "%STAGE%\images\" >nul
if exist "%DIST%\manifest-%VER%.txt" copy /y "%DIST%\manifest-%VER%.txt" "%STAGE%\" >nul
echo %VER%> "%STAGE%\VERSION"

if exist "%ZIP%" del /f /q "%ZIP%"

where tar >nul 2>&1
if errorlevel 1 (
  echo ERROR: tar not found
  exit /b 1
)

pushd "%STAGE%"
tar -caf "%ZIP%" .
set "RC=%ERRORLEVEL%"
popd
if not "%RC%"=="0" exit /b %RC%

echo PACK OK: %ZIP%
exit /b 0
