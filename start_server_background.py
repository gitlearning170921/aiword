"""在后台启动服务器的 Python 脚本（Windows）"""
import subprocess
import sys
import os
from pathlib import Path

def start_server_background():
    """在后台启动 Flask 服务器"""
    script_dir = Path(__file__).parent
    log_file = script_dir / 'server.log'
    pid_file = script_dir / 'server.pid'
    
    print("=" * 50)
    print("文档生成工具 - Web 服务器")
    print("=" * 50)
    print("\n正在后台启动服务器...")
    print(f"访问地址: http://localhost:5000")
    print(f"日志文件: {log_file}")
    print("\n要停止服务器，请运行 stop_server.bat")
    print("=" * 50)
    
    # 在 Windows 上使用 CREATE_NO_WINDOW 标志在后台运行
    if sys.platform == 'win32':
        # 使用 subprocess 在后台启动
        with open(log_file, 'w', encoding='utf-8') as log:
            process = subprocess.Popen(
                [sys.executable, str(script_dir / 'run_web.py')],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
    else:
        # Linux/Mac 使用 nohup
        with open(log_file, 'w', encoding='utf-8') as log:
            process = subprocess.Popen(
                ['nohup', sys.executable, str(script_dir / 'run_web.py')],
                stdout=log,
                stderr=subprocess.STDOUT
            )
    
    pid_file.write_text(str(process.pid), encoding='utf-8')
    print(f"\n服务器已在后台启动！PID: {process.pid}")
    print(f"日志文件: {log_file}")
    print(f"PID 文件: {pid_file}")
    print("\n提示：关闭此窗口不会停止服务器")
    print("要停止服务器，请运行 stop_server.bat")

if __name__ == '__main__':
    start_server_background()

