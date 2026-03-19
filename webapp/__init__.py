import os
from pathlib import Path

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from jinja2 import ChoiceLoader, FileSystemLoader
from sqlalchemy import inspect, text

db = SQLAlchemy()


def ensure_schema(app: Flask):
    """确保数据库schema与模型定义一致，包括添加缺失的列和修复nullable约束。"""
    engine = db.engine
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    is_sqlite = engine.dialect.name == "sqlite"

    def ensure_column(table: str, column: str, ddl_sqlite: str, ddl_other: str):
        if table not in existing_tables:
            return
        columns = {col["name"] for col in inspector.get_columns(table)}
        if column in columns:
            return
        ddl = ddl_sqlite if is_sqlite else ddl_other
        with engine.connect() as conn:
            conn.execute(text(ddl))
            conn.commit()

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
        "generate_records",
        "output_file_blob",
        "ALTER TABLE generate_records ADD COLUMN output_file_blob BLOB",
        "ALTER TABLE generate_records ADD COLUMN output_file_blob MEDIUMBLOB",
    )


def init_default_configs():
    """初始化默认的配置项数据"""
    from .models import TaskTypeConfig, CompletionStatusConfig, AuditStatusConfig, NotifyTemplateConfig, AppConfig
    
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
        ("single_task_reminder", "单条任务催办通知",
         "【任务催办】\n致：{author}\n\n- **{title}**\n - 截止日期：{due_date}\n - 影响业务方：{business_side}\n - 产品：{product}\n - 国家：{country}\n - 项目编号：{project_code}\n - 项目备注：{project_notes}\n - 文件版本号：{file_version}\n - 文档体现日期：{document_display_date}\n - 审核人员：{reviewer}\n - 批准人员：{approver}\n - 文档地址：{doc_link_md}\n\n请抓紧处理！"),
    ]
    
    for name, order in default_task_types:
        existing = TaskTypeConfig.query.filter_by(name=name).first()
        if not existing:
            db.session.add(TaskTypeConfig(name=name, sort_order=order))
    
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
    for sk, _, _ in SYSTEM_CONFIG_KEYS:
        if not AppConfig.query.filter_by(config_key=sk).first():
            db.session.add(AppConfig(config_key=sk, config_value=""))

    db.session.commit()


def create_app() -> Flask:
    """Application factory for the AI Word web suite."""
    project_root = Path(__file__).resolve().parent.parent
    
    # 尝试从 .env 加载环境变量（若已安装 python-dotenv）
    try:
        from dotenv import load_dotenv
        load_dotenv(project_root / ".env")
    except ImportError:
        pass
    
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

    uploads_dir = project_root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir = project_root / "outputs"
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
    app = Flask(
        __name__,
        template_folder=_template_paths[0],
        static_folder=str(project_root / "web" / "static"),
    )
    if len(_template_paths) > 1:
        app.jinja_loader = ChoiceLoader(
            [FileSystemLoader(p) for p in _template_paths]
        )

    # 已注释 SQLite 入口，避免搞混当前连接的数据库。当前仅使用 MySQL。
    # default_db_uri = "sqlite:///" + str(project_root / "data" / "aiword.db")
    default_db_uri = "mysql+pymysql://root:mysql170921@10.26.1.221:13306/aiword?charset=utf8mb4"
    from .app_settings import resolve_database_uri
    db_uri = resolve_database_uri(project_root, os.getenv("DATABASE_URL", default_db_uri))

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
    if db_uri.startswith("mysql"):
        _sep = "&" if "?" in db_uri else "?"
        db_uri = db_uri + _sep + "connect_timeout=10"

    app.config.update(
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS=_engine_opts,
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
        for rel in ("js/app.js", "css/app.css"):
            p = project_root / "web" / "static" / rel
            try:
                v = max(v, int(p.stat().st_mtime))
            except OSError:
                pass
        return v

    @app.context_processor
    def _inject_static_version():
        return {"static_version": _static_assets_version()}

    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)

    db.init_app(app)

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
            return render_template("error.html", message="数据库连接中断，请刷新页面重试"), 503
        except Exception:
            return "<h1>数据库连接中断</h1><p>请刷新页面重试。</p>", 503

    with app.app_context():
        ensure_schema(app)
        from .routes import register_blueprint

        register_blueprint(app)

        from .integration_routes import bp as integration_bp
        app.register_blueprint(integration_bp)

        db.create_all()
        init_default_configs()
        from .app_settings import ensure_environment_variables_migrated_to_db, apply_system_settings_to_flask
        ensure_environment_variables_migrated_to_db(
            project_root, startup_database_uri=db_uri, flask_app=app
        )
        from .app_settings import sync_authoritative_sources_into_db

        sync_authoritative_sources_into_db(project_root, app)
        apply_system_settings_to_flask(app, project_root)
        from .migrate_binary_assets import migrate_binary_assets_to_db

        migrate_binary_assets_to_db(app)
        from .startup_local_env import run_startup_local_maintenance

        run_startup_local_maintenance(app, project_root)

    try:
        from .scheduler import init_scheduler
        init_scheduler(app)
    except Exception:
        pass

    return app


app = create_app()

