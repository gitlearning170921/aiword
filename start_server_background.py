"""在后台启动服务器的 Python 脚本（Windows）"""
import subprocess
import sys
from pathlib import Path


def start_server_background():
    """在后台启动 Flask 服务器，脚本退出后服务继续运行；停止请运行 stop_server.bat"""
    script_dir = Path(__file__).parent
    log_file = script_dir / "server.log"
    pid_file = script_dir / "server.pid"

    print("=" * 50)
    print("文档生成工具 - Web 服务器")
    print("=" * 50)
    print("\n正在后台启动服务器...")
    print(f"访问地址: http://localhost:5000")
    abs_log = log_file.resolve()
    print(f"运行日志文件（实时内容写在此文件，非本窗口）:")
    print(f"  {abs_log}")
    print("查看方式：用记事本打开上述路径，或在本机 PowerShell 执行：")
    print(f'  Get-Content -LiteralPath "{abs_log}" -Wait -Tail 50')
    print("若要在本窗口直接看日志，请关闭本服务后运行 start_server_foreground.bat")
    print("\n要停止服务器，请运行 stop_server.bat")
    print("=" * 50)

    if sys.platform == "win32":
        with open(log_file, "w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(script_dir / "run_web.py")],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                cwd=str(script_dir),
            )
    else:
        with open(log_file, "w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, str(script_dir / "run_web.py")],
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(script_dir),
            )

    pid_file.write_text(str(process.pid), encoding="utf-8")
    abs_log = log_file.resolve()
    print(f"\n服务器已在后台启动，PID: {process.pid}")
    print(f"运行日志: {abs_log}")
    print("要停止服务器，请运行 stop_server.bat")


if __name__ == "__main__":
    start_server_background()

