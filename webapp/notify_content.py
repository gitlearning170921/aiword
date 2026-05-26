"""钉钉等推送通知中的任务行文案（含事项型任务的文档地址提示）。"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import User

logger = logging.getLogger(__name__)

MATTER_COMPLETE_NOTES_MSG = "请在备注中填写事项完成情况"
MATTER_COMPLETE_NOTES_INVALID_MSG = "请在备注中填写有效的事项完成情况，不可仅填空格或符号"

# 事项型任务在通知中替代「点击打开」链接的固定说明
MATTER_TASK_DOC_LINK_HINT = "本条为实操项，请确保与相应文件内容一致"

# 催办/自动通知中页面2登录说明（钉钉 Markdown 括号内文案）
PAGE2_LOGIN_HINT_MD = "账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456"


def normalize_person_name(s: str) -> str:
    """姓名/用户名比对前规范化（去首尾空白、全角等）。"""
    return unicodedata.normalize("NFKC", str(s or "").strip())


def user_author_pick_label(user: "User") -> str:
    """与页面1 编写人下拉一致：显示名优先，否则用户名。"""
    dn = normalize_person_name(getattr(user, "display_name", None) or "")
    un = normalize_person_name(getattr(user, "username", None) or "")
    return dn or un


def normalize_dingtalk_at_mobile(raw: str) -> str:
    """
    钉钉 atMobiles 用 11 位大陆手机号。
    支持库中常见写法：18712345678、+86-18712345678、+86 187 1234 5678 等。
    """
    s = unicodedata.normalize("NFKC", str(raw or "").strip())
    if not s:
        return ""
    digits = re.sub(r"\D", "", s)
    if not digits:
        return ""
    if len(digits) == 11 and digits.startswith("1"):
        return digits
    if len(digits) >= 13 and digits.startswith("86"):
        tail = digits[-11:]
        if len(tail) == 11 and tail.startswith("1"):
            return tail
    if len(digits) > 11 and digits.startswith("1"):
        return digits[:11]
    return ""


def format_mobile_for_storage(raw: str) -> Optional[str]:
    """保存用户手机号时统一为 11 位，便于催办 @ 与展示一致。"""
    s = (raw or "").strip()
    if not s:
        return None
    normalized = normalize_dingtalk_at_mobile(s)
    return normalized or s


def resolve_user_for_author_label(label: str) -> Optional["User"]:
    """
    任务「编写人/负责人」姓名 → 用户账号。
    除 username/display_name 精确匹配外，还与编写人下拉的展示名（display 优先）对齐。
    """
    from sqlalchemy import func

    from . import db
    from .models import User

    name = normalize_person_name(label)
    if not name:
        return None

    user = User.query.filter(
        db.or_(User.username == name, User.display_name == name)
    ).first()
    if user:
        return user

    user = User.query.filter(
        db.or_(
            func.trim(User.username) == name,
            func.trim(User.display_name) == name,
        )
    ).first()
    if user:
        return user

    for cand in User.query.all():
        if user_author_pick_label(cand) == name:
            return cand

    return None


def collect_notify_person_names_from_uploads(uploads) -> List[str]:
    """催办 @ 对象：编写人 + 负责人（去重），避免仅负责人字段填写时漏 @。"""
    names: set[str] = set()
    for u in uploads or []:
        for field in (getattr(u, "author", None), getattr(u, "assignee_name", None)):
            n = normalize_person_name(field)
            if n:
                names.add(n)
    return sorted(names)


def at_resolve_report(label: str) -> dict:
    """管理端诊断：任务姓名能否解析到钉钉 @ 用手机号。"""
    name = normalize_person_name(label)
    if not name:
        return {
            "matched": False,
            "label": label or "",
            "normalizedLabel": "",
            "message": "姓名为空",
        }
    user = resolve_user_for_author_label(name)
    if not user:
        return {
            "matched": False,
            "label": label,
            "normalizedLabel": name,
            "message": "未在用户表中找到匹配账号（请核对任务「编写人」与用户名/显示名是否一致）",
        }
    raw = str(getattr(user, "mobile", None) or "").strip()
    at_mobile = normalize_dingtalk_at_mobile(raw)
    return {
        "matched": True,
        "label": label,
        "normalizedLabel": name,
        "username": user.username,
        "displayName": user.display_name,
        "pickLabel": user_author_pick_label(user),
        "mobileRaw": raw,
        "mobileAt": at_mobile,
        "canAt": bool(at_mobile),
        "message": (
            f"可传给钉钉 @：{at_mobile}"
            if at_mobile
            else "已匹配账号但未解析出有效手机号，请检查手机号格式"
        ),
    }


def resolve_mobiles_for_author_labels(
    author_names: list,
) -> Tuple[List[str], List[str], List[str]]:
    """
    解析催办 @ 用手机号。

    :return: (at_mobiles, 未匹配到账号的姓名, 已匹配但无手机号的姓名)
    """
    mobiles: List[str] = []
    unmatched: List[str] = []
    no_mobile: List[str] = []
    seen: set[str] = set()

    for raw in author_names or []:
        name = normalize_person_name(raw)
        if not name:
            continue
        user = resolve_user_for_author_label(name)
        if not user:
            unmatched.append(name)
            logger.info("催办@：未匹配账号，编写人=%r", name)
            continue
        mobile = normalize_dingtalk_at_mobile(getattr(user, "mobile", None) or "")
        if not mobile:
            no_mobile.append(name)
            logger.info(
                "催办@：账号无手机号，编写人=%r username=%r",
                name,
                getattr(user, "username", None),
            )
            continue
        if mobile not in seen:
            seen.add(mobile)
            mobiles.append(mobile)

    return mobiles, unmatched, no_mobile


def page2_my_tasks_link_md(page2_url: str) -> str:
    """催办通知末尾「页面2（我的任务）」链接行。"""
    u = (page2_url or "").strip()
    if not u:
        return ""
    return f"页面2（我的任务）：[点击打开]({u})（{PAGE2_LOGIN_HINT_MD}）"


def normalize_task_type_category(raw) -> str:
    from .models import TASK_TYPE_CATEGORIES, TASK_TYPE_CATEGORY_FILE

    v = (str(raw or "").strip().lower())
    if v in TASK_TYPE_CATEGORIES:
        return v
    return TASK_TYPE_CATEGORY_FILE


def _task_type_category_by_name() -> Dict[str, str]:
    from .models import TaskTypeConfig

    out: Dict[str, str] = {}
    for t in TaskTypeConfig.query.filter_by(is_active=True).all():
        name = (t.name or "").strip()
        if name:
            out[name] = normalize_task_type_category(getattr(t, "category", None))
    return out


def task_type_category_of_upload(upload) -> str:
    from .models import TASK_TYPE_CATEGORY_FILE

    tt = (getattr(upload, "task_type", None) or "").strip()
    if not tt:
        return TASK_TYPE_CATEGORY_FILE
    return _task_type_category_by_name().get(tt, TASK_TYPE_CATEGORY_FILE)


def is_matter_task_upload(upload) -> bool:
    from .models import TASK_TYPE_CATEGORY_MATTER

    return task_type_category_of_upload(upload) == TASK_TYPE_CATEGORY_MATTER


def is_meaningful_matter_execution_notes(raw) -> bool:
    """事项型完成备注：去空白后须含至少一个中文/字母/数字，拒绝纯空格或纯符号。"""
    s = str(raw or "").strip()
    if not s:
        return False
    core = re.sub(r"\s+", "", s)
    if not core:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", core))


def notify_doc_link_suffix_md(upload) -> str:
    """任务行末尾的「文档地址：…」片段（含前导空格）。"""
    if is_matter_task_upload(upload):
        return f"  文档地址：{MATTER_TASK_DOC_LINK_HINT}"
    links = upload.get_template_links_list() or []
    link = links[0] if links else None
    if link:
        return f"  文档地址：[点击打开]({link})"
    return ""


def notify_doc_link_md_for_template(upload) -> str:
    """单条催办模板占位符 {doc_link_md}。"""
    if is_matter_task_upload(upload):
        return MATTER_TASK_DOC_LINK_HINT
    links = upload.get_template_links_list() or []
    if links:
        return f"[点击打开]({links[0]})"
    return "（无链接）"
