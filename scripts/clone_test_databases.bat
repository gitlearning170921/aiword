@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM 仅克隆 aiword 生产库 -> aiword_test（aicheckword/aiprintword 不分环境）
REM 用法: clone_test_databases.bat mysql-host 3306 root yourpassword

set "HOST=%~1"
set "PORT=%~2"
set "USER=%~3"
set "PASS=%~4"
if "%HOST%"=="" set "HOST=%MYSQL_HOST%"
if "%PORT%"=="" set "PORT=%MYSQL_PORT%"
if "%PORT%"=="" set "PORT=3306"
if "%USER%"=="" set "USER=%MYSQL_USER%"
if "%PASS%"=="" set "PASS=%MYSQL_PASSWORD%"

if "%HOST%"=="" (
    echo [ERROR] 用法: clone_test_databases.bat host port user password
    exit /b 1
)
if "%USER%"=="" (
    echo [ERROR] 请提供 MySQL 用户
    exit /b 1
)

if not "%PASS%"=="" set "MYSQL_PWD=%PASS%"
set "OPTS=-h %HOST% -P %PORT% -u %USER%"

echo ========================================
echo   克隆 aiword -^> aiword_test
echo   主机: %HOST%:%PORT%
echo ========================================
echo [WARN] 将覆盖 aiword_test 中已有数据
pause

call :clone_one aiword aiword_test
exit /b %errorlevel%

:clone_one
set "SRC=%~1"
set "DST=%~2"
echo.
echo [INFO] %SRC% -^> %DST%
mysqldump %OPTS% --single-transaction --routines --triggers "%SRC%" > "%TEMP%\clone_%DST%.sql"
if errorlevel 1 (
    echo [ERROR] mysqldump %SRC% 失败
    exit /b 1
)
mysql %OPTS% -e "CREATE DATABASE IF NOT EXISTS `%DST%` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
mysql %OPTS% "%DST%" < "%TEMP%\clone_%DST%.sql"
if errorlevel 1 (
    echo [ERROR] 导入 %DST% 失败
    exit /b 1
)
del "%TEMP%\clone_%DST%.sql" 2>nul
echo [OK] %DST% 完成
exit /b 0
