@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ========================================
echo  仅推送 ^|  仓库: %CD%
echo ========================================
for /f %%i in ('git branch --show-current 2^>nul') do set "CUR_BRANCH=%%i"
if defined CUR_BRANCH echo 当前分支: %CUR_BRANCH%
echo.

git push
if errorlevel 1 (
    echo 推送失败，请检查网络、凭据或远程分支。
    pause
    exit /b 1
)

echo.
echo 推送成功。
pause
