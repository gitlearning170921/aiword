"""测试脚本：分析 template.docx 中的占位符"""
from aiword import extract_placeholders
from pathlib import Path

template_path = "template.docx"

if Path(template_path).exists():
    print(f"正在分析模板文件: {template_path}")
    print("-" * 50)
    
    try:
        placeholders = extract_placeholders(template_path)
        
        if placeholders:
            print(f"找到 {len(placeholders)} 个占位符：")
            for i, placeholder in enumerate(placeholders, 1):
                print(f"  {i}. {{{{ {placeholder} }}}}")
        else:
            print("未找到任何占位符")
            print("\n提示：占位符格式应为 {{占位符名称}}")
        
        print("-" * 50)
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
else:
    print(f"文件不存在: {template_path}")

