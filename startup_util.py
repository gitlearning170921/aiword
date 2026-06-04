# -*- coding: utf-8 -*-
"""启动辅助：端口占用自检、控制台进度提示（独立于 webapp 包，避免 import 时触发 create_app）。"""
from __future__ import annotations

import os
import sys
from typing import Iterable


def startup_quiet() -> bool:
    return os.environ.get("AIWORD_QUIET_STARTUP", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def startup_note(message: str) -> None:
    if startup_quiet():
        return
    print(f"[aiword] {message}", file=sys.stderr, flush=True)


def port_listeners(port: int) -> list[int]:
    """返回监听指定 TCP 端口的进程 PID 列表（Windows / Linux）。"""
    pids: list[int] = []
    if sys.platform == "win32":
        import subprocess

        try:
            out = subprocess.check_output(
                ["netstat", "-ano"],
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            return pids
        needle = f":{int(port)}"
        for line in out.splitlines():
            if "LISTENING" not in line.upper():
                continue
            if needle not in line:
                continue
            parts = line.split()
            if not parts:
                continue
            pid_txt = parts[-1].strip()
            if pid_txt.isdigit():
                pid = int(pid_txt)
                if pid not in pids:
                    pids.append(pid)
        return pids

    try:
        import subprocess

        out = subprocess.check_output(
            ["ss", "-ltnp"],
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        out = ""
    if not out:
        try:
            import subprocess

            out = subprocess.check_output(
                ["lsof", "-i", f":{int(port)}", "-sTCP:LISTEN", "-t"],
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
            return pids
        except Exception:
            return pids
    needle = f":{int(port)}"
    for line in out.splitlines():
        if needle not in line:
            continue
        if "pid=" not in line:
            continue
        for chunk in line.split(","):
            chunk = chunk.strip()
            if chunk.startswith("pid="):
                pid_txt = chunk[4:].split(",", 1)[0].strip()
                if pid_txt.isdigit():
                    pid = int(pid_txt)
                    if pid not in pids:
                        pids.append(pid)
    return pids


def ensure_port_available(port: int, *, own_pid: int | None = None) -> None:
    """端口已被占用时打印排查命令并退出（非 0）。"""
    own = own_pid if own_pid is not None else os.getpid()
    listeners = [p for p in port_listeners(port) if p != own]
    if not listeners:
        return
    startup_note(f"端口 {port} 已被占用，PID: {', '.join(str(p) for p in listeners)}")
    if sys.platform == "win32":
        startup_note(f"排查: netstat -ano | findstr :{port}")
        startup_note(f"关闭: taskkill /PID <PID> /F")
    else:
        startup_note(f"排查: lsof -i :{port} 或 ss -ltnp | grep {port}")
        startup_note("关闭: kill <PID>")
    startup_note("请只保留一个 aiword 服务进程后再启动。")
    raise SystemExit(2)


def format_port_conflict_help(port: int, pids: Iterable[int]) -> str:
    pid_list = ", ".join(str(p) for p in pids)
    if sys.platform == "win32":
        return (
            f"端口 {port} 已被占用（PID: {pid_list}）。"
            f"请先运行 stop_server.bat，或执行 taskkill /PID <PID> /F"
        )
    return f"端口 {port} 已被占用（PID: {pid_list}）。请先结束旧进程后再启动。"
