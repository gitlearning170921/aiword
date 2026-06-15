@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

rem ============================================================
rem  release.bat  ：一键发布 aiword + aicheckword 双仓库
rem  用法： release.bat <version> [commit-msg]
rem    示例： release.bat 1.0.2
rem           release.bat 1.0.2 "fix audit pagination"
rem  行为：
rem    1) aiword 仓库（当前目录）   : 同步前端 → add/commit → push → 打 tag v<ver> → push tag
rem    2) aicheckword 仓库（同级）  : add/commit → push → 打 tag v<ver> → push tag
rem  无新提交也会继续打 tag 并推送，确保打包服务器能按同名 tag 拉到。
rem  aiprintword 不在打包链中，需要时请单独运行该仓库的 commit_push.bat。
rem ============================================================

if "%~1"=="" (
    echo Usage: release.bat ^<version^> [commit-msg]
    echo   e.g.  release.bat 1.0.2
    echo         release.bat 1.0.2 "fix audit pagination"
    exit /b 1
)
set "VER=%~1"
set "TAG=v%VER%"
if "%~2"=="" (
    set "MSG=release %TAG%"
) else (
    set "MSG=%~2"
)

set "AIWORD_DIR=%~dp0"
for %%I in ("%AIWORD_DIR%\..") do set "PARENT_DIR=%%~fI"
set "AICHECKWORD_DIR=%PARENT_DIR%\aicheckword"

echo ============================================================
echo  发布 %TAG%   commit-msg=%MSG%
echo  aiword     : %AIWORD_DIR%
echo  aicheckword: %AICHECKWORD_DIR%
echo ============================================================

where git >nul 2>&1
if errorlevel 1 (
    echo [ERROR] git not found in PATH.
    pause & exit /b 1
)

if not exist "%AICHECKWORD_DIR%\.git" (
    echo [ERROR] 找不到 aicheckword 仓库: %AICHECKWORD_DIR%
    echo         请确保 aiword 与 aicheckword 同级。
    pause & exit /b 1
)

rem ----------------------------------------------------------------
rem  aiword 仓库
rem ----------------------------------------------------------------
echo.
echo [aiword 1/5] 同步前端模板: web\templates\*.html -^> webapp\templates\
if exist "%AIWORD_DIR%web\templates\" if exist "%AIWORD_DIR%webapp\templates\" (
    for %%F in ("%AIWORD_DIR%web\templates\*.html") do copy /Y "%%F" "%AIWORD_DIR%webapp\templates\" >nul
) else (
    echo       (跳过：缺少 web\templates 或 webapp\templates 目录)
)

pushd "%AIWORD_DIR%"
echo [aiword 2/5] git add
git add -- web/static web/templates webapp/templates 2>nul
git add -A
if errorlevel 1 ( echo [ERROR] aiword git add 失败 & popd & pause & exit /b 1 )

echo [aiword 3/5] git commit -m "%MSG%"
git commit -m "%MSG%"
if errorlevel 1 (
    echo [INFO] aiword 无新提交，继续走 push + tag 流程。
)

echo [aiword 4/5] git push
git push
if errorlevel 1 ( echo [ERROR] aiword push 失败 & popd & pause & exit /b 1 )

echo [aiword 5/5] tag %TAG%
git rev-parse -q --verify "refs/tags/%TAG%" >nul
if not errorlevel 1 (
    echo [INFO] aiword 本地已有 tag %TAG%，跳过创建，直接 push tag。
) else (
    git tag -a "%TAG%" -m "release %TAG%"
    if errorlevel 1 ( echo [ERROR] aiword 打 tag 失败 & popd & pause & exit /b 1 )
)
git push origin "%TAG%"
if errorlevel 1 (
    echo [ERROR] aiword push tag %TAG% 失败 ^(可能远程已存在同名 tag^)。
    echo         如要强制覆盖，请手动: git push -f origin %TAG%
    popd & pause & exit /b 1
)
popd

rem ----------------------------------------------------------------
rem  aicheckword 仓库
rem ----------------------------------------------------------------
echo.
pushd "%AICHECKWORD_DIR%"
echo [aicheckword 1/4] git add
git add -A
if errorlevel 1 ( echo [ERROR] aicheckword git add 失败 & popd & pause & exit /b 1 )

echo [aicheckword 2/4] git commit -m "%MSG%"
git commit -m "%MSG%"
if errorlevel 1 (
    echo [INFO] aicheckword 无新提交，继续走 push + tag 流程。
)

echo [aicheckword 3/4] git push
git push
if errorlevel 1 ( echo [ERROR] aicheckword push 失败 & popd & pause & exit /b 1 )

echo [aicheckword 4/4] tag %TAG%
git rev-parse -q --verify "refs/tags/%TAG%" >nul
if not errorlevel 1 (
    echo [INFO] aicheckword 本地已有 tag %TAG%，跳过创建。
) else (
    git tag -a "%TAG%" -m "release %TAG%"
    if errorlevel 1 ( echo [ERROR] aicheckword 打 tag 失败 & popd & pause & exit /b 1 )
)
git push origin "%TAG%"
if errorlevel 1 (
    echo [ERROR] aicheckword push tag %TAG% 失败 ^(可能远程已存在同名 tag^)。
    popd & pause & exit /b 1
)
popd

echo.
echo ============================================================
echo  完成: 双仓库代码已 push，并打了同名 tag %TAG%。
echo  下一步：到打包服务器执行：
echo      cd ^<BUILD_ROOT^>\aiword\deploy
echo      server-build-from-git.bat %VER%
echo ============================================================
pause
endlocal
