@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem ============================================================
rem  server-build-from-git.bat
rem  在 Windows 打包服务器：按 git tag 同步 aiword + aicheckword 双仓库，
rem  然后调用 build-all.bat 打镜像、出部署 zip。
rem  用法： server-build-from-git.bat <version>      ^(必填，例如 1.0.2^)
rem  前置：
rem    1) 已装 Git for Windows + Docker Desktop ^(WSL2/Linux containers^)
rem    2) 已配置 GitHub 凭据（HTTPS PAT 或 SSH key）
rem    3) 已基于 server-build.config.bat.example 复制出 server-build.config.bat 并填好
rem    4) 开发机已运行过 release.bat <version>，双仓库都有同名 tag v<version>
rem ============================================================

if "%~1"=="" (
    echo Usage: server-build-from-git.bat ^<version^>
    echo   e.g.  server-build-from-git.bat 1.0.2
    exit /b 1
)
set "VER=%~1"
set "TAG=v%VER%"

if not exist "%~dp0server-build.config.bat" (
    echo [ERROR] 缺少 server-build.config.bat
    echo         请先： copy server-build.config.bat.example server-build.config.bat
    echo         然后编辑填入 GIT_AIWORD_URL / GIT_AICHECKWORD_URL / BUILD_ROOT
    exit /b 1
)
call "%~dp0server-build.config.bat"

if not defined GIT_AIWORD_URL (
    echo [ERROR] server-build.config.bat 未设置 GIT_AIWORD_URL
    exit /b 1
)
if not defined GIT_AICHECKWORD_URL (
    echo [ERROR] server-build.config.bat 未设置 GIT_AICHECKWORD_URL
    exit /b 1
)
if not defined BUILD_ROOT set "BUILD_ROOT=%USERPROFILE%\aiword-build"

where git >nul 2>&1
if errorlevel 1 ( echo [ERROR] git not found in PATH. & exit /b 1 )
where docker >nul 2>&1
if errorlevel 1 ( echo [ERROR] docker not found. 请安装 Docker Desktop. & exit /b 1 )

docker version >nul 2>&1
if errorlevel 1 ( echo [ERROR] Docker 未运行，请启动 Docker Desktop. & exit /b 1 )

if not exist "%BUILD_ROOT%" mkdir "%BUILD_ROOT%"

rem 安全校验：脚本所在目录不能落在 BUILD_ROOT 里，否则 git clean 会把自己清掉
for %%I in ("%~dp0..\..") do set "DRIVER_PARENT=%%~fI"
for %%I in ("%BUILD_ROOT%") do set "BUILD_ROOT_ABS=%%~fI"
if /I "%DRIVER_PARENT%"=="%BUILD_ROOT_ABS%" (
    echo [ERROR] 检测到 server-build-from-git.bat 位于 BUILD_ROOT 内部：
    echo         脚本所在:    %~dp0
    echo         BUILD_ROOT:  %BUILD_ROOT_ABS%
    echo         请把 deploy 目录的副本（含 server-build.config.bat）放到 BUILD_ROOT 之外，
    echo         例如  D:\aiword-build-driver\aiword\deploy\
    exit /b 1
)

echo ============================================================
echo  打包服务器同步并构建
echo    VERSION    = %VER%
echo    TAG        = %TAG%
echo    BUILD_ROOT = %BUILD_ROOT_ABS%
echo    AIWORD URL = %GIT_AIWORD_URL%
echo    AICHK URL  = %GIT_AICHECKWORD_URL%
echo ============================================================

rem ----------------------------------------------------------------
rem  同步 aiword
rem ----------------------------------------------------------------
if not exist "%BUILD_ROOT%\aiword\.git" (
    echo.
    echo [aiword] clone -^> %BUILD_ROOT%\aiword
    pushd "%BUILD_ROOT%"
    git clone "%GIT_AIWORD_URL%" aiword
    set "RC=!ERRORLEVEL!"
    popd
    if not "!RC!"=="0" ( echo [ERROR] aiword clone 失败 & exit /b !RC! )
) else (
    echo.
    echo [aiword] fetch --all --tags --prune
    pushd "%BUILD_ROOT%\aiword"
    git fetch --all --tags --prune
    set "RC=!ERRORLEVEL!"
    popd
    if not "!RC!"=="0" ( echo [ERROR] aiword fetch 失败 & exit /b !RC! )
)

echo [aiword] checkout %TAG%
pushd "%BUILD_ROOT%\aiword"
git rev-parse -q --verify "refs/tags/%TAG%" >nul
if errorlevel 1 (
    echo [ERROR] aiword 仓库不存在 tag %TAG%。请先在开发机运行 release.bat %VER%。
    popd & exit /b 1
)
git checkout -f "%TAG%"
if errorlevel 1 ( echo [ERROR] aiword checkout 失败 & popd & exit /b 1 )
git reset --hard "%TAG%"
rem 仅清 untracked，不动 ignored（保留 deploy/dist 下的历史 build 产物）
git clean -fd
popd

rem ----------------------------------------------------------------
rem  同步 aicheckword
rem ----------------------------------------------------------------
if not exist "%BUILD_ROOT%\aicheckword\.git" (
    echo.
    echo [aicheckword] clone -^> %BUILD_ROOT%\aicheckword
    pushd "%BUILD_ROOT%"
    git clone "%GIT_AICHECKWORD_URL%" aicheckword
    set "RC=!ERRORLEVEL!"
    popd
    if not "!RC!"=="0" ( echo [ERROR] aicheckword clone 失败 & exit /b !RC! )
) else (
    echo.
    echo [aicheckword] fetch --all --tags --prune
    pushd "%BUILD_ROOT%\aicheckword"
    git fetch --all --tags --prune
    set "RC=!ERRORLEVEL!"
    popd
    if not "!RC!"=="0" ( echo [ERROR] aicheckword fetch 失败 & exit /b !RC! )
)

echo [aicheckword] checkout %TAG%
pushd "%BUILD_ROOT%\aicheckword"
git rev-parse -q --verify "refs/tags/%TAG%" >nul
if errorlevel 1 (
    echo [ERROR] aicheckword 仓库不存在 tag %TAG%。请先在开发机运行 release.bat %VER%。
    popd & exit /b 1
)
git checkout -f "%TAG%"
if errorlevel 1 ( echo [ERROR] aicheckword checkout 失败 & popd & exit /b 1 )
git reset --hard "%TAG%"
git clean -fd
popd

rem ----------------------------------------------------------------
rem  调用现有 build-all.bat 完成 build + export + pack
rem ----------------------------------------------------------------
echo.
echo [build] 调用 aiword\deploy\build-all.bat %VER%
pushd "%BUILD_ROOT%\aiword\deploy"
call build-all.bat %VER%
set "RC=!ERRORLEVEL!"
popd
if not "!RC!"=="0" (
    echo [ERROR] build-all.bat 失败，请检查 Docker Desktop 状态、网络与磁盘空间。
    exit /b !RC!
)

echo.
echo ============================================================
echo  SERVER BUILD OK  version=%VER%
echo  部署 zip ：  %BUILD_ROOT%\aiword\deploy\dist\aiword-stack-%VER%.zip
echo  镜像 tar ：  %BUILD_ROOT%\aiword\deploy\dist\aiword-%VER%.tar.gz
echo               %BUILD_ROOT%\aiword\deploy\dist\aicheckword-%VER%.tar.gz
echo ============================================================
echo  下一步：将该 zip scp 到 Linux 生产服务器:/opt/，解压后:
echo      cd /opt/aiword-stack-%VER% ^&^& cp .env.example .env ^&^& vi .env
echo      chmod +x *.sh ^&^& ./server-deploy.sh %VER%
echo ============================================================
exit /b 0
