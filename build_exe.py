"""
打包脚本：将 aiword.py 打包成 exe 文件
使用方法：python build_exe.py
"""
import subprocess
import sys
import os

def build_exe():
    """使用 PyInstaller 打包程序"""
    print("开始打包程序...")
    
    # PyInstaller 命令参数
    cmd = [
        "pyinstaller",
        "--name=文档生成工具",  # exe 文件名
        "--onefile",  # 打包成单个文件
        "--windowed",  # 不显示控制台窗口（GUI 程序）
        "--icon=NONE",  # 可以指定图标文件路径，如 "icon.ico"
        "--add-data=README.md;." if os.path.exists("README.md") else "",  # 如果有其他文件需要打包
        "aiword.py"
    ]
    
    # 移除空字符串
    cmd = [c for c in cmd if c]
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='ignore')
        print("打包成功！")
        print(f"exe 文件位置: dist/文档生成工具.exe")
        print("\n提示：")
        print("1. 首次打包可能需要较长时间，请耐心等待")
        print("2. 打包完成后，exe 文件在 dist 文件夹中")
        print("3. 可以将 exe 文件复制到任何位置使用")
    except subprocess.CalledProcessError as e:
        print(f"打包失败: {e}")
        print("\n请确保已安装 PyInstaller:")
        print("pip install pyinstaller")
        sys.exit(1)
    except FileNotFoundError:
        print("错误: 未找到 PyInstaller")
        print("\n请先安装 PyInstaller:")
        print("pip install pyinstaller")
        sys.exit(1)

if __name__ == "__main__":
    build_exe()

