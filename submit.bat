@echo off
chcp 65001 >nul
setlocal

if "%~1"=="" (
    set "msg=update"
) else (
    set "msg=%~1"
)

echo 正在提交代码...
git add .
git commit -m "%msg%"
if errorlevel 1 (
    echo 提交失败或没有变更，请检查。
    pause
    exit /b 1
)
git push
if errorlevel 1 (
    echo 推送失败，请检查网络或远程仓库。
    pause
    exit /b 1
)
echo 提交并推送完成。
pause
