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
echo  [git-no_tag] 提交并推送（容错，不打 tag）
echo  仓库: %CD%
echo ========================================
for /f %%i in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%i"
if defined CUR_BRANCH echo 当前分支: %CUR_BRANCH%
echo.

if not exist "web\templates\" ( echo [错误] 缺少 web\templates & pause & exit /b 1 )
if not exist "web\static\" ( echo [错误] 缺少 web\static & pause & exit /b 1 )
if not exist "webapp\templates\" ( echo [错误] 缺少 webapp\templates & pause & exit /b 1 )

echo [1/5] 同步模板...
for %%F in ("web\templates\*.html") do copy /Y "%%F" "webapp\templates\" >nul

echo [2/5] git add 前端...
git add -- web/static web/templates webapp/templates
if errorlevel 1 ( pause & exit /b 1 )

echo [3/5] git add -A
git add -A
if errorlevel 1 ( pause & exit /b 1 )

echo [4/5] git commit -m "%msg%"
git commit -m "%msg%"
if errorlevel 1 echo 无新提交，继续 push...

echo [5/5] git push
git push
if errorlevel 1 ( pause & exit /b 1 )

echo.
echo 完成（未打 tag）。
pause
