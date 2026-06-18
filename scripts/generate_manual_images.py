"""生成角色操作手册用 PNG 示意图（运行一次即可）。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT, size)
    except OSError:
        return ImageFont.load_default()


def _box(
    draw: ImageDraw.ImageDraw,
    xy,
    title: str,
    lines: list[str],
    fill: str = "#ffffff",
    border: str = "#dee2e6",
    title_fill: str = "#212529",
):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=8, fill=fill, outline=border, width=2)
    draw.text((x1 + 12, y1 + 10), title, fill=title_fill, font=_font(16, True))
    y = y1 + 38
    for line in lines:
        draw.text((x1 + 12, y), line, fill="#495057", font=_font(13))
        y += 22


def save(name: str, img: Image.Image) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    img.save(path, "PNG")
    print(path)


def role_overview() -> None:
    w, h = 960, 360
    img = Image.new("RGB", (w, h), "#f8f9fa")
    d = ImageDraw.Draw(img)
    d.text((w // 2, 18), "三种角色首页（示意）", fill="#212529", font=_font(18, True), anchor="mt")
    panels = [
        (24, 48, 324, 320, "公司管理员", "#0d6efd", ["首页：公司项目总览", "项目管理 · 初稿 · 审核", "（文档工具手动上传）"]),
        (340, 48, 640, 320, "项目管理员", "#198754", ["首页：任务管理", "任务分配 · 统计催办", "初稿生成"]),
        (656, 48, 936, 320, "普通用户", "#fd7e14", ["首页：我的任务", "完成状态 · 执行任务备注", "（本手册仅此两项）"]),
    ]
    for x1, y1, x2, y2, title, color, lines in panels:
        d.rounded_rectangle((x1, y1, x2, y2), radius=8, fill="#fff", outline="#adb5bd", width=2)
        d.rounded_rectangle((x1, y1, x2, y1 + 36), radius=8, fill=color)
        d.rectangle((x1, y1 + 18, x2, y1 + 36), fill=color)
        d.text(((x1 + x2) // 2, y1 + 18), title, fill="#fff", font=_font(14, True), anchor="mm")
        y = y1 + 56
        for line in lines:
            d.text((x1 + 14, y), line, fill="#495057", font=_font(13))
            y += 26
    save("manual-role-overview.png", img)


def company_projects() -> None:
    w, h = 900, 420
    img = Image.new("RGB", (w, h), "#f8f9fa")
    d = ImageDraw.Draw(img)
    d.text((w // 2, 16), "公司项目总览 · 项目管理", fill="#212529", font=_font(18, True), anchor="mt")
    _box(d, (24, 48, 876, 110), "顶部", ["公司项目总览 · 当前可见范围（注册国家）"])
    _box(
        d,
        (24, 126, 876, 220),
        "全公司项目列表",
        ["[ 登记新项目 ]  [ 批量编辑 ]  [ 筛选 ]", "项目名称 | 注册国家 | 注册类别 | 项目组 | 操作", "关联任务项目 · 编辑 · 移出总览"],
        fill="#eef6ff",
        border="#0d6efd",
    )
    _box(
        d,
        (24, 236, 876, 320),
        "登记 / 编辑项目弹窗",
        ["项目名称 * · 注册国家 · 注册类别 · 分配给项目组", "保存后项目管理员可在任务管理中同步使用"],
    )
    save("manual-company-projects.png", img)


def company_doc_tools() -> None:
    w, h = 900, 220
    img = Image.new("RGB", (w, h), "#f8f9fa")
    d = ImageDraw.Draw(img)
    d.text((w // 2, 16), "公司项目总览 · 文档工具", fill="#212529", font=_font(18, True), anchor="mt")
    _box(
        d,
        (24, 48, 876, 180),
        "文档工具（手动上传，不带任务列表）",
        ["[ 初稿生成 ]    [ 文档审核 ]", "适用于公司层自检稿件，不从任务带入文件"],
        fill="#eef6ff",
        border="#0d6efd",
    )
    save("manual-company-doc-tools.png", img)


def audit_page() -> None:
    w, h = 900, 400
    img = Image.new("RGB", (w, h), "#f8f9fa")
    d = ImageDraw.Draw(img)
    d.text((w // 2, 16), "文档审核页（仅手动上传）", fill="#212529", font=_font(18, True), anchor="mt")
    _box(d, (24, 48, 876, 130), "来源", ["选择文件…（可多次追加 / 支持 zip）", "须自行上传；不从任务列表 / 我的任务带入"])
    _box(d, (24, 146, 876, 240), "审核设置", ["审核模式 ▼ · 所属公司 ▼ · 项目 ▼（必选）", "注册国家/类型 · 自动匹配过往项目案例"])
    d.rounded_rectangle((24, 256, 876, 304), radius=8, fill="#0dcaf0")
    d.text((450, 280), "提交审核", fill="#fff", font=_font(16, True), anchor="mm")
    _box(d, (24, 320, 876, 384), "结果", ["进度条 · 审核结果 · 下载报告 ZIP · 我的审核历史"])
    save("manual-audit-page.png", img)


def draft_page() -> None:
    w, h = 900, 440
    img = Image.new("RGB", (w, h), "#f8f9fa")
    d = ImageDraw.Draw(img)
    d.text((w // 2, 16), "初稿生成页（仅手动上传）", fill="#212529", font=_font(18, True), anchor="mt")
    _box(d, (24, 48, 876, 120), "个人 LLM 设置（可选）", ["API Key · 保存 · 测试 Key（与审核共用）"])
    _box(
        d,
        (24, 136, 876, 250),
        "生成设置",
        ["所属公司 ▼ · 刷新列表", "选择模板项目案例 ▼ · 勾选要生成的文件名", "生成语言 · 生成策略 · 选择已有项目 ▼"],
        fill="#eef6ff",
        border="#0d6efd",
    )
    _box(d, (24, 266, 876, 330), "上传文件", ["输入/参考文件（必填）· Base 基础文件（可选）· 自定义提示", "须在本页自行上传；不含从任务带入"])
    d.rounded_rectangle((24, 346, 876, 394), radius=8, fill="#0d6efd")
    d.text((450, 370), "提交生成 → 下载 ZIP", fill="#fff", font=_font(16, True), anchor="mm")
    save("manual-draft-page.png", img)


def project_tasks() -> None:
    w, h = 900, 430
    img = Image.new("RGB", (w, h), "#f8f9fa")
    d = ImageDraw.Draw(img)
    d.text((w // 2, 16), "任务管理 · 项目任务分配", fill="#212529", font=_font(18, True), anchor="mt")
    d.text((w // 2, 36), "（不含占位符识别与占位符填写）", fill="#6c757d", font=_font(12), anchor="mt")
    _box(d, (24, 52, 876, 114), "文档工具", ["[ 初稿生成 ]（手动上传，不从任务带入）"])
    _box(
        d,
        (24, 130, 876, 234),
        "任务录入区",
        ["项目名称 ▼ · 文件名称 · 任务类型 · 编写人员 ▼ · 截止日期", "[+ 添加任务行]  [+ 添加项目块]  [ 保存全部 ]"],
        fill="#e8f5e9",
        border="#198754",
    )
    _box(
        d,
        (24, 250, 876, 404),
        "已保存任务列表",
        ["筛选 · 按项目选择 · 批量编辑", "操作列：[ 编辑 ] [ 删除 ]"],
    )
    save("manual-project-tasks.png", img)


def dashboard_notify() -> None:
    w, h = 900, 480
    img = Image.new("RGB", (w, h), "#f8f9fa")
    d = ImageDraw.Draw(img)
    d.text((w // 2, 16), "统计面板 · 统计与催办", fill="#212529", font=_font(18, True), anchor="mt")
    _box(d, (24, 48, 876, 130), "整体完成率 · 下一次自动通知时间", ["查看定时催办计划（周四提醒 / 逾期前一日 / 项目统计）"])
    _box(
        d,
        (24, 146, 876, 280),
        "按项目 / 按编写人员 / 按项目+编写人员",
        ["完成 · 未完成 · 完成率 · 状态分布", "[ 催办 ] 按钮：按项目 / 按人员 / 按项目+人员 / 单条任务"],
        fill="#fff8e1",
        border="#ffc107",
    )
    _box(
        d,
        (24, 296, 876, 450),
        "催办 · 按项目组钉钉（页面底部）",
        [
            "① 钉钉群：群设置 → 智能群助手 → 自定义机器人 → 复制 Webhook",
            "② 安全设置：自定义关键词或 IP（不配置加签/Secret）",
            "③ 统计页底部：项目组 ▼ · Webhook · [ 保存 ]（Secret 留空）",
            "④ 留空 Webhook 时使用系统全局催办机器人（系统管理员配置）",
        ],
        fill="#e7f5ff",
        border="#0d6efd",
    )
    save("manual-dashboard-notify.png", img)


def user_tasks() -> None:
    w, h = 900, 380
    img = Image.new("RGB", (w, h), "#f8f9fa")
    d = ImageDraw.Draw(img)
    d.text((w // 2, 16), "我的任务 · 完成状态与备注", fill="#212529", font=_font(18, True), anchor="mt")
    _box(
        d,
        (24, 48, 876, 340),
        "我的任务列表（仅本人）",
        [
            "列：项目 | 文件名称 | 任务类型 | 执行任务备注 | 完成状态",
            "执行任务备注：失焦自动保存；事项型任务须填写有效完成情况",
            "完成状态下拉：选择「已完成初稿」等（须先有模板/链接）",
            "事项型任务：须先填执行任务备注，再改完成状态",
            "文档链接：可在列表中填写 http/https 链接后保存",
        ],
        fill="#fff3e0",
        border="#fd7e14",
    )
    save("manual-user-tasks.png", img)


def main() -> None:
    role_overview()
    company_projects()
    company_doc_tools()
    audit_page()
    draft_page()
    project_tasks()
    dashboard_notify()
    user_tasks()
    print("done")


if __name__ == "__main__":
    main()
