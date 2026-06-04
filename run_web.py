"""启动 Web 服务器的便捷脚本"""
from __future__ import annotations

PORT = 5000


def main() -> None:
    from startup_util import ensure_port_available, startup_note

    print("=" * 50, flush=True)
    print("文档生成工具 - Web 服务器", flush=True)
    print("=" * 50, flush=True)
    print("\n服务器正在启动...", flush=True)
    print(f"访问地址: http://localhost:{PORT}", flush=True)
    print("按 Ctrl+C 停止服务器\n", flush=True)
    print("实时日志（INFO）输出在本窗口；更详细可设置环境变量 AIWORD_LOG_LEVEL=DEBUG", flush=True)
    print("关闭控制台日志：AIWORD_CONSOLE_LOG=0", flush=True)
    print("=" * 50, flush=True)

    ensure_port_available(PORT)
    startup_note("正在连接数据库并初始化（首次约 30–60 秒，请稍候）…")

    from app import app

    startup_note("初始化完成，正在监听 HTTP 请求…")
    # use_reloader=False：后台运行时避免 reloader 杀子进程导致“daemon threads + stderr”崩溃
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)


if __name__ == "__main__":
    main()
