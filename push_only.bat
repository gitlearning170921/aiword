@echo off
chcp 65001 >nul

echo Pushing...
git push
if errorlevel 1 (
    echo Push failed. Please check network/remote.
    pause
    exit /b 1
)

echo Push OK.
pause

