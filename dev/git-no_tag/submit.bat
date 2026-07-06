@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

if "%~1"=="" (
    set "msg=update"
) else (
    set "msg=%~1"
)

echo ========================================
echo  [git-no_tag] 日常提交并推送（不打 tag）
echo  仓库: %CD%
echo ========================================
for /f %%i in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%i"
if defined CUR_BRANCH echo 当前分支: %CUR_BRANCH%
echo 流程: 同步前端模板 -^> git add -^> commit -^> push（无新提交则中止）
echo 发版请改用: dev\git-tag_release\release.bat
echo.

if not exist "web\templates\" (
    echo [错误] 缺少目录 web\templates
    pause & exit /b 1
)
if not exist "web\static\" (
    echo [错误] 缺少目录 web\static
    pause & exit /b 1
)
if not exist "webapp\templates\" (
    echo [错误] 缺少目录 webapp\templates
    pause & exit /b 1
)

echo [1/5] 同步: web\templates\*.html -^> webapp\templates\
for %%F in ("web\templates\*.html") do copy /Y "%%F" "webapp\templates\" >nul

echo [2/5] git add -- web/static web/templates webapp/templates
git add -- web/static web/templates webapp/templates
if errorlevel 1 ( pause & exit /b 1 )

echo [3/5] git add -A
git add -A
if errorlevel 1 ( pause & exit /b 1 )

echo [4/5] git commit -m "%msg%"
git commit -m "%msg%"
if errorlevel 1 (
    echo 无新提交。若需推送已有提交，请用 dev\git-no_tag\submit_push_retry.bat
    pause & exit /b 1
)

echo [5/5] git push
git push
if errorlevel 1 ( pause & exit /b 1 )

echo.
echo 完成（未打 tag）。
pause
