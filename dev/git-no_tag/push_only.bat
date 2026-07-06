@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\.."

echo ========================================
echo  [git-no_tag] 仅 git push（不打 tag）
echo  仓库: %CD%
echo ========================================
echo 说明: 不含 add/commit。请先 submit*.bat 或手动 git add。
echo.

git push
if errorlevel 1 ( pause & exit /b 1 )
echo 推送成功。
pause
