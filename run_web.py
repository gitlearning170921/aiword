"""启动 Web 服务器的便捷脚本"""
from app import app

if __name__ == '__main__':
    print("=" * 50)
    print("文档生成工具 - Web 服务器")
    print("=" * 50)
    print("\n服务器正在启动...")
    print("访问地址: http://localhost:5000")
    print("按 Ctrl+C 停止服务器\n")
    print("=" * 50)
    
    # use_reloader=False：后台运行时避免 reloader 杀子进程导致“daemon threads + stderr”崩溃；需热重载可前台运行 python run_web.py
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

