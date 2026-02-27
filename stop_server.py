"""
根据 server.pid 中记录的 PID 停止后台 Flask 服务器。
"""
from __future__ import annotations

import os
import signal
from pathlib import Path


def stop_server():
    script_dir = Path(__file__).parent
    pid_file = script_dir / "server.pid"

    if not pid_file.exists():
        print("未找到 server.pid，服务器可能未启动。")
        return

    pid_text = pid_file.read_text(encoding="utf-8").strip()
    if not pid_text.isdigit():
        print("PID 文件格式不正确，无法停止服务器。")
        return

    pid = int(pid_text)
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"已发送终止信号到进程 {pid}")
    except OSError as exc:
        print(f"结束进程失败：{exc}")
    finally:
        pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    stop_server()




