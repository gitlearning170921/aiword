@echo off
cd /d %~dp0
echo [提示] 本脚本为后台启动：Python 日志写入项目目录下的 server.log，不会出现在本窗口。
echo [提示] 若要在当前窗口看实时日志，请改用 start_server_foreground.bat
echo.
python start_server_background.py
if errorlevel 1 (
  echo.
  echo [失败] 后台启动未成功，请查看上方输出或 server.log
)
pause




