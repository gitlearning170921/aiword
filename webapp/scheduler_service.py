# -*- coding: utf-8 -*-
"""
定时任务调度服务。
用于获取下一次自动通知时间（支持传入配置，与 scheduler 使用相同格式）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    CN_TZ = timezone(timedelta(hours=8))

# 星期缩写 -> 0=周一 .. 6=周日（Python weekday）
_DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _parse_schedule(value: str):
    """解析 'thu 16:00' / '15:00' / 'mon,wed,fri 9:30' -> (weekdays or None, hour, minute)。"""
    value = (value or "").strip()
    if not value:
        return None, None, None
    parts = value.split()
    if len(parts) == 1:
        day_part, time_part = None, parts[0]
    elif len(parts) >= 2:
        day_part, time_part = parts[0].lower(), parts[1]
    else:
        return None, None, None
    if ":" not in time_part:
        return None, None, None
    t = time_part.split(":")
    try:
        hour, minute = int(t[0].strip()), int(t[1].strip()) if len(t) > 1 else 0
    except ValueError:
        return None, None, None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None, None, None
    weekdays = None
    if day_part:
        wds = [d.strip() for d in day_part.split(",") if d.strip()]
        weekdays = [_DAY_MAP[d] for d in wds if d in _DAY_MAP]
        if not weekdays:
            weekdays = None
    return weekdays, hour, minute


def get_next_run_times(schedule_config: dict | None = None) -> dict:
    """
    获取各定时任务的下一次执行时间。
    schedule_config 可选，格式：{
      "weekly": "thu 16:00",
      "overdue": "15:00",
      "project": "mon,wed,fri 9:30",
      "moduleCascade": "mon,wed,fri 10:00",
    }。未传或缺少键时使用默认值。
    """
    cfg = schedule_config or {}
    weekly_str = (cfg.get("weekly") or "").strip() or "thu 16:00"
    overdue_str = (cfg.get("overdue") or "").strip() or "15:00"
    project_str = (cfg.get("project") or "").strip() or "mon,wed,fri 9:30"
    try:
        delay_m = int(cfg.get("moduleCascadeDelayMinutes") or cfg.get("module_cascade_delay_minutes") or 5)
        delay_m = max(1, min(1440, delay_m))
    except (TypeError, ValueError):
        delay_m = 5

    now = datetime.now(CN_TZ).replace(tzinfo=None)

    def next_weekday(target_weekday: int, hour: int, minute: int) -> datetime:
        days_ahead = target_weekday - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        next_date = now + timedelta(days=days_ahead)
        next_time = next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_time <= now:
            next_time += timedelta(days=7)
        return next_time

    def next_from_weekdays(weekdays: list, hour: int, minute: int) -> datetime:
        candidates = []
        for wd in weekdays:
            days_ahead = wd - now.weekday()
            if days_ahead < 0:
                days_ahead += 7
            next_date = now + timedelta(days=days_ahead)
            next_time = next_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if next_time <= now:
                next_time += timedelta(days=7)
            candidates.append(next_time)
        return min(candidates) if candidates else now

    def format_cron_weekly(s: str) -> str:
        wd, h, m = _parse_schedule(s)
        if wd is not None and len(wd) == 1:
            names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            return f"每周{names[wd[0]]} {h:02d}:{m:02d}"
        if wd is not None and len(wd) > 1:
            names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            return "每周" + "/".join(names[i] for i in sorted(wd)) + f" {h:02d}:{m:02d}"
        return f"每天 {h:02d}:{m:02d}" if h is not None else s

    def format_cron_overdue(s: str) -> str:
        _, h, m = _parse_schedule(s) if ":" in (s or "") else _parse_schedule("15:00")
        if h is not None:
            return f"截止日期前一天 {h:02d}:{m:02d}"
        return "截止日期前一天 15:00"

    # 每周提醒
    wd_weekly, h_weekly, m_weekly = _parse_schedule(weekly_str)
    if wd_weekly is not None and len(wd_weekly) >= 1 and h_weekly is not None:
        thursday_reminder = next_from_weekdays(wd_weekly, h_weekly, m_weekly)
        cron_weekly = format_cron_weekly(weekly_str)
    else:
        thursday_reminder = next_weekday(3, 16, 0)
        cron_weekly = "每周四 16:00"

    # 逾期：仅显示配置时间
    cron_overdue = format_cron_overdue(overdue_str)

    # 每两天统计
    wd_proj, h_proj, m_proj = _parse_schedule(project_str)
    if wd_proj and h_proj is not None:
        project_stats = next_from_weekdays(wd_proj, h_proj, m_proj)
        cron_project = format_cron_weekly(project_str)
    else:
        project_stats = next_from_weekdays([0, 2, 4], 9, 30)
        cron_project = "每周一/三/五 09:30"

    return {
        "thursdayReminder": {
            "description": "每周任务完成提醒",
            "nextTime": thursday_reminder.strftime("%Y-%m-%d %H:%M"),
            "cron": cron_weekly,
        },
        "overdueReminder": {
            "description": "逾期前一天催告",
            "nextTime": "根据任务截止日期动态计算",
            "cron": cron_overdue,
        },
        "projectStats": {
            "description": "每两天项目完成情况统计",
            "nextTime": project_stats.strftime("%Y-%m-%d %H:%M"),
            "cron": cron_project,
        },
        "moduleCascadeReminder": {
            "description": "模块级联催办（按项目：产品/开发最后一份完成后延迟发送）",
            "nextTime": f"项目完成后 {delay_m} 分钟执行，见下方状态",
            "cron": f"延迟 {delay_m} 分钟",
        },
    }
