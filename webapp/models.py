import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo

    CN_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover
    CN_TZ = timezone(timedelta(hours=8))

from sqlalchemy import LargeBinary, UniqueConstraint
from sqlalchemy.dialects.mysql import MEDIUMBLOB
from sqlalchemy.orm import Mapped, mapped_column, relationship

# MySQL 默认 BLOB 仅 64KB，模板/生成文件用 MEDIUMBLOB；SQLite 仍用 BLOB
_BinaryMedium = LargeBinary().with_variant(MEDIUMBLOB(), "mysql")

from . import db


def generate_uuid() -> str:
    return str(uuid.uuid4())


def now_local() -> datetime:
    return datetime.now(CN_TZ).replace(tzinfo=None)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


class User(db.Model):
    """用户账号，用于页面2登录。在页面1管理。"""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    username: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(db.String(128), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(db.String(128))
    mobile: Mapped[Optional[str]] = mapped_column(db.String(32))
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime, default=now_local, onupdate=now_local
    )

    def set_password(self, password: str):
        self.password_hash = hash_password(password)

    def check_password(self, password: str) -> bool:
        return verify_password(password, self.password_hash)


class TaskTypeConfig(db.Model):
    """任务类型配置表（页面1使用）"""
    __tablename__ = "task_type_configs"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)


class CompletionStatusConfig(db.Model):
    """完成状态配置表（页面2使用）"""
    __tablename__ = "completion_status_configs"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)


class AuditStatusConfig(db.Model):
    """审核状态配置表（页面1使用）"""
    __tablename__ = "audit_status_configs"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)


class NotifyTemplateConfig(db.Model):
    """钉钉通知文案配置表"""
    __tablename__ = "notify_template_configs"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    template_key: Mapped[str] = mapped_column(db.String(64), unique=True, nullable=False)
    template_name: Mapped[str] = mapped_column(db.String(128), nullable=False)
    template_content: Mapped[str] = mapped_column(db.Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime, default=now_local, onupdate=now_local
    )


class AppConfig(db.Model):
    """应用配置表（key-value），如自动通知时间。"""
    __tablename__ = "app_configs"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    config_key: Mapped[str] = mapped_column(db.String(128), unique=True, nullable=False)
    config_value: Mapped[str] = mapped_column(db.Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime, default=now_local, onupdate=now_local
    )


class Project(db.Model):
    """项目元数据：优先级与状态（进行中/已结束）。"""
    __tablename__ = "projects"

    PRIORITY_LOW = 1
    PRIORITY_MEDIUM = 2
    PRIORITY_HIGH = 3

    STATUS_ACTIVE = "active"  # 进行中
    STATUS_ENDED = "ended"    # 已结束

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(db.String(128), nullable=False)
    # 注册国家/注册类别用于区分“同名不同项目”的唯一性
    registered_country: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    registered_category: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    priority: Mapped[int] = mapped_column(db.Integer, default=PRIORITY_MEDIUM)
    status: Mapped[str] = mapped_column(db.String(16), default=STATUS_ACTIVE)
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local, onupdate=now_local)


class ModuleCascadeReminder(db.Model):
    """模块级联催办待执行/已执行记录：按项目，产品最后一份完成→N分钟后催办开发；开发最后一份完成→N分钟后催办测试。"""
    __tablename__ = "module_cascade_reminders"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[Optional[str]] = mapped_column(db.String(36), nullable=True)
    project_name: Mapped[str] = mapped_column(db.String(128), nullable=False)
    trigger_module: Mapped[str] = mapped_column(db.String(32), nullable=False)  # 产品 | 开发
    target_module: Mapped[str] = mapped_column(db.String(32), nullable=False)   # 开发 | 测试
    run_at: Mapped[datetime] = mapped_column(db.DateTime, nullable=False)
    status: Mapped[str] = mapped_column(db.String(16), default="pending")  # pending | sent
    sent_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)


class UploadRecord(db.Model):
    """
    上传记录：支持文件上传或多行文档链接。
    合并了任务分配功能，可设置负责人、截止日期，并发送钉钉通知。
    """
    __tablename__ = "upload_records"
    __table_args__ = (
        UniqueConstraint("project_name", "file_name", "task_type", "author", name="uq_project_file_type_author"),
    )

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[Optional[str]] = mapped_column(db.String(36), nullable=True)
    project_name: Mapped[str] = mapped_column(db.String(128), nullable=False)
    file_name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    task_type: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    author: Mapped[str] = mapped_column(db.String(128), nullable=False)
    stored_file_name: Mapped[Optional[str]] = mapped_column(db.String(255), nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(db.String(512), nullable=True)
    template_file_blob: Mapped[Optional[bytes]] = mapped_column(_BinaryMedium, nullable=True)
    original_file_name: Mapped[Optional[str]] = mapped_column(db.String(255), nullable=True)
    template_links: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)
    project_notes: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)  # 第一层 项目备注
    execution_notes: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)
    placeholders: Mapped[list] = mapped_column(db.JSON, default=list)
    assignee_name: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(db.Date, nullable=True)
    business_side: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    product: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)  # 影响产品
    country: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    registered_product_name: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)  # 注册产品名称
    model: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)  # 型号
    registration_version: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)  # 注册版本号
    project_code: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    file_version: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    document_display_date: Mapped[Optional[datetime]] = mapped_column(db.Date, nullable=True)
    reviewer: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    approver: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    belonging_module: Mapped[Optional[str]] = mapped_column(db.String(32), nullable=True)  # 所属模块：产品、开发、测试、全员
    displayed_author: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)  # 体现编写人员
    task_status: Mapped[str] = mapped_column(db.String(32), default="pending")
    completion_status: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    audit_status: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    audit_reject_count: Mapped[int] = mapped_column(default=0)
    quick_completed: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0)
    dingtalk_notified_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime, default=now_local, onupdate=now_local
    )

    generate_records: Mapped[list["GenerateRecord"]] = relationship(
        back_populates="upload", cascade="all, delete-orphan"
    )
    summary: Mapped["GenerationSummary"] = relationship(
        back_populates="upload", uselist=False, cascade="all, delete-orphan"
    )

    def get_template_links_list(self) -> list:
        """获取模板链接列表（每行一个链接）"""
        if not self.template_links:
            return []
        return [line.strip() for line in self.template_links.strip().split("\n") if line.strip()]

    def has_template(self) -> bool:
        """是否有可用的模板（库内文件、本机路径或链接）"""
        if self.template_file_blob:
            return True
        from pathlib import Path
        if self.storage_path and Path(self.storage_path).exists():
            return True
        return bool(self.template_links)

    def has_stored_template_file(self) -> bool:
        """是否有已保存的模板文件（数据库或本机）"""
        if self.template_file_blob:
            return True
        if self.storage_path:
            from pathlib import Path
            return Path(self.storage_path).exists()
        return False


class GenerateRecord(db.Model):
    __tablename__ = "generate_records"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    upload_id: Mapped[str] = mapped_column(
        db.String(36), db.ForeignKey("upload_records.id"), nullable=False
    )
    triggered_by: Mapped[Optional[str]] = mapped_column(db.String(128))
    status: Mapped[str] = mapped_column(db.String(32), default="pending")
    success: Mapped[bool] = mapped_column(default=False)
    placeholder_payload: Mapped[Optional[dict]] = mapped_column(db.JSON)
    output_file_name: Mapped[Optional[str]] = mapped_column(db.String(255))
    output_path: Mapped[Optional[str]] = mapped_column(db.String(512))
    output_file_blob: Mapped[Optional[bytes]] = mapped_column(_BinaryMedium, nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)
    completed_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime, nullable=True)

    upload: Mapped[UploadRecord] = relationship(back_populates="generate_records")


class GenerationSummary(db.Model):
    __tablename__ = "generation_summary"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    project_id: Mapped[Optional[str]] = mapped_column(db.String(36), nullable=True)
    upload_id: Mapped[str] = mapped_column(
        db.String(36), db.ForeignKey("upload_records.id"), unique=True, nullable=False
    )
    project_name: Mapped[str] = mapped_column(db.String(128), nullable=False)
    file_name: Mapped[str] = mapped_column(db.String(255), nullable=False)
    author: Mapped[str] = mapped_column(db.String(128), nullable=False)
    total_generate_clicks: Mapped[int] = mapped_column(default=0)
    has_generated: Mapped[bool] = mapped_column(default=False)
    last_generated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(
        db.DateTime, default=now_local, onupdate=now_local
    )

    upload: Mapped[UploadRecord] = relationship(back_populates="summary")


class NoteAttachmentFile(db.Model):
    """备注附件：存数据库，迁机只需带库。"""
    __tablename__ = "note_attachment_files"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    stored_name: Mapped[str] = mapped_column(db.String(255), unique=True, nullable=False)
    file_blob: Mapped[bytes] = mapped_column(_BinaryMedium, nullable=False)
    original_name: Mapped[Optional[str]] = mapped_column(db.String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)


class ExamBankIngestJob(db.Model):
    """考试训练中心：老师批量录入题库任务记录（aiword 本地记录 + 轮询结果快照）。"""
    __tablename__ = "exam_bank_ingest_jobs"
    __table_args__ = (
        UniqueConstraint("upstream_job_id", name="uq_exam_bank_ingest_upstream_job_id"),
    )

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    upstream_job_id: Mapped[str] = mapped_column(db.String(128), nullable=False)
    # 上游套题 ID：ingest-by-ai 可能在任务进行中就返回（不必等 done）
    upstream_set_id: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    exam_track: Mapped[Optional[str]] = mapped_column(db.String(32), nullable=True)
    target_count: Mapped[Optional[int]] = mapped_column(db.Integer, nullable=True)
    review_mode: Mapped[Optional[str]] = mapped_column(db.String(32), nullable=True)

    status: Mapped[str] = mapped_column(db.String(32), default="pending")  # pending/running/done/failed/unknown
    last_message: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)

    # 最近一次上游轮询返回的 data（用于排查与展示）
    last_upstream_data: Mapped[Optional[dict]] = mapped_column(db.JSON, nullable=True)
    last_upstream_http_status: Mapped[Optional[int]] = mapped_column(db.Integer, nullable=True)
    last_upstream_request_url: Mapped[Optional[str]] = mapped_column(db.String(1024), nullable=True)
    last_upstream_trace_id: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)

    created_by: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)  # session username/display_name
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local, onupdate=now_local)


class ExamSetReviewJob(db.Model):
    """考试训练中心：老师 AI 复审套题任务（异步 job + 本地快照，轮询方式与录题一致）。"""
    __tablename__ = "exam_set_review_jobs"
    __table_args__ = (UniqueConstraint("upstream_job_id", name="uq_exam_set_review_upstream_job_id"),)

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    upstream_job_id: Mapped[str] = mapped_column(db.String(128), nullable=False)
    set_id: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)

    status: Mapped[str] = mapped_column(db.String(32), default="pending")
    last_message: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)

    last_upstream_data: Mapped[Optional[dict]] = mapped_column(db.JSON, nullable=True)
    last_upstream_http_status: Mapped[Optional[int]] = mapped_column(db.Integer, nullable=True)
    last_upstream_request_url: Mapped[Optional[str]] = mapped_column(db.String(1024), nullable=True)
    last_upstream_trace_id: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)

    created_by: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local, onupdate=now_local)


class ExamCenterActivity(db.Model):
    """考试训练中心：练习/考试提交在 aiword 侧的本地记录（配合 aicheckword 上游业务数据）。"""
    __tablename__ = "exam_center_activities"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(db.String(36), nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)

    mode: Mapped[str] = mapped_column(db.String(16), nullable=False)  # practice | exam
    exam_track: Mapped[Optional[str]] = mapped_column(db.String(32), nullable=True)
    set_id: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    assignment_id: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    assignment_label: Mapped[Optional[str]] = mapped_column(db.String(256), nullable=True)
    attempt_id: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)

    upstream_http_status: Mapped[Optional[int]] = mapped_column(db.Integer, nullable=True)
    upstream_trace_id: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)


class ExamCenterAssignment(db.Model):
    """考试训练中心：老师下发的考试任务本地镜像（上游不可用时兜底展示）。"""
    __tablename__ = "exam_center_assignments"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    assignment_id: Mapped[str] = mapped_column(db.String(128), nullable=False, unique=True, index=True)
    set_id: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True, index=True)
    title: Mapped[Optional[str]] = mapped_column(db.String(256), nullable=True)
    exam_track: Mapped[Optional[str]] = mapped_column(db.String(32), nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(db.String(16), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(db.String(32), nullable=True)
    # 截止完成时间（本地镜像）：老师下发时填写，用于学生端展示与按时完成统计；可为空。
    due_at: Mapped[Optional[datetime]] = mapped_column(db.DateTime, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(db.String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local, onupdate=now_local)


class ExamCenterActivityDetail(db.Model):
    """练习/考试提交后明细快照，供老师端/统计端查看成绩与薄弱项。"""
    __tablename__ = "exam_center_activity_details"

    id: Mapped[str] = mapped_column(db.String(36), primary_key=True, default=generate_uuid)
    activity_id: Mapped[str] = mapped_column(db.String(36), nullable=False, index=True, unique=True)
    mode: Mapped[Optional[str]] = mapped_column(db.String(16), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(db.Float, nullable=True)
    total_score: Mapped[Optional[float]] = mapped_column(db.Float, nullable=True)
    correct_count: Mapped[Optional[int]] = mapped_column(db.Integer, nullable=True)
    wrong_count: Mapped[Optional[int]] = mapped_column(db.Integer, nullable=True)
    weakness: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)
    recommendation: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)
    upstream_payload: Mapped[Optional[dict]] = mapped_column(db.JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=now_local)

