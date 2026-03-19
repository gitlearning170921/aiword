@echo off
chcp 65001 >nul
setlocal

if "%~1"=="" (
    set "msg=update"
) else (
    set "msg=%~1"
)

echo [1/2] Adding changes...
git add .

echo [2/2] Committing...
git commit -m "%msg%"
if errorlevel 1 (
    rem Usually "no changes to commit". Don't stop, still try pushing.
    echo Commit skipped (no new commit or commit failed). Will still try pushing existing commits...
)

echo Pushing...
git push
if errorlevel 1 (
    echo Push failed. Please check network/remote.
    pause
    exit /b 1
)

echo Submit & push completed.
pause

