@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    set "msg=update"
) else (
    set "msg=%~1"
)

echo ========================================
echo  提交并推送（严格：无新提交则中止，不 push）^|  仓库: %CD%
echo ========================================
for /f %%i in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%i"
if defined CUR_BRANCH echo 当前分支: %CUR_BRANCH%
echo 流程含: 同步前端模板 → 显式 git add 前端目录 → 全仓暂存 → 提交 → 推送
echo 详见: DEPLOY_REQUIRED.txt
echo.

if not exist "web\templates\" (
    echo [错误] 缺少目录 web\templates，无法同步前端。
    pause
    exit /b 1
)
if not exist "web\static\" (
    echo [错误] 缺少目录 web\static。
    pause
    exit /b 1
)
if not exist "webapp\templates\" (
    echo [错误] 缺少目录 webapp\templates。
    pause
    exit /b 1
)

echo [1/5] 同步前端模板: web\templates\*.html → webapp\templates\
for %%F in ("web\templates\*.html") do copy /Y "%%F" "webapp\templates\" >nul
echo       已复制 HTML 模板到 webapp\templates（与 web 保持一致，便于部署只带 webapp 时也不缺页）。

echo [2/5] 暂存前端: git add -- web/static web/templates webapp/templates
git add -- web/static web/templates webapp/templates
if errorlevel 1 (
    echo git add（前端路径）失败。
    pause
    exit /b 1
)

echo [3/5] 暂存其余变更: git add -A
git add -A
if errorlevel 1 (
    echo git add -A 失败。
    pause
    exit /b 1
)

echo [4/5] 提交: git commit -m "%msg%"
git commit -m "%msg%"
if errorlevel 1 (
    echo 提交失败或无变更可提交。若本地已有未推送提交，请改用 submit_push_retry.bat 或先解决后再推送。
    pause
    exit /b 1
)

echo [5/5] 推送: git push
git push
if errorlevel 1 (
    echo 推送失败，请检查网络、凭据或远程分支。
    pause
    exit /b 1
)

echo.
echo 完成: 已提交并推送（含前端 web/ 与 webapp/templates 同步）。
pause
