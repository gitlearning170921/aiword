"""验证占位符提取的准确性"""
from aiword import extract_placeholders
import sys

# 设置输出编码为UTF-8
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

placeholders = extract_placeholders("template.docx")

print(f"找到 {len(placeholders)} 个占位符：")
print("-" * 60)
for i, p in enumerate(placeholders, 1):
    print(f"{i:2d}. {{{{ {p} }}}}")
print("-" * 60)

# 预期的占位符列表（根据调试输出）
expected = [
    "name",
    "date", 
    "location",
    "产品名称",
    "设备识别码或序列号",
    "预计用途",
    "使用场景",
    "预计用户",
    "功能模块",
    "项目名称",
    "文件版本号",
    "临床应用建议值"
]

print("\n验证结果：")
missing = [p for p in expected if p not in placeholders]
extra = [p for p in placeholders if p not in expected]

if missing:
    print(f"❌ 缺失的占位符: {missing}")
if extra:
    print(f"⚠️  额外识别的占位符: {extra}")
if not missing and not extra:
    print("✅ 所有占位符识别正确！")

