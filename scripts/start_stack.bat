@echo off
chcp 65001 >nul
setlocal

REM 本机全栈：aicheckword + aiword + aiprintword（代码在本机跑，库仅 aiword 可分环境）
set "AIWORD_ROOT=%~dp0.."
set "AICHECK_ROOT=%AIWORD_ROOT%\..\aicheckword"
set "AIPRINT_ROOT=%AIWORD_ROOT%\..\aiprintword"

if not exist "%AIWORD_ROOT%\.env" (
    echo [ERROR] 缺少 %AIWORD_ROOT%\.env
    echo [HINT] copy .env.example .env 后配置 FEATURE_ENV_SEPARATION / AIWORD_ENV
    pause
    exit /b 1
)

echo ========================================
echo   本机全栈启动
echo   aicheckword: http://127.0.0.1:8000  （生产库 aicheckword）
echo   aiword:      http://127.0.0.1:5000  （库见 FEATURE_ENV_SEPARATION）
echo   aiprintword: http://127.0.0.1:5050  （生产库 aiprintword_sign）
echo ========================================
echo.

if not exist "%AICHECK_ROOT%\.env" (
    echo [WARN] 缺少 %AICHECK_ROOT%\.env，请先 copy .env.example .env
)
if not exist "%AIPRINT_ROOT%\.env" (
    echo [WARN] 缺少 %AIPRINT_ROOT%\.env，请先 copy .env.example .env
)

start "aicheckword-api" cmd /k "cd /d \"%AICHECK_ROOT%\" && call restart_api.bat --in-window"
timeout /t 4 /nobreak >nul

start "aiword" cmd /k "cd /d \"%AIWORD_ROOT%\" && python run_web.py"
timeout /t 2 /nobreak >nul

start "aiprintword" cmd /k "cd /d \"%AIPRINT_ROOT%\" && call start_server.bat"

echo [INFO] 已在三个窗口启动。仅 aiword 受 FEATURE_ENV_SEPARATION 影响；改 .env 后重启对应窗口。
endlocal
