@echo off
chcp 65001 >nul
setlocal
echo ========================================
echo   停止 Windows 测试全栈 (5000/8000/5050)
echo ========================================
echo.

for %%P in (8000 5000 5050) do (
    echo [INFO] 检查端口 %%P ...
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        taskkill /F /PID %%a >nul 2>&1 && echo [OK] 已停止 PID %%a （端口 %%P）
    )
)

echo.
echo [INFO] 完成。若仍有残留窗口，请手动关闭标题含 test 的 cmd 窗口。
endlocal
pause
