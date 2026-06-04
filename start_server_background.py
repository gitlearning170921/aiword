"""在后台启动服务器的 Python 脚本（Windows）"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PORT = 5000


def _tail_log(log_file: Path, max_lines: int = 40) -> str:
    if not log_file.is_file():
        return "(日志文件尚未生成)"
    try:
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return f"(无法读取日志: {exc})"
    if not lines:
        return "(日志为空)"
    return "\n".join(lines[-max_lines:])


def start_server_background() -> int:
    """在后台启动 Flask 服务器；失败时把 server.log 尾部打印到控制台。"""
    from startup_util import ensure_port_available, format_port_conflict_help, port_listeners

    script_dir = Path(__file__).parent
    log_file = script_dir / "server.log"
    pid_file = script_dir / "server.pid"

    listeners = port_listeners(PORT)
    if listeners:
        print(format_port_conflict_help(PORT, listeners))
        print("可先运行 stop_server.bat 关闭旧进程。")
        return 2

    print("=" * 50)
    print("文档生成工具 - Web 服务器")
    print("=" * 50)
    print("\n正在后台启动服务器...")
    print(f"访问地址: http://localhost:{PORT}")
    abs_log = log_file.resolve()
    print("运行日志文件（实时内容写在此文件，非本窗口）:")
    print(f"  {abs_log}")
    print("查看方式：用记事本打开上述路径，或在本机 PowerShell 执行：")
    print(f'  Get-Content -LiteralPath "{abs_log}" -Wait -Tail 50')
    print("若要在本窗口直接看日志，请关闭本服务后运行 start_server_foreground.bat")
    print("\n要停止服务器，请运行 stop_server.bat")
    print("=" * 50)
    print("[aiword] 正在连接数据库并初始化（约 30–60 秒），详情见 server.log …", flush=True)

    ensure_port_available(PORT)

    with open(log_file, "w", encoding="utf-8") as log:
        log.write("[aiword] 后台启动 run_web.py …\n")
        log.flush()
        popen_kwargs = {
            "args": [sys.executable, "-u", str(script_dir / "run_web.py")],
            "stdout": log,
            "stderr": subprocess.STDOUT,
            "cwd": str(script_dir),
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        process = subprocess.Popen(**popen_kwargs)

    pid_file.write_text(str(process.pid), encoding="utf-8")
    print(f"\n子进程已启动，PID: {process.pid}（初始化中，请稍候）")

    deadline = time.time() + 120
    ready_markers = ("Running on http", "Press CTRL+C to quit", "初始化完成")
    while time.time() < deadline:
        if process.poll() is not None:
            print("\n[错误] 服务进程已退出，最近日志：")
            print("-" * 50)
            print(_tail_log(log_file))
            print("-" * 50)
            pid_file.unlink(missing_ok=True)
            return 1
        try:
            text = log_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        if any(m in text for m in ready_markers):
            print(f"\n服务器已在后台启动成功，PID: {process.pid}")
            print(f"运行日志: {abs_log}")
            print("要停止服务器，请运行 stop_server.bat")
            return 0
        time.sleep(2)

    if process.poll() is None:
        print(f"\n服务器仍在初始化（超过 120 秒），PID: {process.pid}")
        print(f"请查看日志: {abs_log}")
        return 0

    print("\n[错误] 服务进程已退出，最近日志：")
    print("-" * 50)
    print(_tail_log(log_file))
    print("-" * 50)
    pid_file.unlink(missing_ok=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(start_server_background())
