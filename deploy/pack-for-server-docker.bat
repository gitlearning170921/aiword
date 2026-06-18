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

set "CHROMA_IMG="
if exist "%DIST%\chroma-%VER%.tar.gz" (
  set "CHROMA_IMG=%DIST%\chroma-%VER%.tar.gz"
) else if exist "%DIST%\chroma-%VER%.tar" (
  set "CHROMA_IMG=%DIST%\chroma-%VER%.tar"
)
if "%CHROMA_IMG%"=="" (
  echo WARN: missing chroma export for version %VER% ^(remote Chroma will not load offline^)
)

if exist "%STAGE%" rd /s /q "%STAGE%"
mkdir "%STAGE%"
mkdir "%STAGE%\images"

for %%F in (
  docker-compose.prod.yml
  .env.example
  server-deploy.sh
  server-load-images.sh
  migrate-knowledge-store.sh
  backup.sh
  upgrade.sh
  build-images.bat
  build-images-docker.bat
  build-chroma-docker.bat
  export-images.bat
  export-images-docker.bat
  pack-for-server.bat
  pack-for-server-docker.bat
  build-all.bat
  build-apps-all.bat
  build-apps-docker.bat
  export-apps-docker.bat
  server-load-apps-only.sh
  README.md
) do if exist "%~dp0%%F" copy /y "%~dp0%%F" "%STAGE%\" >nul

if exist "%~dp0nginx" xcopy /E /I /Y /Q "%~dp0nginx" "%STAGE%\nginx\" >nul

copy /y "%AIWORD_IMG%" "%STAGE%\images\" >nul
copy /y "%AICHECKWORD_IMG%" "%STAGE%\images\" >nul
if not "%CHROMA_IMG%"=="" copy /y "%CHROMA_IMG%" "%STAGE%\images\" >nul
if exist "%~dp0chroma-image.tag" copy /y "%~dp0chroma-image.tag" "%STAGE%\" >nul
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
