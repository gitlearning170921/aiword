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
    
    app.run(host='0.0.0.0', port=5000, debug=True)

