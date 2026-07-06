@echo off
chcp 65001 >nul 2>&1
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0..\.."

:: [git-tag_release] 发版：aiword + aicheckword 双仓库 push + 同名 tag v版本

if "%~1"=="" (
    echo.
    echo Usage: release.bat ^<version^> [commit-msg]
    echo   e.g. release.bat 1.0.5
    echo        release.bat 1.0.5 "fix audit pagination"
    echo.
    echo 日常开发（不打 tag）请用: dev\git-no_tag\submit.bat
    exit /b 1
)
set "VER=%~1"
set "TAG=v%VER%"
if "%~2"=="" (
    set "MSG=release %TAG%"
) else (
    set "MSG=%~2"
)

set "AIWORD_DIR=%~dp0..\..\"
for %%I in ("%AIWORD_DIR%\..") do set "PARENT_DIR=%%~fI"
set "AICHECKWORD_DIR=%PARENT_DIR%\aicheckword"

echo ============================================================
echo  [git-tag_release] 发版 %TAG%
echo  commit-msg=%MSG%
echo  aiword     : %AIWORD_DIR%
echo  aicheckword: %AICHECKWORD_DIR%
echo ============================================================

where git >nul 2>&1
if errorlevel 1 ( echo [ERROR] git not found & pause & exit /b 1 )

if not exist "%AICHECKWORD_DIR%\.git" (
    echo [ERROR] 找不到 aicheckword: %AICHECKWORD_DIR%
    echo         aiword 与 aicheckword 须同级目录。
    pause & exit /b 1
)

echo.
echo [aiword 1/5] 同步 web\templates -^> webapp\templates
if exist "%AIWORD_DIR%web\templates\" if exist "%AIWORD_DIR%webapp\templates\" (
    for %%F in ("%AIWORD_DIR%web\templates\*.html") do copy /Y "%%F" "%AIWORD_DIR%webapp\templates\" >nul
)

pushd "%AIWORD_DIR%"
echo [aiword 2/5] git add
git add -- web/static web/templates webapp/templates 2>nul
git add -A
if errorlevel 1 ( echo [ERROR] aiword git add 失败 & popd & pause & exit /b 1 )

echo [aiword 3/5] git commit -m "%MSG%"
git commit -m "%MSG%"
if errorlevel 1 echo [INFO] aiword 无新提交，继续 push + tag

echo [aiword 4/5] git push
git push
if errorlevel 1 ( echo [ERROR] aiword push 失败 & popd & pause & exit /b 1 )

echo [aiword 5/5] tag %TAG%
git rev-parse -q --verify "refs/tags/%TAG%" >nul
if not errorlevel 1 (
    echo [INFO] 本地已有 tag %TAG%，跳过创建
) else (
    git tag -a "%TAG%" -m "release %TAG%"
    if errorlevel 1 ( echo [ERROR] 打 tag 失败 & popd & pause & exit /b 1 )
)
git push origin "%TAG%"
if errorlevel 1 (
    echo [ERROR] push tag 失败（远程可能已有同名 tag）
    popd & pause & exit /b 1
)
popd

echo.
pushd "%AICHECKWORD_DIR%"
echo [aicheckword 1/4] git add
git add -A
if errorlevel 1 ( echo [ERROR] aicheckword git add 失败 & popd & pause & exit /b 1 )

echo [aicheckword 2/4] git commit -m "%MSG%"
git commit -m "%MSG%"
if errorlevel 1 echo [INFO] aicheckword 无新提交，继续 push + tag

echo [aicheckword 3/4] git push
git push
if errorlevel 1 ( echo [ERROR] aicheckword push 失败 & popd & pause & exit /b 1 )

echo [aicheckword 4/4] tag %TAG%
git rev-parse -q --verify "refs/tags/%TAG%" >nul
if not errorlevel 1 (
    echo [INFO] 本地已有 tag %TAG%，跳过创建
) else (
    git tag -a "%TAG%" -m "release %TAG%"
    if errorlevel 1 ( echo [ERROR] 打 tag 失败 & popd & pause & exit /b 1 )
)
git push origin "%TAG%"
if errorlevel 1 ( echo [ERROR] push tag 失败 & popd & pause & exit /b 1 )
popd

echo.
echo ============================================================
echo  完成: 双仓库已 push，tag=%TAG%
echo.
echo  下一步 - 打包机:
echo    cd /d d:\aicode
echo    git_clone_repo_aiword.bat %VER% build
echo.
echo  或仅拉代码:
echo    git_clone_repo_aiword.bat %VER%
echo ============================================================
pause
endlocal
