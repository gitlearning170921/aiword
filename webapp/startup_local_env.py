# -*- coding: utf-8 -*-
"""
本机运行时目录/缓存（与业务数据无关）：启动时自动处理，并在日志中提示新机器需核对项。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask

logger = logging.getLogger(__name__)


def run_startup_local_maintenance(app: Flask, project_root: Path) -> None:
    """
    1. 确保 instance/scheduler_locks 存在。
    2. 清除 scheduler_locks 下 *.lock：迁机或复制项目时常带入旧机锁，会导致定时任务在冷却期内被误跳过。
    3. 删除 uploads/_dbtpl_*.docx：仅为模板缓存，下次访问会从数据库或链接重建。
    4. 打一条部署提示（新机器核对数据库与系统设置）。
    """
    try:
        inst = Path(app.instance_path)
        lock_dir = inst / "scheduler_locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        cleared_locks = 0
        for p in lock_dir.glob("*.lock"):
            try:
                p.unlink()
                cleared_locks += 1
            except OSError:
                pass
        if cleared_locks:
            logger.info(
                "已清除 %s 个定时任务本机锁文件（避免沿用旧机/异常退出留下的锁）",
                cleared_locks,
            )

        upload_root = Path(app.config.get("UPLOAD_FOLDER") or "")
        if upload_root.is_dir():
            n_tpl = 0
            for p in upload_root.glob("_dbtpl_*.docx"):
                try:
                    p.unlink(missing_ok=True)
                    n_tpl += 1
                except OSError:
                    pass
            if n_tpl:
                logger.info("已清除 %s 个模板磁盘缓存 _dbtpl_*.docx（将从库或链接自动重建）", n_tpl)

        banner = (
            "\n"
            "========== AIWord 本机环境（已自动处理）==========\n"
            "  · 已确保 instance/scheduler_locks 存在，并清除其中 *.lock（避免旧机锁导致定时任务跳过）\n"
            "  · 已清除 uploads 下 _dbtpl_*.docx 模板缓存（需要时从数据库/链接自动重建）\n"
            "  【新机器请核对】数据库 URI（.env 或系统设置）、钉钉 Webhook、BASE_URL 等\n"
            "  说明文档：docs/SERVER_MIGRATION.md\n"
            "  设置 AIWORD_QUIET_STARTUP=1 可不再显示本横幅；删除 instance/.aiword_startup_banner 可再次显示\n"
            "==================================================\n"
        )
        logger.info(banner.strip().replace("\n", " | "))
        quiet = os.environ.get("AIWORD_QUIET_STARTUP", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        force_hint = os.environ.get("AIWORD_SHOW_STARTUP_HINT", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        marker = inst / ".aiword_startup_banner"
        if not quiet and (force_hint or not marker.exists()):
            print(banner, flush=True)
            try:
                marker.write_text("shown", encoding="utf-8")
            except OSError:
                pass
    except Exception as e:
        logger.warning("启动本机环境维护时出现异常（可忽略）: %s", e)
