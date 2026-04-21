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
echo  提交并推送（容错：无新提交时仍会 push）^|  仓库: %CD%
echo ========================================
for /f %%i in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%i"
if defined CUR_BRANCH echo 当前分支: %CUR_BRANCH%
echo 部署提醒: 须包含 web/static 与 web/templates，详见 DEPLOY_REQUIRED.txt
echo.

echo [1/3] 暂存变更 ^(git add -A^)...
git add -A
if errorlevel 1 (
    echo git add 失败。
    pause
    exit /b 1
)

echo [2/3] 提交 ^(git commit^)...
git commit -m "%msg%"
if errorlevel 1 (
    echo 提交跳过（无变更或提交失败）。继续尝试推送本地已有提交…
)

echo [3/3] 推送 ^(git push^)...
git push
if errorlevel 1 (
    echo 推送失败，请检查网络或远程仓库。
    pause
    exit /b 1
)

echo.
echo 完成: 提交/推送流程已结束。
pause
