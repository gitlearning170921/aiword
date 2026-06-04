"""
根据 server.pid 停止后台 Flask 服务器；若 pid 失效则尝试释放 5000 端口。
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

PORT = 5000


def _kill_pid(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                check=False,
                capture_output=True,
                text=True,
            )
            return True
        except Exception as exc:
            print(f"结束进程 {pid} 失败：{exc}")
            return False
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError as exc:
        print(f"结束进程 {pid} 失败：{exc}")
        return False


def stop_server() -> None:
    from startup_util import port_listeners

    script_dir = Path(__file__).parent
    pid_file = script_dir / "server.pid"
    stopped: set[int] = set()

    if pid_file.exists():
        pid_text = pid_file.read_text(encoding="utf-8").strip()
        if pid_text.isdigit():
            pid = int(pid_text)
            if _kill_pid(pid):
                print(f"已终止 server.pid 中的进程 {pid}")
                stopped.add(pid)
        else:
            print("PID 文件格式不正确。")
        pid_file.unlink(missing_ok=True)
    else:
        print("未找到 server.pid，尝试按端口释放…")

    for pid in port_listeners(PORT):
        if pid in stopped:
            continue
        if _kill_pid(pid):
            print(f"已终止占用端口 {PORT} 的进程 {pid}")
            stopped.add(pid)

    if not stopped:
        print(f"未发现运行中的 aiword 服务（端口 {PORT} 空闲）。")


if __name__ == "__main__":
    stop_server()
