# -*- coding: utf-8 -*-
"""
定时任务：每周任务完成提醒、逾期前一日催告、每两天项目完成统计推送到钉钉。
时间在统计页面配置，存入数据库 AppConfig。
"""
from __future__ import annotations

import atexit
import hashlib
import logging
import os
import threading
import time
from collections import defaultdict
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    BackgroundScheduler = None
    CronTrigger = None
    IntervalTrigger = None

logger = logging.getLogger(__name__)
scheduler: "BackgroundScheduler | None" = None
_app: "Flask | None" = None
_shutdown_registered = False
_cron_mysql_lock_tls = threading.local()


def _scheduler_instance_branch() -> str:
    """
    定时钉钉互斥/去重用的「部署分支」标识，来自页面4 系统配置 SCHEDULER_INSTANCE_ID。
    - 留空：与历史一致，共库时同 job 同分钟全库只发一条（多 worker / 多机 HA 去重）。
    - 各套部署填不同值：共库时各套各发一条钉钉。
    """
    app = _app
    if not app:
        return ""
    try:
        from .app_settings import get_setting_for_scheduler

        raw = (get_setting_for_scheduler("SCHEDULER_INSTANCE_ID", default="", app=app) or "").strip()
    except Exception:
        return ""
    if not raw:
        return ""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _send_lock_file_basename(job_id: str) -> str:
    """本地 scheduler_locks 文件名：有实例分支时与兄弟部署区分，避免同机同路径抢同一把文件锁。"""
    br = _scheduler_instance_branch()
    jid = (job_id or "").strip()
    return f"{jid}_{br}" if br else jid


def shutdown_scheduler() -> None:
    """进程退出前关闭调度器，避免后台线程在解释器关闭时访问 stderr 导致 Fatal Python error。"""
    global scheduler, _shutdown_registered
    if scheduler is None:
        return
    try:
        scheduler.shutdown(wait=True)
        logger.info("定时任务调度器已关闭")
    except Exception as e:
        logger.warning("关闭调度器时异常: %s", e)
    finally:
        scheduler = None
        _shutdown_registered = False


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
    """在 app 上下文中从数据库读取自动通知时间配置。返回 dict: weekly, overdue, project, module_cascade_delay_minutes。"""
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
    delay_row = AppConfig.query.filter_by(config_key="MODULE_CASCADE_DELAY_MINUTES").first()
    delay_minutes = 5
    if delay_row and delay_row.config_value:
        try:
            delay_minutes = max(1, min(1440, int(str(delay_row.config_value).strip())))
        except ValueError:
            pass
    return {
        "weekly": out["SCHEDULE_WEEKLY_REMINDER"],
        "overdue": out["SCHEDULE_OVERDUE_REMINDER"],
        "project": out["SCHEDULE_PROJECT_STATS"],
        "module_cascade_delay_minutes": delay_minutes,
    }


def _get_webhook_secret(team_id: str | None = None):
    """按项目组解析 webhook/secret（无组配置时回退全局）。"""
    from .dingtalk_team import resolve_dingtalk_credentials

    webhook, secret, _source = resolve_dingtalk_credentials(team_id, for_scheduler=True)
    return webhook, secret


def _scheduler_team_in_scope(team_id: str | None, scope_team_ids: frozenset[str] | None) -> bool:
    """scope_team_ids 为 None 表示全部项目组（定时任务）；否则仅匹配所属组。"""
    if scope_team_ids is None:
        return True
    tid = (team_id or "").strip()
    if not tid:
        return False
    return tid in scope_team_ids


def _scheduler_upload_team_id(rec, team_maps=None, proj_meta: dict | None = None) -> str | None:
    from .dingtalk_team import build_project_team_maps, resolve_team_id_by_upload, upload_team_id_from_maps

    maps = team_maps if team_maps is not None else build_project_team_maps()
    tid = upload_team_id_from_maps(rec, maps)
    if tid:
        return tid
    if proj_meta is not None and rec is not None:
        pn = (getattr(rec, "project_name", None) or "").strip()
        if pn:
            m = proj_meta.get(pn) or {}
            fallback = _norm_scheduler_team_id(m.get("team_id"))
            if fallback:
                return fallback
    # 与手动催办 resolve_team_id_by_upload 对齐：maps 未命中时按 Project 行解析所属组
    return _norm_scheduler_team_id(resolve_team_id_by_upload(rec))


def _scheduler_group_uploads_by_team(
    uploads, team_maps=None, proj_meta: dict | None = None
) -> dict[str | None, list]:
    out: dict[str | None, list] = {}
    for rec in uploads:
        tid = _norm_scheduler_team_id(_scheduler_upload_team_id(rec, team_maps, proj_meta))
        out.setdefault(tid, []).append(rec)
    return out


def _filter_uploads_by_scheduler_team_scope(
    uploads, team_maps, scope_team_ids: frozenset[str] | None, proj_meta: dict | None = None
):
    if scope_team_ids is None:
        return uploads
    out = []
    for u in uploads:
        if _scheduler_team_in_scope(_scheduler_upload_team_id(u, team_maps, proj_meta), scope_team_ids):
            out.append(u)
    return out


def _norm_scheduler_team_id(team_id: str | None) -> str | None:
    tid = (team_id or "").strip()
    return tid or None


def _scheduler_upload_team_id_normalized(rec, team_maps, proj_meta: dict | None = None) -> str | None:
    return _norm_scheduler_team_id(_scheduler_upload_team_id(rec, team_maps, proj_meta))


def _upload_record_is_completed(rec) -> bool:
    return bool((getattr(rec, "completion_status", None) or "").strip())


def _scheduler_team_uploads(uploads, team_id: str | None, team_maps, proj_meta: dict | None = None) -> list:
    want = _norm_scheduler_team_id(team_id)
    return [
        u
        for u in uploads
        if _scheduler_upload_team_id_normalized(u, team_maps, proj_meta) == want
    ]


def _scheduler_tasks_for_default_webhook(
    uploads,
    team_maps,
    dedicated_team_ids: frozenset[str],
    proj_meta: dict | None = None,
) -> list:
    """未配置独立 Webhook 的项目组 / 未归属项目组的任务，走默认机器人。"""
    out = []
    for u in uploads:
        tid = _scheduler_upload_team_id_normalized(u, team_maps, proj_meta)
        if tid and tid in dedicated_team_ids:
            continue
        out.append(u)
    return out


def _scheduler_notify_targets(scope_team_ids: frozenset[str] | None = None) -> list[dict]:
    """按「已配置独立 Webhook 的项目组」逐条发送；其余任务合并走默认机器人。"""
    from .dingtalk_team import dedicated_webhook_team_ids, iter_teams_with_dedicated_webhook

    targets: list[dict] = []
    for team_id, team_name, webhook, secret in iter_teams_with_dedicated_webhook():
        tid = _norm_scheduler_team_id(team_id)
        if not _scheduler_team_in_scope(tid, scope_team_ids):
            continue
        targets.append(
            {
                "team_id": tid,
                "team_name": team_name,
                "webhook": webhook,
                "secret": secret,
                "mode": "dedicated",
            }
        )
    dedicated_ids = dedicated_webhook_team_ids()
    default_wh, default_sec = _get_webhook_secret(None)
    if default_wh:
        targets.append(
            {
                "team_id": None,
                "team_name": "默认催办（未单独配置 Webhook 的项目组）",
                "webhook": default_wh,
                "secret": default_sec,
                "mode": "default",
                "dedicated_team_ids": dedicated_ids,
            }
        )
    return targets


def _scheduler_tasks_for_target(
    uploads,
    target: dict,
    team_maps,
    proj_meta: dict | None = None,
) -> list:
    if target.get("mode") == "dedicated":
        return _scheduler_team_uploads(uploads, target.get("team_id"), team_maps, proj_meta)
    exclude = target.get("dedicated_team_ids") or frozenset()
    return _scheduler_tasks_for_default_webhook(uploads, team_maps, exclude, proj_meta)


def _scheduler_distinct_team_ids(uploads, team_maps, proj_meta: dict | None = None) -> list[str | None]:
    ids: set[str | None] = set()
    for u in uploads:
        ids.add(_scheduler_upload_team_id_normalized(u, team_maps, proj_meta))
    return sorted(ids, key=lambda t: (t is None, t or ""))


def _scheduler_team_display_name(team_id: str | None) -> str:
    tid = _norm_scheduler_team_id(team_id)
    if not tid:
        return "（未分配项目组）"
    from .models import ProjectTeam

    team = ProjectTeam.query.get(tid)
    name = (getattr(team, "name", None) or "").strip() if team else ""
    return name or tid


def _project_name_in_scheduler_team_scope(
    project_name: str | None,
    proj_meta: dict,
    scope_team_ids: frozenset[str] | None,
) -> bool:
    if scope_team_ids is None:
        return True
    from .dingtalk_team import resolve_team_id_by_project_name

    return _scheduler_team_in_scope(resolve_team_id_by_project_name(project_name), scope_team_ids)


def _project_meta_for_scheduler() -> tuple[dict[str, dict], set[str]]:
    """读取项目优先级/状态，用于排序与过滤已结束项目。"""
    from .models import Project, UploadRecord
    from . import db

    def _project_display_label_from_fields(name, registered_country, registered_category) -> str:
        n = (name or "").strip()
        c = (registered_country or "").strip()
        cat = (registered_category or "").strip()
        if not c and not cat:
            return n
        return f"{n}（{c or '—'} / {cat or '—'}）"

    def _project_display_label(p: Project) -> str:
        return _project_display_label_from_fields(
            getattr(p, "name", None),
            getattr(p, "registered_country", None),
            getattr(p, "registered_category", None),
        )

    # 自动补齐：历史数据中出现过的项目（包括已结束）也要进入 projects 表，
    # 否则在无人打开页面1前，定时通知/统计会把它当作“未知项目”而无法按状态过滤。
    try:
        names = (
            db.session.query(UploadRecord.project_name)
            .filter(UploadRecord.project_name.isnot(None), UploadRecord.project_name != "")
            .distinct()
            .all()
        )
        for (n,) in names:
            n = (n or "").strip()
            if not n:
                continue
            # projects.name 是基础项目名（可能没有注册字段），但 upload_records.project_name 可能是展示键(label)；
            # 这里用“展示键匹配”补齐。
            exists = False
            for p in Project.query.all():
                if _project_display_label(p) == n:
                    exists = True
                    break
            if not exists:
                db.session.add(Project(name=n, priority=Project.PRIORITY_MEDIUM, status=Project.STATUS_ACTIVE))
        db.session.commit()
    except Exception:
        db.session.rollback()

    rows = Project.query.order_by(Project.name.asc()).all()
    meta = {}
    ended = set()
    for r in rows:
        label = _project_display_label(r)
        if not label:
            continue
        pr = int(getattr(r, "priority", None) or Project.PRIORITY_MEDIUM)
        st = (getattr(r, "status", None) or Project.STATUS_ACTIVE).strip().lower()
        meta[label] = {
            "priority": pr,
            "status": st,
            "team_id": (getattr(r, "assigned_team_id", None) or "").strip() or None,
        }
        if st == Project.STATUS_ENDED:
            ended.add(label)
    return meta, ended


def _resolve_mobiles_for_authors(author_names: list) -> list:
    """根据编写人员姓名解析钉钉 @ 用的手机号（与 routes / notify_content 一致）。"""
    from .notify_content import resolve_mobiles_for_author_labels

    mobiles, _, _ = resolve_mobiles_for_author_labels(author_names)
    return mobiles


def _dedupe_upload_records_for_notify(uploads: list) -> list:
    """
    催办文案内对任务列表去重，避免库中重复行或逻辑重复导致「同一条任务」在一条消息里出现两行。
    维度：项目 + 文件名 + 任务类型 + 催办对象（负责人 assignee_name，否则编写人 author）。
    """
    seen = set()
    out = []
    for u in uploads:
        person = (getattr(u, "assignee_name", None) or getattr(u, "author", None) or "").strip()
        key = (
            (u.project_name or "").strip(),
            (u.file_name or "").strip(),
            (u.task_type or "").strip(),
            person,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out


def _task_block_md(key, uploads_in_group, project_name: str = None):
    """未完成列表块。若传入 project_name 则块标题只显示影响业务方、产品（与上方「项目：xxx」合并为一条，不重复项目名）。"""
    from .notify_content import notify_doc_link_suffix_md, notify_project_name_md

    proj, bs, pr = key
    if project_name is not None:
        header = f"**影响业务方：{bs or '-'}  产品：{pr or '-'}**"
    else:
        header = (
            f"项目：{notify_project_name_md(proj)}  "
            f"影响业务方：{bs or '-'}  产品：{pr or '-'}"
        )
    lines = [header]

    for u in uploads_in_group:
        due = u.due_date.strftime("%Y-%m-%d") if u.due_date else "-"
        due_red = f'<font color="red">{due}</font>' if due != "-" else "-"
        file_label = u.file_name or "-"
        if u.task_type:
            file_label += f" ({u.task_type})"
        line = f" - 文件名称：{file_label}  截止日期：{due_red}"
        line += notify_doc_link_suffix_md(u)
        lines.append(line)
    return "\n".join(lines)


def _try_acquire_send_lock(job_id: str, cooldown_seconds: int = 120) -> bool:
    """
    尝试抢占“发送权”：同一 job_id（同一类型催办）在 cooldown_seconds 内只允许一个进程执行发送，
    避免多进程/重载导致“同一条消息发两遍”。不同类型（如周四提醒 vs 项目统计）各用不同 job_id，各发一条。
    返回 True 表示抢到，可执行发送；False 表示已有其他进程发送，本次跳过。
    """
    app = _app
    if not app:
        return False
    import time as _time
    lock_dir = os.path.join(app.instance_path, "scheduler_locks")
    try:
        os.makedirs(lock_dir, exist_ok=True)
    except OSError:
        return False
    lock_file = os.path.join(lock_dir, f"{_send_lock_file_basename(job_id)}.lock")
    now = _time.time()
    if os.path.exists(lock_file):
        try:
            mtime = os.path.getmtime(lock_file)
            if now - mtime < cooldown_seconds:
                logger.info("自动催办(%s)：其他进程已发送或正在发送，本次跳过，避免重复", job_id)
                return False
            os.unlink(lock_file)
        except OSError:
            return False
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(int(now)).encode())
        os.close(fd)
        return True
    except FileExistsError:
        logger.info("自动催办(%s)：其他进程已抢占发送权，本次跳过，避免重复", job_id)
        return False


def _mysql_user_lock_name(job_id: str) -> str:
    """MySQL GET_LOCK 名称（最大 64 字符）；含实例分支时多套共库部署互不阻塞。"""
    br = _scheduler_instance_branch() or "0"
    jid = (job_id or "").strip()
    base = f"aiword_c:{br}:{jid}"
    return base[:64]


def _try_acquire_mysql_cron_serialize_lock(job_id: str) -> bool:
    """
    在 MySQL 上使用用户级锁串行化「同一类定时钉钉」发送。
    解决：多台机器/多个部署目录导致 instance_path 不一致时，仅靠本地 .lock 文件无法互斥的问题。
    非 MySQL 或执行失败时返回 True（不阻塞发送，仍依赖本地锁文件）。
    """
    app = _app
    if not app:
        return True
    try:
        with app.app_context():
            from . import db

            uri = (db.engine.url.drivername or "") if db.engine is not None else ""
            if "mysql" not in uri:
                return True
            lock_name = _mysql_user_lock_name(job_id)
            conn = db.engine.raw_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT GET_LOCK(%s, 0) AS ok", (lock_name,))
                row = cur.fetchone()
                ok = int(row[0]) if row and row[0] is not None else 0
                cur.close()
                if ok == 1:
                    if not hasattr(_cron_mysql_lock_tls, "conns"):
                        _cron_mysql_lock_tls.conns = {}
                    _cron_mysql_lock_tls.conns[job_id] = conn
                    return True
                if ok == 0:
                    logger.info("自动催办(%s)：MySQL GET_LOCK 未抢到，本次跳过，避免重复", job_id)
                else:
                    logger.warning("自动催办(%s)：MySQL GET_LOCK 异常返回值 %s，继续仅依赖本地锁", job_id, ok)
                conn.close()
                return False
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                raise
    except Exception as e:
        logger.warning("自动催办(%s)：MySQL GET_LOCK 失败，回退为仅本地锁: %s", job_id, e)
        return True


def _release_mysql_cron_serialize_lock(job_id: str) -> None:
    app = _app
    if not app:
        return
    try:
        with app.app_context():
            from . import db

            uri = (db.engine.url.drivername or "") if db.engine is not None else ""
            if "mysql" not in uri:
                return
            conns = getattr(_cron_mysql_lock_tls, "conns", None) or {}
            conn = conns.pop(job_id, None)
            if conn is None:
                return
            lock_name = _mysql_user_lock_name(job_id)
            try:
                cur = conn.cursor()
                cur.execute("SELECT RELEASE_LOCK(%s) AS freed", (lock_name,))
                cur.close()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
    except Exception as e:
        logger.warning("自动催办(%s)：MySQL RELEASE_LOCK 失败: %s", job_id, e)


def _cron_send_dedupe_slot_key(job_id: str) -> str:
    """
    与定时触发同一分钟内的互斥：PRIMARY KEY 同槽位只容一条。
    - 系统配置 SCHEDULER_INSTANCE_ID 留空：同 job 同分钟全库一条（多 worker / 多机 HA 去重）。
    - 各部署配置不同实例标识：同 job 同分钟每部署一条（共库多服务各发一条）。
    """
    from .models import now_local

    nl = now_local()
    br = _scheduler_instance_branch() or "0"
    return f"{job_id}:{br}:{nl.strftime('%Y-%m-%d_%H%M')}"


def _try_claim_cron_send_dedupe(slot_key: str) -> bool:
    """抢占发送槽；已被其他 worker/主机占用则返回 False。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    from . import db

    is_sqlite = db.engine.dialect.name == "sqlite"
    now_expr = "datetime('now')" if is_sqlite else "NOW()"
    try:
        db.session.execute(
            text(f"INSERT INTO scheduler_dingtalk_dedupe (slot_key, created_at) VALUES (:k, {now_expr})"),
            {"k": slot_key},
        )
        db.session.commit()
        return True
    except IntegrityError:
        db.session.rollback()
        return False
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        logger.warning("定时钉钉去重表写入失败，继续发送（可能重复）: %s", e)
        return True


def _release_cron_send_dedupe_claim(slot_key: str) -> None:
    """发送失败时释放槽，便于同分钟内重试。"""
    from sqlalchemy import text

    from . import db

    try:
        db.session.execute(text("DELETE FROM scheduler_dingtalk_dedupe WHERE slot_key = :k"), {"k": slot_key})
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass


# 多 Gunicorn worker 各起一份 APScheduler 时，同一时刻会各跑一次；成功发送后须在冷却期内保留锁文件，
# 不能在 finally 里立刻删除，否则第二个 worker 会误判“未发送”再发一遍。
_DEFAULT_CRON_SEND_COOLDOWN = 3600


def _release_send_lock_after_job(lock_file: str, keep_lock: bool) -> None:
    """keep_lock=True：写入时间戳，供 _try_acquire_send_lock 在冷却期内拦截其他进程；False：删除锁以便重试。"""
    try:
        if keep_lock:
            with open(lock_file, "w", encoding="utf-8") as f:
                f.write(str(int(time.time())))
        elif os.path.exists(lock_file):
            os.unlink(lock_file)
    except OSError:
        pass


def _run_thursday_reminder(
    skip_dedupe: bool = False,
    scope_team_ids: frozenset[str] | None = None,
):
    """每周四 16:00 提醒：统计全部事项（不限于本周），按项目分组展示未完成列表，项目与影响业务方/产品合并为一条显示，并依次 @ 待办人员。"""
    app = _app
    if not app:
        return {"no_tasks": True, "teams_sent": 0}
    if not _try_acquire_send_lock("thursday_reminder", cooldown_seconds=_DEFAULT_CRON_SEND_COOLDOWN):
        return {"no_tasks": False, "teams_sent": 0, "last_error": "跳过(其他进程已发送)"}
    lock_file = os.path.join(
        app.instance_path, "scheduler_locks", f"{_send_lock_file_basename('thursday_reminder')}.lock"
    )
    mysql_lock_ok = False
    actually_sent = False
    try:
        if not _try_acquire_mysql_cron_serialize_lock("thursday_reminder"):
            _release_send_lock_after_job(lock_file, False)
            return {"no_tasks": False, "teams_sent": 0, "last_error": "跳过(其他实例已发送)"}
        mysql_lock_ok = True
        with app.app_context():
            from . import dingtalk_service
            from .models import UploadRecord
            from .notify_content import notify_project_label_line_md

            proj_meta, ended = _project_meta_for_scheduler()
            from .dingtalk_team import build_project_team_maps

            team_maps = build_project_team_maps()
            q_all = UploadRecord.query.filter(UploadRecord.assignee_name.isnot(None))
            if ended:
                q_all = q_all.filter(~UploadRecord.project_name.in_(list(ended)))
            all_tasks = q_all.all()

            q_pending = UploadRecord.query.filter(
                UploadRecord.completion_status.is_(None),
                UploadRecord.assignee_name.isnot(None),
            )
            if ended:
                q_pending = q_pending.filter(~UploadRecord.project_name.in_(list(ended)))
            pending_tasks = q_pending.order_by(UploadRecord.due_date).all()
            pending_tasks = _dedupe_upload_records_for_notify(pending_tasks)
            if scope_team_ids is not None:
                all_tasks = _filter_uploads_by_scheduler_team_scope(
                    all_tasks, team_maps, scope_team_ids, proj_meta
                )
                pending_tasks = _filter_uploads_by_scheduler_team_scope(
                    pending_tasks, team_maps, scope_team_ids, proj_meta
                )

            if not all_tasks:
                return {"no_tasks": True, "teams_sent": 0}

            from .app_settings import get_setting_for_scheduler
            base_url = (get_setting_for_scheduler("BASE_URL", default="", app=app) or "").strip().rstrip("/")
            page2_path = _get_page2_path(app)
            page2_url = f"{base_url}{page2_path}" if base_url else ""

            def _group_key(u):
                return (u.project_name or "", u.business_side or "", u.product or "")

            dedupe_key = None
            if not skip_dedupe:
                dedupe_key = _cron_send_dedupe_slot_key("thursday_reminder")
                if not _try_claim_cron_send_dedupe(dedupe_key):
                    logger.info("自动催办(周四提醒)：本分钟槽位已被占用，跳过重复发送")
                    return {"no_tasks": False, "teams_sent": 0, "last_error": "跳过(本分钟已由其他实例发送)"}
            send_ok = False
            teams_sent = 0
            try:
                for target in _scheduler_notify_targets(scope_team_ids):
                    webhook = target.get("webhook")
                    secret = target.get("secret")
                    if not webhook:
                        continue
                    team_records = _scheduler_tasks_for_target(all_tasks, target, team_maps, proj_meta)
                    team_pending = _scheduler_tasks_for_target(pending_tasks, target, team_maps, proj_meta)
                    if not team_records:
                        continue
                    team_total = len(team_records)
                    team_completed = sum(1 for u in team_records if _upload_record_is_completed(u))
                    team_pending_count = len(team_pending)
                    team_name = target.get("team_name") or _scheduler_team_display_name(target.get("team_id"))
                    logger.info(
                        "自动催办(周四提醒)：发送至 team=%s mode=%s total=%d completed=%d pending=%d",
                        team_name,
                        target.get("mode"),
                        team_total,
                        team_completed,
                        team_pending_count,
                    )
                    lines = [
                        "【每周任务完成提醒】",
                        "",
                        f"项目组：**{team_name}**",
                        "",
                        f"全部事项共 {team_total} 项：已完成 {team_completed} 项，未完成 {team_pending_count} 项。",
                        "",
                    ]
                    if not team_pending:
                        lines.append("当前无未完成任务。")
                    else:
                        team_pending_by_project: dict[str, list] = {}
                        for u in team_pending:
                            pn = u.project_name or ""
                            team_pending_by_project.setdefault(pn, []).append(u)

                        def _proj_sort_key(pn: str):
                            m = proj_meta.get(pn) or {}
                            return (-int(m.get("priority") or 2), pn or "")

                        for project_name in sorted(team_pending_by_project.keys(), key=_proj_sort_key):
                            uploads = team_pending_by_project.get(project_name) or []
                            groups = {}
                            for u in uploads:
                                k = _group_key(u)
                                groups.setdefault(k, []).append(u)
                            lines.append(notify_project_label_line_md(project_name))
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
                    team_assignees = sorted(
                        {
                            (u.assignee_name or u.author or "").strip()
                            for u in team_pending
                            if (u.assignee_name or u.author or "").strip()
                        }
                    )
                    at_names = team_assignees if team_assignees else None
                    at_mobiles = _resolve_mobiles_for_authors(team_assignees) if team_assignees else None
                    result = dingtalk_service.send_markdown_message(
                        "每周任务完成提醒",
                        "\n".join(lines),
                        at_mobiles=at_mobiles,
                        at_names=at_names,
                        webhook=webhook,
                        secret=secret,
                    )
                    send_ok = bool(result and result.get("success")) or send_ok
                    if result and result.get("success"):
                        teams_sent += 1
            finally:
                if dedupe_key and not send_ok:
                    _release_cron_send_dedupe_claim(dedupe_key)
            if send_ok:
                actually_sent = True
            else:
                logger.warning("自动催办(周四提醒)：钉钉发送失败，请检查 Webhook/Secret 及网络")
            return {"no_tasks": False, "teams_sent": teams_sent, "last_error": None if send_ok else "钉钉未返回成功"}
    finally:
        _release_send_lock_after_job(lock_file, actually_sent)
        if mysql_lock_ok:
            _release_mysql_cron_serialize_lock("thursday_reminder")
    return {"no_tasks": False, "teams_sent": 0}


def _run_overdue_reminder(
    skip_dedupe: bool = False,
    scope_team_ids: frozenset[str] | None = None,
):
    """每日 15:00 检查：截止日期为明天的任务，按负责人合并为一条消息发送。返回发送结果供测试接口展示。"""
    app = _app
    if not app:
        return {"no_tasks": False, "sent": 0, "failed": 0, "last_error": "未初始化应用"}
    if not _try_acquire_send_lock("overdue_reminder", cooldown_seconds=_DEFAULT_CRON_SEND_COOLDOWN):
        return {"no_tasks": False, "sent": 0, "failed": 0, "last_error": "跳过(其他进程已发送)"}
    lock_file = os.path.join(
        app.instance_path, "scheduler_locks", f"{_send_lock_file_basename('overdue_reminder')}.lock"
    )
    mysql_lock_ok = False
    keep_lock = False
    try:
        if not _try_acquire_mysql_cron_serialize_lock("overdue_reminder"):
            _release_send_lock_after_job(lock_file, False)
            return {"no_tasks": False, "sent": 0, "failed": 0, "last_error": "跳过(其他实例已发送)"}
        mysql_lock_ok = True
        with app.app_context():
            from . import dingtalk_service
            from .models import UploadRecord, now_local

            tomorrow = (now_local().date() + timedelta(days=1))
            proj_meta, ended = _project_meta_for_scheduler()
            from .dingtalk_team import build_project_team_maps

            team_maps = build_project_team_maps()
            q = UploadRecord.query.filter(
                UploadRecord.due_date == tomorrow,
                UploadRecord.completion_status.is_(None),
                UploadRecord.assignee_name.isnot(None),
            )
            if ended:
                q = q.filter(~UploadRecord.project_name.in_(list(ended)))
            tasks = q.order_by(UploadRecord.assignee_name, UploadRecord.due_date).all()
            tasks = _dedupe_upload_records_for_notify(tasks)
            if scope_team_ids is not None:
                tasks = _filter_uploads_by_scheduler_team_scope(
                    tasks, team_maps, scope_team_ids, proj_meta
                )

            if not tasks:
                return {"no_tasks": True, "sent": 0, "failed": 0, "last_error": None}

            dedupe_key = None
            if not skip_dedupe:
                dedupe_key = _cron_send_dedupe_slot_key("overdue_reminder")
                if not _try_claim_cron_send_dedupe(dedupe_key):
                    return {
                        "no_tasks": False,
                        "sent": 0,
                        "failed": 0,
                        "last_error": "跳过(本分钟已由其他实例发送)",
                    }

            from .app_settings import get_setting_for_scheduler
            base_url = (get_setting_for_scheduler("BASE_URL", default="", app=app) or "").strip().rstrip("/")
            page2_path = _get_page2_path(app)
            page2_url = f"{base_url}{page2_path}" if base_url else ""

            by_team_assignee: dict[tuple[str | None, str], list] = {}

            for t in tasks:
                name = (t.assignee_name or t.author or "").strip()
                if not name:
                    continue
                team_id = _scheduler_upload_team_id(t, team_maps, proj_meta)
                key = (_norm_scheduler_team_id(team_id), name)
                by_team_assignee.setdefault(key, []).append(t)

            sent = 0
            failed = 0
            last_error = None
            webhook_cache: dict[str | None, tuple[str, str | None]] = {}
            try:
                for (team_id, assignee_name), person_tasks in by_team_assignee.items():
                    if not _scheduler_team_in_scope(team_id, scope_team_ids):
                        continue
                    if not person_tasks:
                        continue
                    if team_id not in webhook_cache:
                        webhook_cache[team_id] = _get_webhook_secret(team_id)
                    webhook, secret = webhook_cache[team_id]
                    if not webhook:
                        failed += 1
                        last_error = "未配置钉钉 Webhook"
                        continue
                    groups = {}
                    for u in person_tasks:
                        k = (u.project_name or "", u.business_side or "", u.product or "")
                        groups.setdefault(k, []).append(u)
                    def _grp_sort_key(item):
                        k, _grp = item
                        pn = k[0] if isinstance(k, tuple) and len(k) > 0 else ""
                        pr = int((proj_meta.get(pn) or {}).get("priority") or 2)
                        return (-pr, pn or "", k[1] or "", k[2] or "")
                    task_list = "\n\n".join(_task_block_md(k, grp) for k, grp in sorted(groups.items(), key=_grp_sort_key))
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
                    if result.get("success"):
                        sent += 1
                    else:
                        failed += 1
                        last_error = result.get("error") or "未知错误"
                        logger.warning("自动催办(逾期前一日)：钉钉发送失败 assignee=%s error=%s", assignee_name, last_error)
            finally:
                if dedupe_key and sent == 0:
                    _release_cron_send_dedupe_claim(dedupe_key)
            keep_lock = sent > 0
            return {"no_tasks": False, "sent": sent, "failed": failed, "last_error": last_error}
    finally:
        _release_send_lock_after_job(lock_file, keep_lock)
        if mysql_lock_ok:
            _release_mysql_cron_serialize_lock("overdue_reminder")


def _run_project_stats(
    skip_dedupe: bool = False,
    scope_team_ids: frozenset[str] | None = None,
):
    """每两天 9:30：按项目统计每个人未完成任务项（不显示未完成列表），并依次 @ 待办人员。"""
    app = _app
    if not app:
        return {"no_tasks": True, "teams_sent": 0}
    if not _try_acquire_send_lock("project_stats", cooldown_seconds=_DEFAULT_CRON_SEND_COOLDOWN):
        return {"no_tasks": False, "teams_sent": 0, "last_error": "跳过(其他进程已发送)"}
    lock_file = os.path.join(
        app.instance_path, "scheduler_locks", f"{_send_lock_file_basename('project_stats')}.lock"
    )
    mysql_lock_ok = False
    actually_sent = False
    try:
        if not _try_acquire_mysql_cron_serialize_lock("project_stats"):
            _release_send_lock_after_job(lock_file, False)
            return {"no_tasks": False, "teams_sent": 0, "last_error": "跳过(其他实例已发送)"}
        mysql_lock_ok = True
        with app.app_context():
            from . import dingtalk_service
            from .models import UploadRecord, now_local
            from .notify_content import notify_project_label_line_md

            from .app_settings import get_setting_for_scheduler
            base_url = (get_setting_for_scheduler("BASE_URL", default="", app=app) or "").strip().rstrip("/")
            page2_path = _get_page2_path(app)
            page2_url = f"{base_url}{page2_path}" if base_url else ""

            proj_meta, ended = _project_meta_for_scheduler()
            from .dingtalk_team import build_project_team_maps

            team_maps = build_project_team_maps()
            q_pending = UploadRecord.query.filter(UploadRecord.completion_status.is_(None))
            if ended:
                q_pending = q_pending.filter(~UploadRecord.project_name.in_(list(ended)))
            pending_tasks = q_pending.order_by(UploadRecord.due_date).all()
            pending_tasks = _dedupe_upload_records_for_notify(pending_tasks)
            if scope_team_ids is not None:
                pending_tasks = _filter_uploads_by_scheduler_team_scope(
                    pending_tasks, team_maps, scope_team_ids, proj_meta
                )

            if scope_team_ids is not None and not pending_tasks:
                return {"no_tasks": True, "teams_sent": 0}

            dedupe_key = None
            if not skip_dedupe:
                dedupe_key = _cron_send_dedupe_slot_key("project_stats")
                if not _try_claim_cron_send_dedupe(dedupe_key):
                    logger.info("自动催办(项目统计)：本分钟槽位已被占用，跳过重复发送")
                    return {"no_tasks": False, "teams_sent": 0, "last_error": "跳过(本分钟已由其他实例发送)"}
            send_ok = False
            teams_sent = 0
            try:
                for target in _scheduler_notify_targets(scope_team_ids):
                    webhook = target.get("webhook")
                    secret = target.get("secret")
                    if not webhook:
                        continue
                    team_pending = _scheduler_tasks_for_target(pending_tasks, target, team_maps, proj_meta)
                    team_name = target.get("team_name") or _scheduler_team_display_name(target.get("team_id"))
                    team_project_list = sorted(
                        {(u.project_name or "") for u in team_pending if (u.project_name or "").strip()}
                    )
                    if not team_pending and target.get("mode") == "default":
                        continue
                    logger.info(
                        "自动催办(项目统计)：发送至 team=%s mode=%s projects=%d pending=%d",
                        team_name,
                        target.get("mode"),
                        len(team_project_list),
                        len(team_pending),
                    )
                    if not team_pending:
                        lines = [
                            "【每两天项目完成情况统计】",
                            "",
                            f"项目组：**{team_name}**",
                            "",
                            "当前无未完成任务。",
                        ]
                        at_names = None
                        at_mobiles = None
                    else:
                        team_pending_by_project: dict[str, list] = {}
                        for u in team_pending:
                            pn = u.project_name or ""
                            team_pending_by_project.setdefault(pn, []).append(u)
                        lines = [
                            "【每两天项目完成情况统计】",
                            "",
                            f"项目组：**{team_name}**",
                            "",
                            f"本项目组未完成任务数：{len(team_pending)} 项，涉及 {len(team_project_list)} 个项目。",
                            "",
                        ]
                        def _proj_sort_key(pn: str):
                            m = proj_meta.get(pn) or {}
                            return (-int(m.get("priority") or 2), pn or "")

                        for project_name in sorted(team_pending_by_project.keys(), key=_proj_sort_key):
                            uploads = team_pending_by_project.get(project_name) or []
                            by_person = {}
                            for u in uploads:
                                name = (u.assignee_name or u.author or "").strip() or "（未指定）"
                                by_person[name] = by_person.get(name, 0) + 1
                            person_stats = "、".join(f"{name} {cnt} 项" for name, cnt in sorted(by_person.items()))
                            pn = project_name or "（空）"
                            lines.append(notify_project_label_line_md(pn))
                            lines.append("")
                            lines.append(f"未完成任务（按人统计）：{person_stats}")
                            today = now_local().date()
                            overdue_dates = [u.due_date for u in uploads if u.due_date and u.due_date < today]
                            if overdue_dates:
                                last_overdue = max(overdue_dates)
                                delay_days = (today - last_overdue).days
                                lines.append("")
                                lines.append(f"该项目已**<font color=\"red\">延期{delay_days}天</font>**，请抓紧处理")
                            lines.append("")
                            lines.append("")
                        at_names = sorted(
                            {
                                (u.assignee_name or u.author or "").strip()
                                for u in team_pending
                                if (u.assignee_name or u.author or "").strip()
                            }
                        ) or None
                        at_mobiles = _resolve_mobiles_for_authors(list(at_names)) if at_names else None
                    if page2_url:
                        lines.append(f"页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）")
                        lines.append("")
                    lines.append("## **编写完成后请在页面2中标记完成状态。**")
                    result = dingtalk_service.send_markdown_message(
                        "每两天项目完成情况统计",
                        "\n".join(lines),
                        at_mobiles=at_mobiles,
                        at_names=at_names,
                        webhook=webhook,
                        secret=secret,
                    )
                    send_ok = bool(result and result.get("success")) or send_ok
                    if result and result.get("success"):
                        teams_sent += 1
            finally:
                if dedupe_key and not send_ok:
                    _release_cron_send_dedupe_claim(dedupe_key)
            if send_ok:
                actually_sent = True
            else:
                logger.warning("自动催办(项目统计)：钉钉发送失败，请检查 Webhook/Secret 及网络")
            return {"no_tasks": False, "teams_sent": teams_sent, "last_error": None if send_ok else "钉钉未返回成功"}
    finally:
        _release_send_lock_after_job(lock_file, actually_sent)
        if mysql_lock_ok:
            _release_mysql_cron_serialize_lock("project_stats")
    return {"no_tasks": False, "teams_sent": 0}


def _send_module_cascade_for_project(project_name: str, trigger_module: str, target_module: str, trigger_label: str):
    """
    对指定项目发送模块级联催办：仅针对该项目的 target_module 编写人员，每人一条，多人多文档按人汇总。
    在 app 上下文中调用。
    """
    from . import dingtalk_service
    from .models import UploadRecord

    app = _app
    if not app:
        return
    from .dingtalk_team import resolve_team_id_by_project_name

    webhook, secret = _get_webhook_secret(resolve_team_id_by_project_name(project_name))
    if not webhook:
        return
    from .app_settings import get_setting_for_scheduler
    base_url = (get_setting_for_scheduler("BASE_URL", default="", app=app) or "").strip().rstrip("/")
    page2_path = _get_page2_path(app)
    page2_url = f"{base_url}{page2_path}" if base_url else ""
    pname = (project_name or "").strip()
    if not pname:
        return
    _meta, _ended = _project_meta_for_scheduler()
    if pname in _ended:
        return

    def _group_key(u):
        return (u.project_name or "", u.business_side or "", u.product or "")

    def _task_block_md_for_cascade(key, uploads_in_group):
        from .notify_content import notify_doc_link_suffix_md, notify_project_name_md

        proj, bs, pr = key
        header = (
            f"项目：{notify_project_name_md(proj)}  "
            f"影响业务方：{bs or '-'}  产品：{pr or '-'}"
        )
        lines = [header]

        for u in uploads_in_group:
            due = u.due_date.strftime("%Y-%m-%d") if u.due_date else "-"
            due_red = f'<font color="red">{due}</font>' if due != "-" else "-"
            file_label = u.file_name or "-"
            if u.task_type:
                file_label += f" ({u.task_type})"
            line = f" - 文件名称：{file_label}  截止日期：{due_red}"
            line += notify_doc_link_suffix_md(u)
            lines.append(line)
        return "\n".join(lines)

    pending_in_project = UploadRecord.query.filter(
        UploadRecord.project_name == pname,
        UploadRecord.belonging_module == target_module,
        UploadRecord.completion_status.is_(None),
    ).all()
    pending_in_project = _dedupe_upload_records_for_notify(pending_in_project)
    if not pending_in_project:
        return
    pending_by_author = {}
    for u in pending_in_project:
        name = (u.author or "").strip()
        if name:
            pending_by_author.setdefault(name, []).append(u)
    for author_name in sorted(pending_by_author.keys()):
        uploads = pending_by_author[author_name]
        groups = {}
        for u in uploads:
            k = _group_key(u)
            groups.setdefault(k, []).append(u)
        task_list = "\n\n".join(
            _task_block_md_for_cascade(k, grp) for k, grp in sorted(groups.items())
        )
        hint = f"当前{trigger_label}文档已完成，请抓紧编写您的文档；"
        lines = [
            "【个人任务催办】（模块级联）",
            f"致：{author_name}",
            hint,
            "",
            f"您有 {len(uploads)} 个任务待完成：",
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
        at_mobiles = _resolve_mobiles_for_authors([author_name])
        result = dingtalk_service.send_markdown_message(
            "个人任务催办",
            content,
            at_mobiles=at_mobiles if at_mobiles else None,
            at_names=[author_name],
            webhook=webhook,
            secret=secret,
        )
        if not result.get("success"):
            logger.warning("自动催办(模块级联)：钉钉发送失败 project=%s author=%s", pname, author_name)


def _run_module_cascade_manual(project_name: str | None = None):
    """
    手动模块级联催办：按项目检查，若某项目下产品模块全部完成则给该项目的开发人员发催办；
    若某项目下开发模块全部完成则给该项目的测试人员发催办。不依赖延迟队列，立即发送。
    project_name: 若指定则只处理该项目，否则处理全部项目。
    """
    app = _app
    if not app:
        return
    with app.app_context():
        from . import db
        from .models import UploadRecord

        if project_name and (project_name or "").strip():
            project_names = [(project_name or "").strip()]
        else:
            projects = (
                db.session.query(UploadRecord.project_name)
                .filter(UploadRecord.project_name.isnot(None), UploadRecord.project_name != "")
                .distinct()
                .all()
            )
            project_names = [p[0] for p in projects if (p[0] or "").strip()]
        sent_count = 0
        for pname in project_names:
            pname = (pname or "").strip()
            if not pname:
                continue
            for trigger_module, target_module in (("产品", "开发"), ("开发", "测试")):
                all_in_module = UploadRecord.query.filter(
                    UploadRecord.project_name == pname,
                    UploadRecord.belonging_module == trigger_module,
                ).all()
                if not all_in_module:
                    continue
                if any(getattr(u, "completion_status", None) is None for u in all_in_module):
                    continue
                _send_module_cascade_for_project(pname, trigger_module, target_module, trigger_module)
                sent_count += 1
        if sent_count:
            logger.info("手动模块级联催办已发送 %d 个项目/模块", sent_count)


def _run_process_module_cascade_pending():
    """
    每分钟执行：处理到期的模块级联催办待执行记录，按项目分开发送，发送后标记为已执行。
    """
    app = _app
    if not app:
        return
    # 每分钟触发；冷却需大于「单轮处理」耗时，避免多 worker 同分钟各跑一轮导致重复钉钉
    if not _try_acquire_send_lock("module_cascade_pending_processor", cooldown_seconds=120):
        return
    lock_file = os.path.join(
        app.instance_path,
        "scheduler_locks",
        f"{_send_lock_file_basename('module_cascade_pending_processor')}.lock",
    )
    keep_lock = False
    try:
        with app.app_context():
            from .models import UploadRecord, ModuleCascadeReminder, AppConfig, now_local

            _meta, _ended = _project_meta_for_scheduler()
            now = now_local()
            pending = ModuleCascadeReminder.query.filter(
                ModuleCascadeReminder.status == "pending",
                ModuleCascadeReminder.run_at <= now,
            ).order_by(ModuleCascadeReminder.run_at).all()
            # 同一项目+触发模块若有多条 pending（并发入队等），只发送一次钉钉，避免重复催办
            by_trip = defaultdict(list)
            for rec in pending:
                by_trip[(rec.project_name, rec.trigger_module, rec.target_module)].append(rec)
            for recs in by_trip.values():
                head = recs[0]
                if (head.project_name or "").strip() and (head.project_name or "").strip() in _ended:
                    # 已结束项目：不再催办，但需要把队列标记为已处理，避免一直 pending
                    pass
                else:
                    _send_module_cascade_for_project(
                        head.project_name,
                        head.trigger_module,
                        head.target_module,
                        head.trigger_module,
                    )
                for r in recs:
                    r.status = "sent"
                    r.sent_at = now
            if pending:
                from . import db
                db.session.commit()
                logger.info(
                    "模块级联催办已处理 %d 条队列记录，合并为 %d 次发送",
                    len(pending),
                    len(by_trip),
                )
                keep_lock = True
    finally:
        _release_send_lock_after_job(lock_file, keep_lock)


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
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_overdue_reminder,
        CronTrigger(**overdue),
        id="overdue_reminder",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_project_stats,
        CronTrigger(**project),
        id="project_stats",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    if IntervalTrigger is not None:
        scheduler.add_job(
            _run_process_module_cascade_pending,
            IntervalTrigger(minutes=1),
            id="module_cascade_pending_processor",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
        )
    scheduler.start()
    global _shutdown_registered
    if not _shutdown_registered:
        atexit.register(shutdown_scheduler)
        _shutdown_registered = True
    logger.info(
        "定时任务已注册：每周提醒 %s，逾期 %s，每两天统计 %s，模块级联（按项目完成后延迟执行）",
        cfg["weekly"],
        cfg["overdue"],
        cfg["project"],
    )


def reschedule_jobs(app: "Flask") -> bool:
    """根据数据库中的配置重新注册定时任务（保存配置后调用）。模块级联为按项目完成后延迟执行，不在此重配。"""
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
    scheduler.add_job(
        _run_thursday_reminder,
        CronTrigger(**weekly),
        id="thursday_reminder",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_overdue_reminder,
        CronTrigger(**overdue),
        id="overdue_reminder",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _run_project_stats,
        CronTrigger(**project),
        id="project_stats",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    logger.info(
        "定时任务已更新：每周 %s，逾期 %s，每两天 %s",
        cfg["weekly"], cfg["overdue"], cfg["project"],
    )
    return True
