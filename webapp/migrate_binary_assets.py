# -*- coding: utf-8 -*-
"""启动时将仍在本机磁盘上的模板、生成结果、备注附件迁入数据库（幂等）。"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask

logger = logging.getLogger(__name__)


def migrate_binary_assets_to_db(app: Flask) -> None:
    from . import db
    from .models import GenerateRecord, NoteAttachmentFile, UploadRecord

    uploads_dir = Path(app.config["UPLOAD_FOLDER"])

    for u in UploadRecord.query.all():
        if u.template_file_blob:
            continue
        sp = u.storage_path
        if not sp:
            continue
        p = Path(sp)
        if not p.is_file():
            continue
        try:
            u.template_file_blob = p.read_bytes()
            p.unlink(missing_ok=True)
            u.storage_path = None
            db.session.add(u)
        except Exception as e:
            logger.warning("迁入模板失败 upload_id=%s: %s", u.id, e)
    try:
        db.session.commit()
    except Exception as e:
        logger.warning("提交模板迁入失败: %s", e)
        db.session.rollback()

    for g in GenerateRecord.query.all():
        if g.output_file_blob:
            continue
        op = g.output_path
        if not op:
            continue
        p = Path(op)
        if not p.is_file():
            continue
        try:
            g.output_file_blob = p.read_bytes()
            p.unlink(missing_ok=True)
            g.output_path = None
            db.session.add(g)
        except Exception as e:
            logger.warning("迁入生成文件失败 generate_id=%s: %s", g.id, e)
    try:
        db.session.commit()
    except Exception as e:
        logger.warning("提交生成文件迁入失败: %s", e)
        db.session.rollback()

    notes_dir = uploads_dir / "notes"
    if notes_dir.is_dir():
        for p in list(notes_dir.iterdir()):
            if not p.is_file():
                continue
            if NoteAttachmentFile.query.filter_by(stored_name=p.name).first():
                continue
            try:
                db.session.add(
                    NoteAttachmentFile(
                        stored_name=p.name,
                        file_blob=p.read_bytes(),
                        original_name=p.name,
                    )
                )
                p.unlink(missing_ok=True)
            except Exception as e:
                logger.warning("迁入备注附件失败 %s: %s", p.name, e)
        try:
            db.session.commit()
        except Exception as e:
            logger.warning("提交备注附件迁入失败: %s", e)
            db.session.rollback()
