# -*- coding: utf-8 -*-
"""
定时任务：每周任务完成提醒、逾期前一日催告、每两天项目完成统计推送到钉钉。
时间在统计页面配置，存入数据库 AppConfig。
"""
from __future__ import annotations

import logging
import os
import re
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    BackgroundScheduler = None
    CronTrigger = None

logger = logging.getLogger(__name__)
scheduler: "BackgroundScheduler | None" = None
_app: "Flask | None" = None


def _get_page2_path(app: "Flask") -> str:
    """在无请求上下文时获取页面2路径，避免 url_for 依赖 SERVER_NAME。"""
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "pages.generate_page":
            return rule.rule
    return "/generate"


def _parse_schedule_time(value: str) -> dict:
    """
    解析 schedule 配置字符串，返回 CronTrigger 可用的 kwargs。
    - "15:00" -> 每天 15:00
    - "thu 16:00" -> 周四 16:00
    - "mon,wed,fri 9:30" -> 周一/三/五 9:30
    """
    value = (value or "").strip()
    if not value:
        return {}
    parts = value.split()
    if len(parts) == 1:
        time_part = parts[0]
        day_of_week = None
    elif len(parts) >= 2:
        day_of_week = parts[0].lower().strip()
        time_part = parts[1].strip()
    else:
        return {}
    if ":" not in time_part:
        return {}
    t = time_part.split(":")
    try:
        hour = int(t[0].strip())
        minute = int(t[1].strip()) if len(t) > 1 else 0
    except ValueError:
        return {}
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return {}
    out = {"hour": hour, "minute": minute}
    if day_of_week:
        out["day_of_week"] = day_of_week
    return out


def _get_schedule_config_from_db():
    """在 app 上下文中从数据库读取自动通知时间配置。返回 dict: weekly, overdue, project。"""
    from .models import AppConfig
    defaults = {
        "SCHEDULE_WEEKLY_REMINDER": "thu 16:00",
        "SCHEDULE_OVERDUE_REMINDER": "15:00",
        "SCHEDULE_PROJECT_STATS": "mon,wed,fri 9:30",
    }
    out = {}
    for key, default in defaults.items():
        row = AppConfig.query.filter_by(config_key=key).first()
        out[key] = (row.config_value.strip() if row and row.config_value else None) or default
    return {
        "weekly": out["SCHEDULE_WEEKLY_REMINDER"],
        "overdue": out["SCHEDULE_OVERDUE_REMINDER"],
        "project": out["SCHEDULE_PROJECT_STATS"],
    }


def _get_webhook_secret():
    """从 current_app（在 app_context 内）或 _app 或环境变量获取钉钉 webhook 与 secret。"""
    app = None
    try:
        from flask import current_app
        app = current_app._get_current_object()
    except RuntimeError:
        app = _app
    if app:
        w = app.config.get("DINGTALK_WEBHOOK") or os.environ.get("DINGTALK_WEBHOOK")
        s = app.config.get("DINGTALK_SECRET") or os.environ.get("DINGTALK_SECRET")
        webhook = (str(w).strip() if w else "") or ""
        secret = (str(s).strip() if s else "") or None
        return webhook, secret
    webhook = (os.environ.get("DINGTALK_WEBHOOK") or "").strip()
    secret = (os.environ.get("DINGTALK_SECRET") or "").strip() or None
    return webhook, secret


def _resolve_mobiles_for_authors(author_names: list) -> list:
    """根据编写人员姓名解析钉钉 @ 用的手机号（从 User 表），与 routes 中逻辑一致。"""
    if not author_names:
        return []
    from . import db
    from .models import User
    mobiles = []
    for name in author_names:
        if not name or not str(name).strip():
            continue
        name = str(name).strip()
        user = User.query.filter(
            db.or_(
                User.username == name,
                User.display_name == name,
            )
        ).first()
        if user and getattr(user, "mobile", None) and str(user.mobile).strip():
            mobiles.append(str(user.mobile).strip())
    return mobiles


def _task_block_md(key, uploads_in_group, project_name: str = None):
    """未完成列表块。若传入 project_name 则块标题只显示影响业务方、产品（与上方「项目：xxx」合并为一条，不重复项目名）。"""
    proj, bs, pr = key
    if project_name is not None:
        header = f"**影响业务方：{bs or '-'}  产品：{pr or '-'}**"
    else:
        header = f"**项目：{proj or '-'}  影响业务方：{bs or '-'}  产品：{pr or '-'}**"
    lines = [header]
    for u in uploads_in_group:
        links = u.get_template_links_list() or []
        link = links[0] if links else None
        due = u.due_date.strftime("%Y-%m-%d") if u.due_date else "-"
        due_red = f'<font color="red">{due}</font>' if due != "-" else "-"
        file_label = u.file_name or "-"
        if u.task_type:
            file_label += f" ({u.task_type})"
        line = f" - 文件名称：{file_label}  截止日期：{due_red}"
        if link:
            line += f"  文档地址：[点击打开]({link})"
        lines.append(line)
    return "\n".join(lines)


def _run_thursday_reminder():
    """每周四 16:00 提醒：统计全部事项（不限于本周），按项目分组展示未完成列表，项目与影响业务方/产品合并为一条显示，并依次 @ 待办人员。"""
    app = _app
    if not app:
        return
    with app.app_context():
        from . import dingtalk_service
        from .models import UploadRecord

        webhook, secret = _get_webhook_secret()
        if not webhook:
            logger.warning("自动催办(周四提醒)：未配置 DINGTALK_WEBHOOK，跳过发送")
            return

        total_count = UploadRecord.query.filter(
            UploadRecord.assignee_name.isnot(None),
        ).count()
        completed_count = UploadRecord.query.filter(
            UploadRecord.task_status == "completed",
            UploadRecord.assignee_name.isnot(None),
        ).count()
        pending_tasks = UploadRecord.query.filter(
            UploadRecord.task_status == "pending",
            UploadRecord.assignee_name.isnot(None),
        ).order_by(UploadRecord.due_date).all()

        if total_count == 0:
            return

        base_url = (app.config.get("BASE_URL") or os.environ.get("BASE_URL") or "").strip().rstrip("/")
        page2_path = _get_page2_path(app)
        page2_url = f"{base_url}{page2_path}" if base_url else ""

        def _group_key(u):
            return (u.project_name or "", u.business_side or "", u.product or "")

        by_project = {}
        all_assignees = set()
        for u in pending_tasks:
            p = u.project_name or ""
            if p not in by_project:
                by_project[p] = []
            by_project[p].append(u)
            name = (u.assignee_name or u.author or "").strip()
            if name:
                all_assignees.add(name)

        lines = [
            "【每周任务完成提醒】",
            "",
            f"全部事项共 {total_count} 项：已完成 {completed_count} 项，未完成 {len(pending_tasks)} 项。",
            "",
        ]

        if not by_project:
            lines.append("当前无未完成任务。")
            if page2_url:
                lines.append("")
                lines.append(f"页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）")
            lines.append("")
            lines.append("## **编写完成后请在页面2中标记完成状态。**")
            lines.append("")
            lines.append("请抓紧处理！")
        else:
            for project_name in sorted(by_project.keys()):
                uploads = by_project[project_name]
                groups = {}
                for u in uploads:
                    k = _group_key(u)
                    groups.setdefault(k, []).append(u)
                lines.append(f"项目：{project_name or '（空）'}")
                lines.append("")
                lines.append(f"未完成任务数：{len(uploads)}")
                lines.append("")
                assignees = list(set(u.assignee_name or u.author for u in uploads if (u.assignee_name or u.author)))
                if assignees:
                    lines.append(f"请以下人员尽快完成：{'、'.join(assignees)}")
                    lines.append("")
                lines.append("")
                task_blocks = []
                for key, grp in sorted(groups.items()):
                    task_blocks.append(_task_block_md(key, grp, project_name=project_name))
                lines.append("\n\n".join(task_blocks))
                lines.append("")
                lines.append("")
            if page2_url:
                lines.append(f"页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）")
                lines.append("")
            lines.append("## **编写完成后请在页面2中标记完成状态。**")
            lines.append("")
            lines.append("请抓紧处理！")

        content = "\n".join(lines)
        at_names = sorted(all_assignees) if all_assignees else None
        at_mobiles = _resolve_mobiles_for_authors(list(all_assignees)) if all_assignees else None
        result = dingtalk_service.send_markdown_message(
            "每周任务完成提醒",
            content,
            at_mobiles=at_mobiles,
            at_names=at_names,
            webhook=webhook,
            secret=secret,
        )
        if not (result and result.get("success")):
            logger.warning("自动催办(周四提醒)：钉钉发送失败，请检查 Webhook/Secret 及网络")


def _run_overdue_reminder():
    """每日 15:00 检查：截止日期为明天的任务，按负责人合并为一条消息发送。返回发送结果供测试接口展示。"""
    app = _app
    if not app:
        return {"no_tasks": False, "sent": 0, "failed": 0, "last_error": "未初始化应用"}
    with app.app_context():
        from . import dingtalk_service
        from .models import UploadRecord, now_local

        webhook, secret = _get_webhook_secret()
        if not webhook:
            logger.warning("自动催办(逾期前一日)：未配置 DINGTALK_WEBHOOK，跳过发送")
            return {"no_tasks": False, "sent": 0, "failed": 0, "last_error": "未配置 DINGTALK_WEBHOOK"}

        tomorrow = (now_local().date() + timedelta(days=1))
        tasks = UploadRecord.query.filter(
            UploadRecord.due_date == tomorrow,
            UploadRecord.task_status == "pending",
            UploadRecord.assignee_name.isnot(None),
        ).order_by(UploadRecord.assignee_name, UploadRecord.due_date).all()

        if not tasks:
            return {"no_tasks": True, "sent": 0, "failed": 0, "last_error": None}

        base_url = (app.config.get("BASE_URL") or os.environ.get("BASE_URL") or "").strip().rstrip("/")
        page2_path = _get_page2_path(app)
        page2_url = f"{base_url}{page2_path}" if base_url else ""

        by_assignee = {}
        for t in tasks:
            name = (t.assignee_name or t.author or "").strip()
            if not name:
                continue
            if name not in by_assignee:
                by_assignee[name] = []
            by_assignee[name].append(t)

        sent = 0
        failed = 0
        last_error = None
        for assignee_name, person_tasks in by_assignee.items():
            if not person_tasks:
                continue
            groups = {}
            for u in person_tasks:
                k = (u.project_name or "", u.business_side or "", u.product or "")
                groups.setdefault(k, []).append(u)
            task_list = "\n\n".join(_task_block_md(k, grp) for k, grp in sorted(groups.items()))
            lines = [
                "【个人任务即将逾期提醒】",
                f"致：{assignee_name}",
                f"您有 {len(person_tasks)} 个任务将于明日截止：",
                "",
                task_list,
                "",
                "请抓紧处理！",
            ]
            if page2_url:
                lines.append("")
                lines.append(f"页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）")
            lines.append("")
            lines.append("## **编写完成后请在页面2中标记完成状态。**")
            content = "\n".join(lines)
            # 打出逾期提醒完整文案，便于核对钉钉关键词与内容
            title = "个人任务即将逾期提醒"
            logger.info("逾期提醒-钉钉消息标题(关键词): %s", title)
            logger.info("逾期提醒-完整文案:\n%s", content)
            at_mobiles = _resolve_mobiles_for_authors([assignee_name])
            result = dingtalk_service.send_markdown_message(
                title,
                content,
                at_mobiles=at_mobiles if at_mobiles else None,
                at_names=[assignee_name],
                webhook=webhook,
                secret=secret,
            )
            if not result.get("success"):
                text_content = content.replace("## **", "").replace("**", "")
                text_content = re.sub(r"\[点击打开\]\((https?://[^)]+)\)", r"\1", text_content)
                text_content = re.sub(r"<font[^>]*>([^<]*)</font>", r"\1", text_content)
                result = dingtalk_service.send_text_message(
                    text_content,
                    at_mobiles=at_mobiles if at_mobiles else None,
                    at_names=[assignee_name],
                    webhook=webhook,
                    secret=secret,
                )
            if result.get("success"):
                sent += 1
            else:
                failed += 1
                last_error = result.get("error") or "未知错误"
                logger.warning("自动催办(逾期前一日)：钉钉发送失败 assignee=%s error=%s", assignee_name, last_error)
        return {"no_tasks": False, "sent": sent, "failed": failed, "last_error": last_error}


def _run_project_stats():
    """每两天 9:30：按项目统计每个人未完成任务项（不显示未完成列表），并依次 @ 待办人员。"""
    app = _app
    if not app:
        return
    with app.app_context():
        from . import dingtalk_service
        from .models import UploadRecord, now_local

        webhook, secret = _get_webhook_secret()
        if not webhook:
            logger.warning("自动催办(项目统计)：未配置 DINGTALK_WEBHOOK，跳过发送")
            return

        base_url = (app.config.get("BASE_URL") or os.environ.get("BASE_URL") or "").strip().rstrip("/")
        page2_path = _get_page2_path(app)
        page2_url = f"{base_url}{page2_path}" if base_url else ""

        pending_tasks = UploadRecord.query.filter(
            UploadRecord.completion_status.is_(None),
        ).order_by(UploadRecord.due_date).all()

        by_project = {}
        all_assignees = set()
        for u in pending_tasks:
            p = u.project_name or ""
            if p not in by_project:
                by_project[p] = []
            by_project[p].append(u)
            name = (u.assignee_name or u.author or "").strip()
            if name:
                all_assignees.add(name)

        if not by_project:
            lines = ["【每两天项目完成情况统计】", "", "当前无未完成任务。"]
            if page2_url:
                lines.append("")
                lines.append(f"页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）")
            lines.append("")
            lines.append("## **编写完成后请在页面2中标记完成状态。**")
            at_names = None
            at_mobiles = None
        else:
            lines = [
                "【每两天项目完成情况统计】",
                "",
                f"整体未完成任务数：{len(pending_tasks)} 项，涉及 {len(by_project)} 个项目。",
                "",
            ]
            for project_name in sorted(by_project.keys()):
                uploads = by_project[project_name]
                by_person = {}
                for u in uploads:
                    name = (u.assignee_name or u.author or "").strip() or "（未指定）"
                    by_person[name] = by_person.get(name, 0) + 1
                person_stats = "、".join(f"{name} {cnt} 项" for name, cnt in sorted(by_person.items()))
                lines.append(f"项目：{project_name or '（空）'}")
                lines.append("")
                lines.append(f"未完成任务（按人统计）：{person_stats}")
                # 只要项目下存在已过期任务就提示；多个过期日期以最后一个（最晚的过期日）为准计算延期天数
                today = now_local().date()
                overdue_dates = [u.due_date for u in uploads if u.due_date and u.due_date < today]
                if overdue_dates:
                    last_overdue = max(overdue_dates)
                    delay_days = (today - last_overdue).days
                    lines.append("")
                    lines.append(f"该项目已**<font color=\"red\">延期{delay_days}天</font>**，请抓紧处理")
                lines.append("")
                lines.append("")
            if page2_url:
                lines.append(f"页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）")
                lines.append("")
            lines.append("## **编写完成后请在页面2中标记完成状态。**")
            at_names = sorted(all_assignees) if all_assignees else None
            at_mobiles = _resolve_mobiles_for_authors(list(all_assignees)) if all_assignees else None
        content = "\n".join(lines)
        result = dingtalk_service.send_markdown_message(
            "每两天项目完成情况统计",
            content,
            at_mobiles=at_mobiles,
            at_names=at_names,
            webhook=webhook,
            secret=secret,
        )
        if not (result and result.get("success")):
            logger.warning("自动催办(项目统计)：钉钉发送失败，请检查 Webhook/Secret 及网络")


def init_scheduler(app: "Flask") -> None:
    """在应用上下文中注册定时任务，时间从数据库 AppConfig 读取。"""
    global scheduler, _app
    _app = app
    if not HAS_APSCHEDULER or scheduler is not None:
        return
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    with app.app_context():
        cfg = _get_schedule_config_from_db()
    weekly = _parse_schedule_time(cfg["weekly"])
    overdue = _parse_schedule_time(cfg["overdue"])
    project = _parse_schedule_time(cfg["project"])

    if not weekly:
        weekly = {"day_of_week": "thu", "hour": 16, "minute": 0}
    if not overdue:
        overdue = {"hour": 15, "minute": 0}
    if not project:
        project = {"day_of_week": "mon,wed,fri", "hour": 9, "minute": 30}

    scheduler.add_job(
        _run_thursday_reminder,
        CronTrigger(**weekly),
        id="thursday_reminder",
    )
    scheduler.add_job(
        _run_overdue_reminder,
        CronTrigger(**overdue),
        id="overdue_reminder",
    )
    scheduler.add_job(
        _run_project_stats,
        CronTrigger(**project),
        id="project_stats",
    )
    scheduler.start()
    logger.info(
        "定时任务已注册：每周提醒 %s，逾期 %s，每两天统计 %s",
        cfg["weekly"],
        cfg["overdue"],
        cfg["project"],
    )


def reschedule_jobs(app: "Flask") -> bool:
    """根据数据库中的配置重新注册三个定时任务（保存配置后调用）。返回是否成功。"""
    global scheduler
    if not HAS_APSCHEDULER or scheduler is None:
        return False
    with app.app_context():
        cfg = _get_schedule_config_from_db()
    weekly = _parse_schedule_time(cfg["weekly"])
    overdue = _parse_schedule_time(cfg["overdue"])
    project = _parse_schedule_time(cfg["project"])
    if not weekly:
        weekly = {"day_of_week": "thu", "hour": 16, "minute": 0}
    if not overdue:
        overdue = {"hour": 15, "minute": 0}
    if not project:
        project = {"day_of_week": "mon,wed,fri", "hour": 9, "minute": 30}
    for jid in ("thursday_reminder", "overdue_reminder", "project_stats"):
        try:
            scheduler.remove_job(jid)
        except Exception:
            pass
    scheduler.add_job(_run_thursday_reminder, CronTrigger(**weekly), id="thursday_reminder")
    scheduler.add_job(_run_overdue_reminder, CronTrigger(**overdue), id="overdue_reminder")
    scheduler.add_job(_run_project_stats, CronTrigger(**project), id="project_stats")
    logger.info("定时任务已更新：每周 %s，逾期 %s，每两天 %s", cfg["weekly"], cfg["overdue"], cfg["project"])
    return True
