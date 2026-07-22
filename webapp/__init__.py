import logging
import os
import sys
import uuid
from pathlib import Path

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import inspect, text

db = SQLAlchemy()


def _configure_console_logging(app: Flask) -> None:
    """前台启动时把日志打到 stderr，与 run_web.py / 控制台同一窗口实时可见。"""
    flag = (os.environ.get("AIWORD_CONSOLE_LOG") or "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return

    raw = (os.environ.get("AIWORD_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, raw, None)
    if not isinstance(level, int):
        level = logging.INFO

    root = logging.getLogger()
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler) and getattr(h, "_aiword_console", False):
            break
    else:
        class _FlushingStreamHandler(logging.StreamHandler):
            def emit(self, record):
                super().emit(record)
                try:
                    self.flush()
                except Exception:
                    pass

        handler = _FlushingStreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        handler._aiword_console = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    root.setLevel(level)
    app.logger.setLevel(level)
    logging.getLogger("werkzeug").setLevel(level)
    logging.getLogger("webapp").setLevel(level)


def ensure_schema(app: Flask):
    """确保数据库schema与模型定义一致，包括添加缺失的列和修复nullable约束。"""
    engine = db.engine
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    is_sqlite = engine.dialect.name == "sqlite"

    # 定时钉钉跨进程/跨主机去重：同一 job 在同一分钟内只允许一条成功 INSERT
    with engine.connect() as conn:
        if is_sqlite:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS scheduler_dingtalk_dedupe (
                        slot_key VARCHAR(192) NOT NULL PRIMARY KEY,
                        created_at DATETIME NOT NULL
                    )
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS scheduler_dingtalk_dedupe (
                        slot_key VARCHAR(192) NOT NULL PRIMARY KEY,
                        created_at DATETIME NOT NULL
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """
                )
            )
        conn.commit()

    def ensure_column(table: str, column: str, ddl_sqlite: str, ddl_other: str):
        live_inspector = inspect(engine)
        if table not in live_inspector.get_table_names():
            return
        columns = {col["name"] for col in live_inspector.get_columns(table)}
        if column in columns:
            return
        ddl = ddl_sqlite if is_sqlite else ddl_other
        try:
            with engine.connect() as conn:
                conn.execute(text(ddl))
                conn.commit()
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate column" in msg or "already exists" in msg:
                return
            raise

    def fix_upload_records_nullable():
        """修复 upload_records 表中某些字段的 nullable 约束（SQLite专用）"""
        if not is_sqlite or "upload_records" not in existing_tables:
            return
        
        columns = inspector.get_columns("upload_records")
        col_names = {col['name'] for col in columns}
        nullable_fields = ['stored_file_name', 'storage_path', 'original_file_name']
        
        need_fix = any(
            not col['nullable'] for col in columns if col['name'] in nullable_fields
        )
        need_new_cols = 'task_type' not in col_names or 'completion_status' not in col_names
        
        if not need_fix and not need_new_cols:
            return
        
        with engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            
            conn.execute(text("DROP TABLE IF EXISTS upload_records_new"))
            conn.execute(text("""
                CREATE TABLE upload_records_new (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    project_name VARCHAR(128) NOT NULL,
                    file_name VARCHAR(255) NOT NULL,
                    task_type VARCHAR(64),
                    author VARCHAR(128) NOT NULL,
                    stored_file_name VARCHAR(255),
                    storage_path VARCHAR(512),
                    original_file_name VARCHAR(255),
                    template_links TEXT,
                    notes TEXT,
                    placeholders JSON DEFAULT '[]',
                    assignee_name VARCHAR(128),
                    due_date DATE,
                    task_status VARCHAR(32) DEFAULT 'pending',
                    completion_status VARCHAR(64),
                    quick_completed INTEGER DEFAULT 0,
                    dingtalk_notified_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE (project_name, file_name, task_type)
                )
            """))
            
            old_columns = [col['name'] for col in columns]
            all_target_cols = [
                'id', 'project_name', 'file_name', 'task_type', 'author', 'stored_file_name',
                'storage_path', 'original_file_name', 'template_links', 'notes',
                'placeholders', 'assignee_name', 'due_date', 'task_status', 'completion_status',
                'quick_completed', 'dingtalk_notified_at', 'created_at', 'updated_at'
            ]
            common_columns = [c for c in all_target_cols if c in old_columns]
            cols_str = ", ".join(common_columns)
            
            conn.execute(text(f"""
                INSERT OR IGNORE INTO upload_records_new ({cols_str})
                SELECT {cols_str} FROM upload_records
            """))
            
            conn.execute(text("DROP TABLE upload_records"))
            conn.execute(text("ALTER TABLE upload_records_new RENAME TO upload_records"))
            conn.execute(text("PRAGMA foreign_keys=ON"))
            conn.commit()

    def fix_upload_records_unique_include_author():
        """将 upload_records 唯一约束改为 (project, file, type, author)（SQLite 需重建表）"""
        if "upload_records" not in existing_tables:
            return
        need_migrate = False
        if is_sqlite:
            with engine.connect() as conn:
                r = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='upload_records'"))
                row = r.fetchone()
                if row and row[0]:
                    sql = row[0]
                    if "UNIQUE (project_name, file_name, task_type, author)" in sql:
                        return
                    if "UNIQUE (project_name, file_name" in sql or "UNIQUE(project_name, file_name" in sql:
                        need_migrate = True
        else:
            indexes = inspector.get_indexes("upload_records")
            for idx in indexes:
                if not idx.get("unique"):
                    continue
                cols = idx.get("column_names") or []
                if set(cols) == {"project_name", "file_name", "task_type", "author"} and len(cols) == 4:
                    return
                if set(cols) <= {"project_name", "file_name", "task_type"} and "author" not in cols:
                    need_migrate = True
                    break
        if not need_migrate:
            return
        if is_sqlite:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA foreign_keys=OFF"))
                conn.execute(text("DROP TABLE IF EXISTS upload_records_new"))
                conn.execute(text("""
                    CREATE TABLE upload_records_new (
                        id VARCHAR(36) NOT NULL PRIMARY KEY,
                        project_name VARCHAR(128) NOT NULL,
                        file_name VARCHAR(255) NOT NULL,
                        task_type VARCHAR(64),
                        author VARCHAR(128) NOT NULL,
                        stored_file_name VARCHAR(255),
                        storage_path VARCHAR(512),
                        original_file_name VARCHAR(255),
                        template_links TEXT,
                        notes TEXT,
                        placeholders TEXT,
                        assignee_name VARCHAR(128),
                        due_date DATE,
                        business_side VARCHAR(128),
                        product VARCHAR(128),
                        country VARCHAR(64),
                        task_status VARCHAR(32) DEFAULT 'pending',
                        completion_status VARCHAR(64),
                        audit_status VARCHAR(64),
                        audit_reject_count INTEGER DEFAULT 0,
                        quick_completed INTEGER DEFAULT 0,
                        sort_order INTEGER DEFAULT 0,
                        dingtalk_notified_at DATETIME,
                        created_at DATETIME,
                        updated_at DATETIME,
                        UNIQUE (project_name, file_name, task_type, author)
                    )
                """))
                columns = inspector.get_columns("upload_records")
                old_cols = [c["name"] for c in columns]
                common = [c for c in [
                    "id", "project_name", "file_name", "task_type", "author",
                    "stored_file_name", "storage_path", "original_file_name",
                    "template_links", "notes", "placeholders", "assignee_name",
                    "due_date", "business_side", "product", "country",
                    "task_status", "completion_status", "audit_status", "audit_reject_count",
                    "quick_completed", "sort_order", "dingtalk_notified_at", "created_at", "updated_at"
                ] if c in old_cols]
                cols_str = ", ".join(common)
                conn.execute(text(f"""
                    INSERT INTO upload_records_new ({cols_str})
                    SELECT {cols_str} FROM upload_records
                """))
                conn.execute(text("DROP TABLE upload_records"))
                conn.execute(text("ALTER TABLE upload_records_new RENAME TO upload_records"))
                conn.execute(text("PRAGMA foreign_keys=ON"))
                conn.commit()
        else:
            with engine.connect() as conn:
                try:
                    conn.execute(text("ALTER TABLE upload_records DROP CONSTRAINT uq_project_file_type"))
                except Exception:
                    pass
                try:
                    conn.execute(text(
                        "ALTER TABLE upload_records ADD CONSTRAINT uq_project_file_type_author "
                        "UNIQUE (project_name, file_name, task_type, author)"
                    ))
                except Exception:
                    pass
                conn.commit()

    # 先修复 nullable 约束问题
    fix_upload_records_nullable()

    # 再修复唯一约束：增加 author（允许同项目同文件同类型不同编写人）
    fix_upload_records_unique_include_author()

    # 添加缺失的列
    ensure_column(
        "upload_records",
        "placeholders",
        "ALTER TABLE upload_records ADD COLUMN placeholders TEXT",
        "ALTER TABLE upload_records ADD COLUMN placeholders JSON",
    )
    ensure_column(
        "upload_records",
        "template_links",
        "ALTER TABLE upload_records ADD COLUMN template_links TEXT",
        "ALTER TABLE upload_records ADD COLUMN template_links TEXT",
    )
    ensure_column(
        "upload_records",
        "assignee_name",
        "ALTER TABLE upload_records ADD COLUMN assignee_name TEXT",
        "ALTER TABLE upload_records ADD COLUMN assignee_name VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "due_date",
        "ALTER TABLE upload_records ADD COLUMN due_date DATE",
        "ALTER TABLE upload_records ADD COLUMN due_date DATE",
    )
    ensure_column(
        "upload_records",
        "task_status",
        "ALTER TABLE upload_records ADD COLUMN task_status TEXT DEFAULT 'pending'",
        "ALTER TABLE upload_records ADD COLUMN task_status VARCHAR(32) DEFAULT 'pending'",
    )
    ensure_column(
        "upload_records",
        "quick_completed",
        "ALTER TABLE upload_records ADD COLUMN quick_completed INTEGER DEFAULT 0",
        "ALTER TABLE upload_records ADD COLUMN quick_completed TINYINT(1) DEFAULT 0",
    )
    ensure_column(
        "upload_records",
        "dingtalk_notified_at",
        "ALTER TABLE upload_records ADD COLUMN dingtalk_notified_at DATETIME",
        "ALTER TABLE upload_records ADD COLUMN dingtalk_notified_at DATETIME",
    )
    ensure_column(
        "upload_records",
        "task_type",
        "ALTER TABLE upload_records ADD COLUMN task_type TEXT",
        "ALTER TABLE upload_records ADD COLUMN task_type VARCHAR(64)",
    )
    ensure_column(
        "upload_records",
        "completion_status",
        "ALTER TABLE upload_records ADD COLUMN completion_status TEXT",
        "ALTER TABLE upload_records ADD COLUMN completion_status VARCHAR(64)",
    )
    ensure_column(
        "upload_records",
        "sort_order",
        "ALTER TABLE upload_records ADD COLUMN sort_order INTEGER DEFAULT 0",
        "ALTER TABLE upload_records ADD COLUMN sort_order INT DEFAULT 0",
    )
    ensure_column(
        "upload_records",
        "business_side",
        "ALTER TABLE upload_records ADD COLUMN business_side TEXT",
        "ALTER TABLE upload_records ADD COLUMN business_side VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "product",
        "ALTER TABLE upload_records ADD COLUMN product TEXT",
        "ALTER TABLE upload_records ADD COLUMN product VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "country",
        "ALTER TABLE upload_records ADD COLUMN country TEXT",
        "ALTER TABLE upload_records ADD COLUMN country VARCHAR(64)",
    )
    ensure_column(
        "upload_records",
        "audit_reject_count",
        "ALTER TABLE upload_records ADD COLUMN audit_reject_count INTEGER DEFAULT 0",
        "ALTER TABLE upload_records ADD COLUMN audit_reject_count INT DEFAULT 0",
    )
    ensure_column(
        "upload_records",
        "audit_status",
        "ALTER TABLE upload_records ADD COLUMN audit_status TEXT",
        "ALTER TABLE upload_records ADD COLUMN audit_status VARCHAR(64)",
    )
    ensure_column(
        "upload_records",
        "execution_notes",
        "ALTER TABLE upload_records ADD COLUMN execution_notes TEXT",
        "ALTER TABLE upload_records ADD COLUMN execution_notes TEXT",
    )
    ensure_column(
        "upload_records",
        "project_code",
        "ALTER TABLE upload_records ADD COLUMN project_code TEXT",
        "ALTER TABLE upload_records ADD COLUMN project_code VARCHAR(64)",
    )
    ensure_column(
        "upload_records",
        "document_number",
        "ALTER TABLE upload_records ADD COLUMN document_number TEXT",
        "ALTER TABLE upload_records ADD COLUMN document_number VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "file_version",
        "ALTER TABLE upload_records ADD COLUMN file_version TEXT",
        "ALTER TABLE upload_records ADD COLUMN file_version VARCHAR(64)",
    )
    ensure_column(
        "upload_records",
        "document_display_date",
        "ALTER TABLE upload_records ADD COLUMN document_display_date DATE",
        "ALTER TABLE upload_records ADD COLUMN document_display_date DATE",
    )
    ensure_column(
        "upload_records",
        "reviewer",
        "ALTER TABLE upload_records ADD COLUMN reviewer TEXT",
        "ALTER TABLE upload_records ADD COLUMN reviewer VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "approver",
        "ALTER TABLE upload_records ADD COLUMN approver TEXT",
        "ALTER TABLE upload_records ADD COLUMN approver VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "project_notes",
        "ALTER TABLE upload_records ADD COLUMN project_notes TEXT",
        "ALTER TABLE upload_records ADD COLUMN project_notes TEXT",
    )
    ensure_column(
        "upload_records",
        "belonging_module",
        "ALTER TABLE upload_records ADD COLUMN belonging_module TEXT",
        "ALTER TABLE upload_records ADD COLUMN belonging_module VARCHAR(32)",
    )
    ensure_column(
        "upload_records",
        "displayed_author",
        "ALTER TABLE upload_records ADD COLUMN displayed_author TEXT",
        "ALTER TABLE upload_records ADD COLUMN displayed_author VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "registered_product_name",
        "ALTER TABLE upload_records ADD COLUMN registered_product_name TEXT",
        "ALTER TABLE upload_records ADD COLUMN registered_product_name VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "model",
        "ALTER TABLE upload_records ADD COLUMN model TEXT",
        "ALTER TABLE upload_records ADD COLUMN model VARCHAR(128)",
    )
    ensure_column(
        "upload_records",
        "registration_version",
        "ALTER TABLE upload_records ADD COLUMN registration_version TEXT",
        "ALTER TABLE upload_records ADD COLUMN registration_version VARCHAR(64)",
    )
    ensure_column(
        "users",
        "mobile",
        "ALTER TABLE users ADD COLUMN mobile TEXT",
        "ALTER TABLE users ADD COLUMN mobile VARCHAR(32)",
    )
    ensure_column(
        "users",
        "is_admin",
        "ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN is_admin TINYINT(1) NOT NULL DEFAULT 0",
    )
    ensure_column(
        "generate_records",
        "output_file_name",
        "ALTER TABLE generate_records ADD COLUMN output_file_name TEXT",
        "ALTER TABLE generate_records ADD COLUMN output_file_name VARCHAR(255)",
    )
    ensure_column(
        "generate_records",
        "output_path",
        "ALTER TABLE generate_records ADD COLUMN output_path TEXT",
        "ALTER TABLE generate_records ADD COLUMN output_path VARCHAR(512)",
    )
    ensure_column(
        "upload_records",
        "template_file_blob",
        "ALTER TABLE upload_records ADD COLUMN template_file_blob BLOB",
        "ALTER TABLE upload_records ADD COLUMN template_file_blob MEDIUMBLOB",
    )
    ensure_column(
        "upload_records",
        "ftp_path",
        "ALTER TABLE upload_records ADD COLUMN ftp_path TEXT",
        "ALTER TABLE upload_records ADD COLUMN ftp_path VARCHAR(768) NULL",
    )
    ensure_column(
        "upload_records",
        "ftp_last_error",
        "ALTER TABLE upload_records ADD COLUMN ftp_last_error TEXT",
        "ALTER TABLE upload_records ADD COLUMN ftp_last_error VARCHAR(512) NULL",
    )
    ensure_column(
        "generate_records",
        "output_file_blob",
        "ALTER TABLE generate_records ADD COLUMN output_file_blob BLOB",
        "ALTER TABLE generate_records ADD COLUMN output_file_blob MEDIUMBLOB",
    )

    # projects：注册国家/注册类别（用于三字段去重）
    ensure_column(
        "projects",
        "registered_country",
        ddl_sqlite="ALTER TABLE projects ADD COLUMN registered_country VARCHAR(128)",
        ddl_other="ALTER TABLE projects ADD COLUMN registered_country VARCHAR(128) NULL",
    )
    ensure_column(
        "projects",
        "registered_category",
        ddl_sqlite="ALTER TABLE projects ADD COLUMN registered_category VARCHAR(128)",
        ddl_other="ALTER TABLE projects ADD COLUMN registered_category VARCHAR(128) NULL",
    )

    # 绑定项目ID：用于删除/统计按ID精确匹配
    ensure_column(
        "upload_records",
        "project_id",
        ddl_sqlite="ALTER TABLE upload_records ADD COLUMN project_id VARCHAR(36)",
        ddl_other="ALTER TABLE upload_records ADD COLUMN project_id VARCHAR(36) NULL",
    )
    ensure_column(
        "module_cascade_reminders",
        "project_id",
        ddl_sqlite="ALTER TABLE module_cascade_reminders ADD COLUMN project_id VARCHAR(36)",
        ddl_other="ALTER TABLE module_cascade_reminders ADD COLUMN project_id VARCHAR(36) NULL",
    )
    ensure_column(
        "generation_summary",
        "project_id",
        ddl_sqlite="ALTER TABLE generation_summary ADD COLUMN project_id VARCHAR(36)",
        ddl_other="ALTER TABLE generation_summary ADD COLUMN project_id VARCHAR(36) NULL",
    )

    # exam_bank_ingest_jobs：补充上游套题 ID（老库升级）
    ensure_column(
        "exam_bank_ingest_jobs",
        "upstream_set_id",
        ddl_sqlite="ALTER TABLE exam_bank_ingest_jobs ADD COLUMN upstream_set_id VARCHAR(128)",
        ddl_other="ALTER TABLE exam_bank_ingest_jobs ADD COLUMN upstream_set_id VARCHAR(128) NULL",
    )
    ensure_column(
        "exam_center_assignments",
        "difficulty",
        ddl_sqlite="ALTER TABLE exam_center_assignments ADD COLUMN difficulty VARCHAR(16)",
        ddl_other="ALTER TABLE exam_center_assignments ADD COLUMN difficulty VARCHAR(16) NULL",
    )
    ensure_column(
        "exam_center_assignments",
        "due_at",
        ddl_sqlite="ALTER TABLE exam_center_assignments ADD COLUMN due_at DATETIME",
        ddl_other="ALTER TABLE exam_center_assignments ADD COLUMN due_at DATETIME NULL",
    )
    # 考试类型：daily=日常；new_standard=新标发布（与体考类型 exam_track 正交）
    ensure_column(
        "exam_center_assignments",
        "exam_category",
        ddl_sqlite="ALTER TABLE exam_center_assignments ADD COLUMN exam_category VARCHAR(32)",
        ddl_other="ALTER TABLE exam_center_assignments ADD COLUMN exam_category VARCHAR(32) NULL",
    )
    ensure_column(
        "exam_center_activities",
        "exam_category",
        ddl_sqlite="ALTER TABLE exam_center_activities ADD COLUMN exam_category VARCHAR(32)",
        ddl_other="ALTER TABLE exam_center_activities ADD COLUMN exam_category VARCHAR(32) NULL",
    )
    ensure_column(
        "exam_attempts",
        "exam_category",
        ddl_sqlite="ALTER TABLE exam_attempts ADD COLUMN exam_category VARCHAR(32)",
        ddl_other="ALTER TABLE exam_attempts ADD COLUMN exam_category VARCHAR(32) NULL",
    )
    ensure_column(
        "exam_bank_ingest_jobs",
        "exam_category",
        ddl_sqlite="ALTER TABLE exam_bank_ingest_jobs ADD COLUMN exam_category VARCHAR(32)",
        ddl_other="ALTER TABLE exam_bank_ingest_jobs ADD COLUMN exam_category VARCHAR(32) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "cursor_repository",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN cursor_repository VARCHAR(512)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN cursor_repository VARCHAR(512) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "cursor_ref",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN cursor_ref VARCHAR(128)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN cursor_ref VARCHAR(128) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "api_key_encrypted_deepseek",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_deepseek BLOB",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_deepseek MEDIUMBLOB NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "api_key_encrypted_cursor",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_cursor BLOB",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_cursor MEDIUMBLOB NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "api_key_encrypted_tongyi",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_tongyi BLOB",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_tongyi MEDIUMBLOB NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "base_url_deepseek",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN base_url_deepseek VARCHAR(512)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN base_url_deepseek VARCHAR(512) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "base_url_cursor",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN base_url_cursor VARCHAR(512)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN base_url_cursor VARCHAR(512) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "base_url_tongyi",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN base_url_tongyi VARCHAR(512)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN base_url_tongyi VARCHAR(512) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "model_deepseek",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN model_deepseek VARCHAR(128)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN model_deepseek VARCHAR(128) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "model_cursor",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN model_cursor VARCHAR(128)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN model_cursor VARCHAR(128) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "model_tongyi",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN model_tongyi VARCHAR(128)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN model_tongyi VARCHAR(128) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "api_key_encrypted_openai",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_openai BLOB",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_openai MEDIUMBLOB NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "api_key_encrypted_claude",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_claude BLOB",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN api_key_encrypted_claude MEDIUMBLOB NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "base_url_openai",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN base_url_openai VARCHAR(512)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN base_url_openai VARCHAR(512) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "base_url_claude",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN base_url_claude VARCHAR(512)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN base_url_claude VARCHAR(512) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "model_openai",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN model_openai VARCHAR(128)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN model_openai VARCHAR(128) NULL",
    )
    ensure_column(
        "user_llm_credentials",
        "model_claude",
        ddl_sqlite="ALTER TABLE user_llm_credentials ADD COLUMN model_claude VARCHAR(128)",
        ddl_other="ALTER TABLE user_llm_credentials ADD COLUMN model_claude VARCHAR(128) NULL",
    )

    def migrate_user_llm_legacy_keys_split():
        """将旧版单列 api_key_encrypted 按 provider 拷入分栏密文（幂等）。"""
        if "user_llm_credentials" not in existing_tables:
            return
        insp2 = inspect(engine)
        cols2 = {c["name"] for c in insp2.get_columns("user_llm_credentials")}
        if "api_key_encrypted_deepseek" not in cols2:
            return
        pairs = (
            ("deepseek", "api_key_encrypted_deepseek"),
            ("cursor", "api_key_encrypted_cursor"),
            ("tongyi", "api_key_encrypted_tongyi"),
            ("openai", "api_key_encrypted_openai"),
            ("claude", "api_key_encrypted_claude"),
        )
        with engine.connect() as conn:
            for prov, col in pairs:
                if is_sqlite:
                    conn.execute(
                        text(
                            f"""
                            UPDATE user_llm_credentials
                            SET {col} = api_key_encrypted
                            WHERE api_key_encrypted IS NOT NULL
                              AND lower(trim(provider)) = :p
                              AND ({col} IS NULL OR length({col}) = 0)
                            """
                        ),
                        {"p": prov},
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            UPDATE user_llm_credentials
                            SET {col} = api_key_encrypted
                            WHERE api_key_encrypted IS NOT NULL
                              AND LOWER(TRIM(provider)) = :p
                              AND {col} IS NULL
                            """
                        ),
                        {"p": prov},
                    )
            conn.commit()

    migrate_user_llm_legacy_keys_split()

    def migrate_user_llm_legacy_base_model_split():
        """将旧版单列 base_url / model 按 provider 拷入分栏（幂等）。"""
        if "user_llm_credentials" not in existing_tables:
            return
        insp3 = inspect(engine)
        cols3 = {c["name"] for c in insp3.get_columns("user_llm_credentials")}
        if "base_url_deepseek" not in cols3:
            return
        pairs = (
            ("deepseek", "base_url_deepseek", "model_deepseek"),
            ("cursor", "base_url_cursor", "model_cursor"),
            ("tongyi", "base_url_tongyi", "model_tongyi"),
            ("openai", "base_url_openai", "model_openai"),
            ("claude", "base_url_claude", "model_claude"),
        )
        with engine.connect() as conn:
            for prov, bcol, mcol in pairs:
                if is_sqlite:
                    conn.execute(
                        text(
                            f"""
                            UPDATE user_llm_credentials
                            SET {bcol} = base_url
                            WHERE base_url IS NOT NULL AND trim(base_url) != ''
                              AND lower(trim(provider)) = :p
                              AND ({bcol} IS NULL OR trim({bcol}) = '')
                            """
                        ),
                        {"p": prov},
                    )
                    conn.execute(
                        text(
                            f"""
                            UPDATE user_llm_credentials
                            SET {mcol} = model
                            WHERE model IS NOT NULL AND trim(model) != ''
                              AND lower(trim(provider)) = :p
                              AND ({mcol} IS NULL OR trim({mcol}) = '')
                            """
                        ),
                        {"p": prov},
                    )
                else:
                    conn.execute(
                        text(
                            f"""
                            UPDATE user_llm_credentials
                            SET {bcol} = base_url
                            WHERE base_url IS NOT NULL AND TRIM(base_url) != ''
                              AND LOWER(TRIM(provider)) = :p
                              AND {bcol} IS NULL
                            """
                        ),
                        {"p": prov},
                    )
                    conn.execute(
                        text(
                            f"""
                            UPDATE user_llm_credentials
                            SET {mcol} = model
                            WHERE model IS NOT NULL AND TRIM(model) != ''
                              AND LOWER(TRIM(provider)) = :p
                              AND {mcol} IS NULL
                            """
                        ),
                        {"p": prov},
                    )
            conn.commit()

    migrate_user_llm_legacy_base_model_split()

    # 用户 LLM 凭据：旧库若缺表则保存失败或退回内存假象；显式建表与初稿任务表一致。
    insp_llm = inspect(engine)
    if "user_llm_credentials" not in insp_llm.get_table_names():
        from .models import UserLlmCredential

        UserLlmCredential.__table__.create(bind=engine, checkfirst=True)

    # 初稿任务历史：旧库若缺表会导致任务无法落库，重启后列表为空。
    insp_jobs = inspect(engine)
    if "draft_generation_jobs" not in insp_jobs.get_table_names():
        from .models import DraftGenerationJob

        DraftGenerationJob.__table__.create(bind=engine, checkfirst=True)

    # 审核 / 翻译 集成任务表：与初稿任务同构，缺表则建表。
    insp_audit = inspect(engine)
    if "audit_jobs" not in insp_audit.get_table_names():
        from .models import AuditJob

        AuditJob.__table__.create(bind=engine, checkfirst=True)

    insp_translation = inspect(engine)
    if "translation_jobs" not in insp_translation.get_table_names():
        from .models import TranslationJob

        TranslationJob.__table__.create(bind=engine, checkfirst=True)

    # DraftGenerationJob 增量列：source（区分初稿 / 审核后修改）。旧库若无该列会导致 ORM 写入 NULL。
    ensure_column(
        "draft_generation_jobs",
        "source",
        "ALTER TABLE draft_generation_jobs ADD COLUMN source TEXT",
        "ALTER TABLE draft_generation_jobs ADD COLUMN source VARCHAR(32)",
    )
    ensure_column(
        "draft_generation_jobs",
        "integration_scope",
        "ALTER TABLE draft_generation_jobs ADD COLUMN integration_scope TEXT",
        "ALTER TABLE draft_generation_jobs ADD COLUMN integration_scope VARCHAR(16)",
    )
    ensure_column(
        "audit_jobs",
        "integration_scope",
        "ALTER TABLE audit_jobs ADD COLUMN integration_scope TEXT",
        "ALTER TABLE audit_jobs ADD COLUMN integration_scope VARCHAR(16)",
    )
    ensure_column(
        "translation_jobs",
        "integration_scope",
        "ALTER TABLE translation_jobs ADD COLUMN integration_scope TEXT",
        "ALTER TABLE translation_jobs ADD COLUMN integration_scope VARCHAR(16)",
    )

    # UploadRecord 增量列：last_audit_*（aicheckword 审核集成的最近一次报告摘要缓存）。
    ensure_column(
        "upload_records",
        "last_audit_report_id",
        "ALTER TABLE upload_records ADD COLUMN last_audit_report_id INTEGER",
        "ALTER TABLE upload_records ADD COLUMN last_audit_report_id INT",
    )
    ensure_column(
        "upload_records",
        "last_audit_mode",
        "ALTER TABLE upload_records ADD COLUMN last_audit_mode TEXT",
        "ALTER TABLE upload_records ADD COLUMN last_audit_mode VARCHAR(16)",
    )
    ensure_column(
        "upload_records",
        "last_audit_severity_json",
        "ALTER TABLE upload_records ADD COLUMN last_audit_severity_json TEXT",
        "ALTER TABLE upload_records ADD COLUMN last_audit_severity_json JSON",
    )
    ensure_column(
        "upload_records",
        "last_audit_at",
        "ALTER TABLE upload_records ADD COLUMN last_audit_at DATETIME",
        "ALTER TABLE upload_records ADD COLUMN last_audit_at DATETIME",
    )

    # 任务类型一级分类（文件型/事项型）：历史行回填为 file
    ensure_column(
        "task_type_configs",
        "category",
        "ALTER TABLE task_type_configs ADD COLUMN category VARCHAR(16) NOT NULL DEFAULT 'file'",
        "ALTER TABLE task_type_configs ADD COLUMN category VARCHAR(16) NOT NULL DEFAULT 'file'",
    )
    if "task_type_configs" in existing_tables:
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    "UPDATE task_type_configs SET category='file' "
                    "WHERE category IS NULL OR TRIM(category)=''"
                ))
                conn.commit()
        except Exception:
            pass

    # 公司级项目总览 / RBAC
    ensure_column(
        "users",
        "admin_role",
        "ALTER TABLE users ADD COLUMN admin_role VARCHAR(16) NOT NULL DEFAULT 'none'",
        "ALTER TABLE users ADD COLUMN admin_role VARCHAR(16) NOT NULL DEFAULT 'none'",
    )
    for col, ddl_s, ddl_m in (
        (
            "product_type",
            "ALTER TABLE projects ADD COLUMN product_type VARCHAR(128)",
            "ALTER TABLE projects ADD COLUMN product_type VARCHAR(128)",
        ),
        (
            "assigned_team_id",
            "ALTER TABLE projects ADD COLUMN assigned_team_id VARCHAR(36)",
            "ALTER TABLE projects ADD COLUMN assigned_team_id VARCHAR(36)",
        ),
        (
            "expected_certification_date",
            "ALTER TABLE projects ADD COLUMN expected_certification_date DATE",
            "ALTER TABLE projects ADD COLUMN expected_certification_date DATE",
        ),
        (
            "expected_submission_date",
            "ALTER TABLE projects ADD COLUMN expected_submission_date DATE",
            "ALTER TABLE projects ADD COLUMN expected_submission_date DATE",
        ),
        (
            "progress_description",
            "ALTER TABLE projects ADD COLUMN progress_description TEXT",
            "ALTER TABLE projects ADD COLUMN progress_description TEXT",
        ),
        (
            "registration_scope",
            "ALTER TABLE projects ADD COLUMN registration_scope VARCHAR(16) NOT NULL DEFAULT 'legacy'",
            "ALTER TABLE projects ADD COLUMN registration_scope VARCHAR(16) NOT NULL DEFAULT 'legacy'",
        ),
        (
            "created_by_user_id",
            "ALTER TABLE projects ADD COLUMN created_by_user_id VARCHAR(36)",
            "ALTER TABLE projects ADD COLUMN created_by_user_id VARCHAR(36)",
        ),
        (
            "updated_by",
            "ALTER TABLE projects ADD COLUMN updated_by VARCHAR(128)",
            "ALTER TABLE projects ADD COLUMN updated_by VARCHAR(128)",
        ),
        (
            "progress_updated_at",
            "ALTER TABLE projects ADD COLUMN progress_updated_at DATETIME",
            "ALTER TABLE projects ADD COLUMN progress_updated_at DATETIME",
        ),
        (
            "project_code",
            "ALTER TABLE projects ADD COLUMN project_code VARCHAR(128)",
            "ALTER TABLE projects ADD COLUMN project_code VARCHAR(128)",
        ),
    ):
        ensure_column("projects", col, ddl_s, ddl_m)

    try:
        from .models import Project, UploadRecord

        for p in Project.query.filter(
            (Project.project_code.is_(None)) | (Project.project_code == "")
        ).all():
            ur = (
                UploadRecord.query.filter_by(project_id=p.id)
                .filter(
                    UploadRecord.project_code.isnot(None),
                    UploadRecord.project_code != "",
                )
                .order_by(UploadRecord.updated_at.desc())
                .first()
            )
            if ur and (ur.project_code or "").strip():
                p.project_code = ur.project_code.strip()
        db.session.commit()
    except Exception:
        db.session.rollback()

    insp_rbac = inspect(engine)
    rbac_tables = insp_rbac.get_table_names()
    if "project_teams" not in rbac_tables:
        from .models import ProjectTeam

        ProjectTeam.__table__.create(bind=engine, checkfirst=True)
    if "organizations" not in rbac_tables:
        from .models import Organization

        Organization.__table__.create(bind=engine, checkfirst=True)
    if "user_organization_memberships" not in rbac_tables:
        from .models import UserOrganizationMembership

        UserOrganizationMembership.__table__.create(bind=engine, checkfirst=True)
    ensure_column(
        "project_teams",
        "dingtalk_webhook",
        "ALTER TABLE project_teams ADD COLUMN dingtalk_webhook VARCHAR(512)",
        "ALTER TABLE project_teams ADD COLUMN dingtalk_webhook VARCHAR(512)",
    )
    ensure_column(
        "project_teams",
        "dingtalk_secret",
        "ALTER TABLE project_teams ADD COLUMN dingtalk_secret VARCHAR(256)",
        "ALTER TABLE project_teams ADD COLUMN dingtalk_secret VARCHAR(256)",
    )
    ensure_column(
        "project_teams",
        "organization_id",
        "ALTER TABLE project_teams ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE project_teams ADD COLUMN organization_id VARCHAR(36)",
    )
    if "user_team_memberships" not in rbac_tables:
        from .models import UserTeamMembership

        UserTeamMembership.__table__.create(bind=engine, checkfirst=True)

    if "company_projects" not in rbac_tables:
        from .models import CompanyProject

        CompanyProject.__table__.create(bind=engine, checkfirst=True)

    ensure_column(
        "company_projects",
        "is_starred",
        ddl_sqlite="ALTER TABLE company_projects ADD COLUMN is_starred INTEGER NOT NULL DEFAULT 0",
        ddl_other="ALTER TABLE company_projects ADD COLUMN is_starred TINYINT(1) NOT NULL DEFAULT 0",
    )
    ensure_column(
        "company_projects",
        "registration_owner",
        ddl_sqlite="ALTER TABLE company_projects ADD COLUMN registration_owner VARCHAR(128)",
        ddl_other="ALTER TABLE company_projects ADD COLUMN registration_owner VARCHAR(128) NULL",
    )
    ensure_column(
        "company_projects",
        "organization_id",
        ddl_sqlite="ALTER TABLE company_projects ADD COLUMN organization_id VARCHAR(36)",
        ddl_other="ALTER TABLE company_projects ADD COLUMN organization_id VARCHAR(36) NULL",
    )

    ensure_column(
        "users",
        "can_access_company_registry",
        ddl_sqlite="ALTER TABLE users ADD COLUMN can_access_company_registry INTEGER NOT NULL DEFAULT 0",
        ddl_other="ALTER TABLE users ADD COLUMN can_access_company_registry TINYINT(1) NOT NULL DEFAULT 0",
    )
    ensure_column(
        "users",
        "feature_permissions_json",
        ddl_sqlite="ALTER TABLE users ADD COLUMN feature_permissions_json TEXT",
        ddl_other="ALTER TABLE users ADD COLUMN feature_permissions_json JSON NULL",
    )
    insp_doc_control = inspect(engine)
    doc_control_tables = insp_doc_control.get_table_names()
    if "numbering_schemes" not in doc_control_tables:
        from .models import NumberingScheme

        NumberingScheme.__table__.create(bind=engine, checkfirst=True)
    if "controlled_documents" not in doc_control_tables:
        from .models import ControlledDocument

        ControlledDocument.__table__.create(bind=engine, checkfirst=True)
    if "number_allocations" not in doc_control_tables:
        from .models import NumberAllocation

        NumberAllocation.__table__.create(bind=engine, checkfirst=True)
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(
                    text(
                        "UPDATE controlled_documents SET status='controlled' "
                        "WHERE status IS NULL OR TRIM(status)='' OR status='active'"
                    )
                )
            else:
                conn.execute(
                    text(
                        "UPDATE controlled_documents SET status='controlled' "
                        "WHERE status IS NULL OR status='' OR status='active'"
                    )
                )
    except Exception:
        pass
    ensure_column(
        "controlled_documents",
        "sheet_category",
        ddl_sqlite="ALTER TABLE controlled_documents ADD COLUMN sheet_category VARCHAR(64)",
        ddl_other="ALTER TABLE controlled_documents ADD COLUMN sheet_category VARCHAR(64) NULL",
    )
    ensure_column(
        "controlled_documents",
        "project_name",
        ddl_sqlite="ALTER TABLE controlled_documents ADD COLUMN project_name VARCHAR(255)",
        ddl_other="ALTER TABLE controlled_documents ADD COLUMN project_name VARCHAR(255) NULL",
    )
    ensure_column(
        "controlled_documents",
        "registered_country",
        ddl_sqlite="ALTER TABLE controlled_documents ADD COLUMN registered_country VARCHAR(64)",
        ddl_other="ALTER TABLE controlled_documents ADD COLUMN registered_country VARCHAR(64) NULL",
    )
    ensure_column(
        "controlled_documents",
        "registration_submitted",
        ddl_sqlite="ALTER TABLE controlled_documents ADD COLUMN registration_submitted INTEGER NOT NULL DEFAULT 0",
        ddl_other="ALTER TABLE controlled_documents ADD COLUMN registration_submitted TINYINT(1) NOT NULL DEFAULT 0",
    )
    ensure_column(
        "controlled_documents",
        "title_en",
        ddl_sqlite="ALTER TABLE controlled_documents ADD COLUMN title_en VARCHAR(255)",
        ddl_other="ALTER TABLE controlled_documents ADD COLUMN title_en VARCHAR(255) NULL",
    )
    ensure_column(
        "controlled_documents",
        "excel_row_index",
        ddl_sqlite="ALTER TABLE controlled_documents ADD COLUMN excel_row_index INTEGER",
        ddl_other="ALTER TABLE controlled_documents ADD COLUMN excel_row_index INT NULL",
    )
    ensure_column(
        "controlled_documents",
        "registration_excel_row_index",
        ddl_sqlite="ALTER TABLE controlled_documents ADD COLUMN registration_excel_row_index INTEGER",
        ddl_other="ALTER TABLE controlled_documents ADD COLUMN registration_excel_row_index INT NULL",
    )
    if "document_control_import_logs" not in doc_control_tables:
        from .models import DocumentControlImportLog

        DocumentControlImportLog.__table__.create(bind=engine, checkfirst=True)
    if "document_title_translation_cache" not in doc_control_tables:
        from .models import DocumentTitleTranslationCache

        DocumentTitleTranslationCache.__table__.create(bind=engine, checkfirst=True)
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(
                    text(
                        "UPDATE controlled_documents "
                        "SET excel_row_index = ("
                        "  SELECT l.row_index FROM document_control_import_logs l "
                        "  WHERE l.controlled_document_id = controlled_documents.id "
                        "    AND l.row_index IS NOT NULL "
                        "    AND l.event_type IN ('import_success', 'import_update') "
                        "    AND (l.sheet_name IS NULL OR l.sheet_name = controlled_documents.sheet_category) "
                        "  ORDER BY l.created_at DESC LIMIT 1"
                        ") "
                        "WHERE excel_row_index IS NULL AND EXISTS ("
                        "  SELECT 1 FROM document_control_import_logs l "
                        "  WHERE l.controlled_document_id = controlled_documents.id "
                        "    AND l.row_index IS NOT NULL "
                        "    AND l.event_type IN ('import_success', 'import_update')"
                        ")"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE controlled_documents "
                        "SET excel_row_index = ("
                        "  SELECT l.row_index FROM document_control_import_logs l "
                        "  WHERE l.controlled_document_id = controlled_documents.id "
                        "    AND l.row_index IS NOT NULL "
                        "    AND l.event_type IN ('import_success', 'import_update') "
                        "    AND l.sheet_name = controlled_documents.sheet_category "
                        "  ORDER BY l.created_at DESC LIMIT 1"
                        ") "
                        "WHERE sheet_category IS NOT NULL AND sheet_category != '' AND EXISTS ("
                        "  SELECT 1 FROM document_control_import_logs l "
                        "  WHERE l.controlled_document_id = controlled_documents.id "
                        "    AND l.row_index IS NOT NULL "
                        "    AND l.event_type IN ('import_success', 'import_update') "
                        "    AND l.sheet_name = controlled_documents.sheet_category"
                        ")"
                    )
                )
            elif engine.dialect.name == "mysql":
                conn.execute(
                    text(
                        "UPDATE controlled_documents cd "
                        "INNER JOIN ("
                        "  SELECT l.controlled_document_id, l.row_index "
                        "  FROM document_control_import_logs l "
                        "  INNER JOIN ("
                        "    SELECT controlled_document_id, MAX(created_at) AS mx "
                        "    FROM document_control_import_logs "
                        "    WHERE controlled_document_id IS NOT NULL "
                        "      AND row_index IS NOT NULL "
                        "      AND event_type IN ('import_success', 'import_update') "
                        "    GROUP BY controlled_document_id"
                        "  ) latest ON l.controlled_document_id = latest.controlled_document_id "
                        "    AND l.created_at = latest.mx"
                        ") src ON cd.id = src.controlled_document_id "
                        "SET cd.excel_row_index = src.row_index "
                        "WHERE cd.excel_row_index IS NULL"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE controlled_documents cd "
                        "INNER JOIN ("
                        "  SELECT l.controlled_document_id, l.row_index "
                        "  FROM document_control_import_logs l "
                        "  INNER JOIN ("
                        "    SELECT l2.controlled_document_id, MAX(l2.created_at) AS mx "
                        "    FROM document_control_import_logs l2 "
                        "    WHERE l2.controlled_document_id IS NOT NULL "
                        "      AND l2.row_index IS NOT NULL "
                        "      AND l2.event_type IN ('import_success', 'import_update') "
                        "    GROUP BY l2.controlled_document_id"
                        "  ) latest ON l.controlled_document_id = latest.controlled_document_id "
                        "    AND l.created_at = latest.mx "
                        "  WHERE l.sheet_name = cd.sheet_category"
                        ") src ON cd.id = src.controlled_document_id "
                        "SET cd.excel_row_index = src.row_index "
                        "WHERE cd.sheet_category IS NOT NULL AND cd.sheet_category != ''"
                    )
                )
    except Exception:
        pass
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(
                    text(
                        "UPDATE controlled_documents "
                        "SET registration_excel_row_index = excel_row_index "
                        "WHERE sheet_category = '注册文件' "
                        "  AND registration_excel_row_index IS NULL "
                        "  AND excel_row_index IS NOT NULL"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE controlled_documents "
                        "SET registration_excel_row_index = NULL "
                        "WHERE sheet_category IS NOT NULL AND sheet_category != '注册文件'"
                    )
                )
            elif engine.dialect.name == "mysql":
                conn.execute(
                    text(
                        "UPDATE controlled_documents "
                        "SET registration_excel_row_index = excel_row_index "
                        "WHERE sheet_category = '注册文件' "
                        "  AND registration_excel_row_index IS NULL "
                        "  AND excel_row_index IS NOT NULL"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE controlled_documents "
                        "SET registration_excel_row_index = NULL "
                        "WHERE sheet_category IS NOT NULL AND sheet_category != '注册文件'"
                    )
                )
    except Exception:
        pass
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(
                    text("DROP INDEX IF EXISTS uq_controlled_document_org_norm_number")
                )
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_controlled_doc_org_norm_controlled "
                        "ON controlled_documents (organization_id, normalized_document_number) "
                        "WHERE status = 'controlled'"
                    )
                )
            elif engine.dialect.name == "mysql":
                try:
                    conn.execute(
                        text(
                            "ALTER TABLE controlled_documents "
                            "DROP INDEX uq_controlled_document_org_norm_number"
                        )
                    )
                except Exception:
                    pass
    except Exception:
        pass
    ensure_column(
        "user_feedback",
        "aiword_version",
        ddl_sqlite="ALTER TABLE user_feedback ADD COLUMN aiword_version TEXT",
        ddl_other="ALTER TABLE user_feedback ADD COLUMN aiword_version VARCHAR(32) NULL",
    )
    ensure_column(
        "user_feedback",
        "aicheckword_version",
        ddl_sqlite="ALTER TABLE user_feedback ADD COLUMN aicheckword_version TEXT",
        ddl_other="ALTER TABLE user_feedback ADD COLUMN aicheckword_version VARCHAR(32) NULL",
    )

    insp_rbac2 = inspect(engine)
    rbac_tables2 = insp_rbac2.get_table_names()
    if "user_country_scopes" not in rbac_tables2:
        from .models import UserCountryScope

        UserCountryScope.__table__.create(bind=engine, checkfirst=True)

    if "registered_country_dict" not in rbac_tables2:
        from .models import RegisteredCountry

        RegisteredCountry.__table__.create(bind=engine, checkfirst=True)

    try:
        from .registered_countries import bootstrap_registered_countries_from_data

        bootstrap_registered_countries_from_data()
    except Exception:
        pass

    ensure_column(
        "projects",
        "company_project_id",
        "ALTER TABLE projects ADD COLUMN company_project_id VARCHAR(36)",
        "ALTER TABLE projects ADD COLUMN company_project_id VARCHAR(36)",
    )
    ensure_column(
        "projects",
        "organization_id",
        "ALTER TABLE projects ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE projects ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "upload_records",
        "organization_id",
        "ALTER TABLE upload_records ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE upload_records ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "draft_generation_jobs",
        "organization_id",
        "ALTER TABLE draft_generation_jobs ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE draft_generation_jobs ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "audit_jobs",
        "organization_id",
        "ALTER TABLE audit_jobs ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE audit_jobs ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "translation_jobs",
        "organization_id",
        "ALTER TABLE translation_jobs ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE translation_jobs ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "exam_center_assignments",
        "organization_id",
        "ALTER TABLE exam_center_assignments ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE exam_center_assignments ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "exam_center_activities",
        "organization_id",
        "ALTER TABLE exam_center_activities ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE exam_center_activities ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "exam_attempts",
        "organization_id",
        "ALTER TABLE exam_attempts ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE exam_attempts ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "exam_bank_ingest_jobs",
        "organization_id",
        "ALTER TABLE exam_bank_ingest_jobs ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE exam_bank_ingest_jobs ADD COLUMN organization_id VARCHAR(36)",
    )
    ensure_column(
        "exam_set_review_jobs",
        "organization_id",
        "ALTER TABLE exam_set_review_jobs ADD COLUMN organization_id VARCHAR(36)",
        "ALTER TABLE exam_set_review_jobs ADD COLUMN organization_id VARCHAR(36)",
    )

    def _table_needs_org_backfill(conn, table_name: str) -> bool:
        try:
            row = conn.execute(
                text(
                    f"SELECT 1 FROM {table_name} "
                    "WHERE organization_id IS NULL OR organization_id = '' LIMIT 1"
                )
            ).fetchone()
            return bool(row)
        except Exception:
            return False

    def _sync_all_organizations_to_aicheckword():
        """启动后把所有 organizations 推送到 aicheckword companies（幂等 upsert）。

        - 失败仅日志，不阻断启动
        - 仅在 FEATURE_MULTI_TENANT 开启时才执行（避免单租户场景产生无谓的对外请求）
        """
        try:
            from . import app_settings as _aps
            if not _aps.is_multi_tenant_enabled():
                return
        except Exception:
            return
        try:
            from . import _integration_common as _ic
        except Exception:
            return
        base = _ic.integration_api_base()
        if not base:
            return
        try:
            import requests as _rq
        except Exception:
            return
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT id, name, slug, knowledge_collection, is_active, is_default "
                        "FROM organizations"
                    )
                ).fetchall()
        except Exception:
            return
        if not rows:
            return
        try:
            from startup_util import startup_note as _sn
        except Exception:
            _sn = lambda *_a, **_k: None
        try:
            _sn(f"同步 {len(rows)} 家公司到 aicheckword …")
        except Exception:
            pass
        ok_cnt = 0
        err_cnt = 0
        for r in rows:
            try:
                oid = str(r[0] or "").strip()
                if not oid:
                    continue
                _rq.post(
                    f"{base.rstrip('/')}/admin/companies/sync",
                    json={
                        "aiword_company_id": oid,
                        "name": str(r[1] or "").strip(),
                        "slug": str(r[2] or "").strip(),
                        "knowledge_collection": (str(r[3] or "").strip() or "regulations"),
                        "is_active": bool(r[4]),
                        "is_default": bool(r[5]),
                    },
                    headers=_ic.upstream_headers(
                        for_multipart=False, organization_id=oid
                    ),
                    timeout=_ic.integration_requests_timeout(read_seconds=15),
                )
                ok_cnt += 1
            except Exception:
                err_cnt += 1
        try:
            _sn(
                f"公司映射同步完成：成功 {ok_cnt} / 失败 {err_cnt}"
            )
        except Exception:
            pass

    def seed_default_organization_and_backfill():
        from .historical_migration import ensure_historical_migration_gate

        if not ensure_historical_migration_gate(engine):
            return
        org_id = ""
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id FROM organizations WHERE is_default = 1 "
                    "ORDER BY created_at ASC LIMIT 1"
                )
            ).fetchone()
            if row and row[0]:
                org_id = str(row[0]).strip()
            if not org_id:
                row = conn.execute(
                    text(
                        "SELECT id FROM organizations WHERE knowledge_collection = :c "
                        "ORDER BY created_at ASC LIMIT 1"
                    ),
                    {"c": "regulations"},
                ).fetchone()
                if row and row[0]:
                    org_id = str(row[0]).strip()
            if not org_id:
                org_id = str(uuid.uuid4())
                conn.execute(
                    text(
                        "INSERT INTO organizations "
                        "(id, name, slug, knowledge_collection, is_active, is_default, created_at, updated_at) "
                        "VALUES (:id, :name, :slug, :kc, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": org_id,
                        "name": "南京鱼跃软件技术有限公司",
                        "slug": "nanjing-yuyue-software",
                        "kc": "regulations",
                    },
                )
            else:
                conn.execute(
                    text(
                        "UPDATE organizations SET is_default = CASE WHEN id = :id THEN 1 ELSE is_default END"
                    ),
                    {"id": org_id},
                )

            # 仅对「完全没有任何公司绑定」的账号补默认公司；勿向已配置其它公司的账号追加默认公司。
            miss_rows = conn.execute(
                text(
                    "SELECT u.id FROM users u "
                    "WHERE NOT EXISTS ("
                    "SELECT 1 FROM user_organization_memberships m "
                    "WHERE m.user_id = u.id"
                    ")"
                )
            ).fetchall()
            for row_u in miss_rows:
                uid = str((row_u[0] or "")).strip()
                if not uid:
                    continue
                conn.execute(
                    text(
                        "INSERT INTO user_organization_memberships "
                        "(id, user_id, organization_id, created_at) "
                        "VALUES (:id, :uid, :oid, CURRENT_TIMESTAMP)"
                    ),
                    {"id": str(uuid.uuid4()), "uid": uid, "oid": org_id},
                )
            backfill_tables = (
                "project_teams",
                "company_projects",
                "projects",
                "upload_records",
                "draft_generation_jobs",
                "audit_jobs",
                "translation_jobs",
                "exam_center_assignments",
                "exam_center_activities",
                "exam_attempts",
                "exam_bank_ingest_jobs",
                "exam_set_review_jobs",
            )
            needs_backfill = bool(miss_rows) or any(
                _table_needs_org_backfill(conn, t) for t in backfill_tables
            )
            if needs_backfill:
                for table_name in backfill_tables:
                    if not _table_needs_org_backfill(conn, table_name):
                        continue
                    conn.execute(
                        text(
                            f"UPDATE {table_name} SET organization_id = :oid "
                            "WHERE organization_id IS NULL OR organization_id = ''"
                        ),
                        {"oid": org_id},
                    )
            conn.commit()

    seed_default_organization_and_backfill()

    try:
        _sync_all_organizations_to_aicheckword()
    except Exception:
        try:
            app.logger.exception("startup sync organizations to aicheckword failed")
        except Exception:
            pass

    if "projects" in existing_tables:
        try:
            with engine.connect() as conn:
                conn.execute(text(
                    "UPDATE projects SET registration_scope='legacy' "
                    "WHERE registration_scope IS NULL OR TRIM(registration_scope)=''"
                ))
                conn.commit()
        except Exception:
            pass


def init_default_configs():
    """初始化默认的配置项数据"""
    from .models import TaskTypeConfig, CompletionStatusConfig, AuditStatusConfig, NotifyTemplateConfig, AppConfig, TASK_TYPE_CATEGORY_FILE

    default_task_types = [
        ("初稿待编写", 1),
        ("初稿审核待修改", 2),
        ("已完成待打印签字", 3),
    ]
    
    default_completion_statuses = [
        ("已完成初稿", 1),
        ("有疑问", 2),
        ("已完成终稿", 3),
        ("已打印签字", 4),
    ]
    
    default_audit_statuses = [
        ("待审核", 1),
        ("审核通过", 2),
        ("审核不通过待修改", 3),
    ]
    
    default_notify_templates = [
        ("project_reminder", "按项目催办通知", 
         "【项目任务催办】\n\n项目：{project_name}\n\n未完成任务数：{pending_count}\n\n请以下人员尽快完成：{assignees}\n\n\n未完成列表（按字段换行，含文档地址、截止日期、影响业务方、产品、国家）：\n{task_list_with_links}\n\n页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）\n\n请抓紧处理！"),
        ("author_reminder", "按人员催办通知",
         "【个人任务催办】\n致：{author}\n您有 {pending_count} 个任务待完成：\n{task_list}\n\n请抓紧处理！"),
        ("project_author_reminder", "按项目+人员催办通知",
         "【个人任务催办】\n致：{author}\n\n项目：{project_name}\n\n您在该项目下有 {pending_count} 个任务待完成：\n\n{task_list}\n\n请抓紧处理！"),
        ("single_task_reminder", "单条任务催办通知",
         "【任务催办】\n致：{author}\n\n- {title}\n - 截止日期：{due_date}\n - 影响业务方：{business_side}\n - 产品：{product}\n - 国家：{country}\n - 项目编号：{project_code}\n - 项目备注：{project_notes}\n - 文件版本号：{file_version}\n - 文档体现日期：{document_display_date}\n - 审核人员：{reviewer}\n - 批准人员：{approver}\n - 文档地址：{doc_link_md}\n\n请抓紧处理！"),
    ]
    
    for name, order in default_task_types:
        existing = TaskTypeConfig.query.filter_by(name=name).first()
        if not existing:
            db.session.add(TaskTypeConfig(name=name, sort_order=order, category=TASK_TYPE_CATEGORY_FILE))
        elif not (existing.category or "").strip():
            existing.category = TASK_TYPE_CATEGORY_FILE
            db.session.add(existing)
    
    for name, order in default_completion_statuses:
        existing = CompletionStatusConfig.query.filter_by(name=name).first()
        if not existing:
            db.session.add(CompletionStatusConfig(name=name, sort_order=order))
    
    for name, order in default_audit_statuses:
        existing = AuditStatusConfig.query.filter_by(name=name).first()
        if not existing:
            db.session.add(AuditStatusConfig(name=name, sort_order=order))
    
    for key, name, content in default_notify_templates:
        existing = NotifyTemplateConfig.query.filter_by(template_key=key).first()
        if not existing:
            db.session.add(NotifyTemplateConfig(
                template_key=key, template_name=name, template_content=content
            ))
        elif key == "project_reminder":
            existing.template_content = content
            existing.template_name = name
            db.session.add(existing)
        elif key == "single_task_reminder" and "- **{title}**" in (existing.template_content or ""):
            existing.template_content = content
            existing.template_name = name
            db.session.add(existing)

    default_schedule = [
        ("SCHEDULE_WEEKLY_REMINDER", "thu 16:00"),
        ("SCHEDULE_OVERDUE_REMINDER", "15:00"),
        ("SCHEDULE_PROJECT_STATS", "mon,wed,fri 9:30"),
    ]
    for config_key, default_value in default_schedule:
        existing = AppConfig.query.filter_by(config_key=config_key).first()
        if not existing:
            db.session.add(AppConfig(config_key=config_key, config_value=default_value))

    existing_delay = AppConfig.query.filter_by(config_key="MODULE_CASCADE_DELAY_MINUTES").first()
    if not existing_delay:
        db.session.add(AppConfig(config_key="MODULE_CASCADE_DELAY_MINUTES", config_value="5"))

    from .app_settings import SYSTEM_CONFIG_KEYS

    existing_cfg_keys = {
        row[0]
        for row in db.session.query(AppConfig.config_key).all()
        if row and row[0]
    }
    for sk, _, _ in SYSTEM_CONFIG_KEYS:
        if sk not in existing_cfg_keys:
            db.session.add(AppConfig(config_key=sk, config_value=""))

    db.session.commit()


def create_app() -> Flask:
    """Application factory for the AI Word web suite."""
    from startup_util import startup_note

    startup_note("create_app: 加载配置与目录…")
    project_root = Path(__file__).resolve().parent.parent
    
    # 尝试从 .env 加载环境变量（若已安装 python-dotenv）
    try:
        from dotenv import load_dotenv

        _dotenv_raw = (os.environ.get("AIWORD_DOTENV_PATH") or "").strip()
        if _dotenv_raw:
            _dotenv_path = Path(_dotenv_raw)
            if not _dotenv_path.is_absolute():
                _dotenv_path = project_root / _dotenv_raw
        else:
            _dotenv_path = project_root / ".env"
        load_dotenv(_dotenv_path)
    except ImportError:
        pass

    from .environment_profile import apply_environment_profile, is_env_separation_enabled

    _active_env = apply_environment_profile(project_root)
    if is_env_separation_enabled():
        startup_note(f"环境分离已开启，AIWORD_ENV={_active_env}")
    else:
        startup_note("环境分离已关闭（FEATURE_ENV_SEPARATION=0）")

    # 从配置文件读取可选项（config.json 在项目根目录；若不存在则尝试 config.json.example）
    def _config_file_value(key: str, default: str = "") -> str:
        for name in ("config.json", "config.json.example"):
            config_path = project_root / name
            if not config_path.exists():
                continue
            try:
                import json
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                val = data.get(key)
                v = (str(val).replace("\ufeff", "").strip() if val is not None else "") or default
                if name == "config.json" or v:
                    return v
            except Exception:
                continue
        return default

    _uploads_name = (os.environ.get("AIWORD_UPLOADS_DIR") or "uploads").strip() or "uploads"
    _outputs_name = (os.environ.get("AIWORD_OUTPUTS_DIR") or "outputs").strip() or "outputs"
    uploads_dir = project_root / _uploads_name
    uploads_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir = project_root / _outputs_name
    outputs_dir.mkdir(parents=True, exist_ok=True)

    _web_templates = project_root / "web" / "templates"
    _pkg_templates = Path(__file__).resolve().parent / "templates"
    _template_paths: list[str] = []
    if _web_templates.is_dir():
        _template_paths.append(str(_web_templates))
    if _pkg_templates.is_dir():
        _template_paths.append(str(_pkg_templates))
    if not _template_paths:
        raise RuntimeError(
            "未找到模板目录：需要存在 web/templates 或 webapp/templates。"
            "请完整部署项目（含 web 目录），或更新代码使 webapp/templates 随包发布。"
        )
    from .app_settings import resolve_instance_dir

    _instance_dir = resolve_instance_dir(project_root)
    _instance_dir.mkdir(parents=True, exist_ok=True)
    app = Flask(
        __name__,
        instance_path=str(_instance_dir),
        template_folder=_template_paths[0],
        static_folder=str(project_root / "web" / "static"),
    )
    if len(_template_paths) > 1:
        app.jinja_loader = ChoiceLoader(
            [FileSystemLoader(p) for p in _template_paths]
        )

    # 已注释 SQLite 入口，避免搞混当前连接的数据库。当前仅使用 MySQL。
    # default_db_uri = "sqlite:///" + str(project_root / "data" / "aiword.db")
    # Docker/生产：通过 AIWORD_BOOTSTRAP_DATABASE_URL 或 instance/database_url.txt 引导，避免硬编码内网地址
    default_db_uri = (os.environ.get("AIWORD_BOOTSTRAP_DATABASE_URL") or "").strip()
    from .app_settings import normalize_database_uri_for_engine, resolve_database_uri

    # 数据库 URI：以页面4 系统配置 (app_configs) 为准；不读取环境变量 DATABASE_URL
    db_uri = normalize_database_uri_for_engine(
        resolve_database_uri(project_root, default_db_uri)
    )

    if db_uri.startswith("mysql"):
        try:
            from sqlalchemy import create_engine, text as _text
            _parts = db_uri.rsplit("/", 1)
            _db_name = _parts[1].split("?")[0] if len(_parts) > 1 else "aiword"
            _server_uri = _parts[0] + "/"
            _tmp_eng = create_engine(_server_uri)
            with _tmp_eng.connect() as _conn:
                _conn.execute(_text(f"CREATE DATABASE IF NOT EXISTS `{_db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
                _conn.commit()
            _tmp_eng.dispose()
        except Exception as _e:
            import logging
            logging.getLogger(__name__).warning("自动创建MySQL数据库失败: %s", _e)

    # 网络断开后恢复：缩短连接回收时间，连接前 ping，连接错误时清空连接池便于下次重连
    _engine_opts = {
        "pool_recycle": 300,
        "pool_pre_ping": True,
    }

    app.config.update(
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS=_engine_opts,
        # 主前端脚本/样式：避免浏览器长期缓存 + 304 一直沿用旧 app.js（内网部署常见）
        SEND_FILE_MAX_AGE=0,
        UPLOAD_FOLDER=str(uploads_dir),
        OUTPUT_FOLDER=str(outputs_dir),
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,  # 25 MB safety cap
        JSON_SORT_KEYS=False,
        DINGTALK_WEBHOOK="",
        DINGTALK_SECRET="",
        SECRET_KEY="aiword-dev-secret-key-change-in-production",
        BASE_URL="",
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        PAGE13_ACCESS_PASSWORD=None,
        INTEGRATION_SECRET="",
    )
    app.json.ensure_ascii = False

    def _static_assets_version() -> int:
        """用于模板里给 app.js/app.css 加查询参数，避免多机/浏览器强缓存导致“拉代码了但页面不变”。"""
        v = 0
        for rel in (
            "js/app.js",
            "js/document_control.js",
            "js/exam_center.js",
            "js/draft_gen.js",
            "js/literature_search.js",
            "css/app.css",
            "data/iso13485_document_name_pairs.json",
            "vendor/bootstrap-5.3.3/bootstrap.min.css",
            "vendor/bootstrap-5.3.3/bootstrap.bundle.min.js",
        ):
            p = project_root / "web" / "static" / rel
            try:
                v = max(v, int(p.stat().st_mtime))
            except OSError:
                pass
        return v

    @app.context_processor
    def _inject_static_version():
        return {"static_version": _static_assets_version()}

    @app.context_processor
    def _inject_feature_flags():
        """注入功能开关（仅超级管理员全开），供模板 {% if feature_flags.xxx %} 使用。"""
        try:
            from .app_settings import effective_feature_flags_for_request

            flags = effective_feature_flags_for_request(app)
        except Exception:
            flags = {}
        return {"feature_flags": flags}

    @app.context_processor
    def _inject_company_registry():
        try:
            from .authz import (
                company_registry_enabled,
                current_admin_role,
                is_company_admin,
                is_company_registry_user,
                is_page13_super_admin,
                is_project_admin,
                nav_show_page0,
                nav_show_page123_staff,
                nav_show_page2,
                nav_show_page4,
            )

            return {
                "company_registry_enabled": company_registry_enabled(),
                "current_admin_role": current_admin_role(),
                "is_company_admin": is_company_admin(),
                "is_project_admin": is_project_admin(),
                "is_page13_super_admin": is_page13_super_admin(),
                "can_access_company_registry": is_company_registry_user(),
                "nav_show_page0": nav_show_page0(),
                "nav_show_page123_staff": nav_show_page123_staff(),
                "nav_show_page2": nav_show_page2(),
                "nav_show_page4": nav_show_page4(),
            }
        except Exception:
            return {
                "company_registry_enabled": False,
                "current_admin_role": "none",
                "is_company_admin": False,
                "is_project_admin": False,
                "is_page13_super_admin": False,
                "can_access_company_registry": False,
                "nav_show_page0": False,
                "nav_show_page123_staff": False,
                "nav_show_page2": False,
                "nav_show_page4": False,
            }

    @app.context_processor
    def _inject_feedback_fab():
        try:
            from .feedback_routes import feedback_fab_enabled

            return {"feedback_fab_enabled": feedback_fab_enabled()}
        except Exception:
            return {"feedback_fab_enabled": False}

    @app.after_request
    def _no_store_for_app_js_css(response):
        from flask import request

        p = (request.path or "").replace("\\", "/")
        # 业务 static/js 强制 no-store（升级后避免浏览器长期缓存旧脚本）；vendor 走 url_for v=static_version
        _biz_js = (
            p.startswith("/static/js/")
            and p.endswith(".js")
            and "/vendor/" not in p
        )
        if _biz_js or p.endswith("/static/css/app.css"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)

    db.init_app(app)
    startup_note("create_app: 连接数据库并检查表结构（可能较慢）…")

    # 数据库连接断开后（如网络恢复前拿到的连接已失效）：清空连接池，下次请求自动重连，无需重启服务
    from sqlalchemy.exc import OperationalError, InterfaceError
    from sqlalchemy.engine import Engine

    @app.errorhandler(OperationalError)
    @app.errorhandler(InterfaceError)
    def _handle_db_connection_error(exc):
        try:
            engine = db.engine
            if isinstance(engine, Engine):
                engine.dispose()
        except Exception:
            pass
        from flask import request
        if request.path.startswith("/api/"):
            return {"message": "数据库连接中断，请刷新页面重试"}, 503
        try:
            from flask import render_template
            return render_template(
                "error.html",
                title="服务暂时不可用",
                message="数据库连接中断，请刷新页面重试",
                hide_main_nav=True,
                gate_page=True,
            ), 503
        except Exception:
            return "<h1>数据库连接中断</h1><p>请刷新页面重试。</p>", 503

    with app.app_context():
        ensure_schema(app)
        startup_note("create_app: 注册路由与加载系统配置…")
        from .routes import register_blueprint

        register_blueprint(app)

        from .integration_routes import bp as integration_bp
        app.register_blueprint(integration_bp)

        from .draft_generation_routes import draft_gen_bp

        app.register_blueprint(draft_gen_bp)

        from .audit_routes import audit_bp

        app.register_blueprint(audit_bp)

        from .audit_modify_routes import audit_modify_bp

        app.register_blueprint(audit_modify_bp)

        from .translation_routes import translation_bp

        app.register_blueprint(translation_bp)

        from .company_routes import company_bp
        from .admin_routes import register_admin_blueprint

        app.register_blueprint(company_bp)
        register_admin_blueprint(app)

        from .feedback_routes import register_feedback_blueprint

        register_feedback_blueprint(app)
        from .document_control.routes import document_control_bp

        app.register_blueprint(document_control_bp)
        from .literature_routes import literature_bp

        app.register_blueprint(literature_bp)

        from .app_settings import register_exam_center_feature_gate

        register_exam_center_feature_gate(app)

        db.create_all()
        ensure_schema(app)
        init_default_configs()
        from .app_settings import (
            apply_system_settings_to_flask,
            ensure_environment_variables_migrated_to_db,
            sync_database_url_bootstrap_from_app_configs,
        )
        ensure_environment_variables_migrated_to_db(
            project_root, startup_database_uri=db_uri, flask_app=app
        )
        sync_database_url_bootstrap_from_app_configs(app, project_root)
        from .app_settings import sync_authoritative_sources_into_db

        sync_authoritative_sources_into_db(project_root, app)
        apply_system_settings_to_flask(app, project_root)
        from .migrate_binary_assets import migrate_binary_assets_to_db

        migrate_binary_assets_to_db(app)
        from .startup_local_env import run_startup_local_maintenance

        run_startup_local_maintenance(app, project_root)
        try:
            from .historical_migration import (
                run_doc_control_norm_backfill_if_pending,
                run_exam_historical_repair_if_pending,
                run_exam_organization_backfill_if_pending,
                run_team_data_migration_if_pending,
                run_team_junction_backfill_if_pending,
            )

            run_team_data_migration_if_pending()
            run_exam_organization_backfill_if_pending()
            run_exam_historical_repair_if_pending()
            run_team_junction_backfill_if_pending()
            n = run_doc_control_norm_backfill_if_pending()
            if n:
                app.logger.info("document_control: backfilled normalized_document_number on %s rows", n)
        except Exception:
            db.session.rollback()
            app.logger.exception("historical_migration failed")

    try:
        from .scheduler import init_scheduler
        init_scheduler(app)
    except Exception:
        pass

    _configure_console_logging(app)
    return app


app = create_app()

