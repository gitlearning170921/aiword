# -*- coding: utf-8 -*-
"""账号级功能权限（页面0 / 页面1 / 页面2 分项，与系统配置全局开关叠加）。"""
from __future__ import annotations

import json
from typing import Any, Optional

from .models import (
    ADMIN_ROLE_COMPANY,
    ADMIN_ROLE_NONE,
    ADMIN_ROLE_PROJECT,
    ADMIN_ROLES,
    User,
)

# 页面0：公司总览 · 文档工具（手动上传）
USER_PAGE0_FEATURE_KEYS: tuple[str, ...] = (
    "FEATURE_PAGE0_DRAFT_GEN",
    "FEATURE_PAGE0_AUDIT",
    "FEATURE_PAGE0_AUDIT_MODIFY",
    "FEATURE_PAGE0_AUDIT_TODO",
    "FEATURE_PAGE0_TRANSLATE",
    "FEATURE_LITERATURE_SEARCH",
    "FEATURE_PAGE0_KNOWLEDGE_TRAIN",
    "FEATURE_PAGE0_DEFICIENCY",
)

# 页面1：文档工具、任务列表签字/打印/单审、考试中心（含页面3 顶栏入口）
USER_PAGE1_FEATURE_KEYS: tuple[str, ...] = (
    "FEATURE_PAGE1_DRAFT_GEN",
    "FEATURE_PAGE1_AUDIT",
    "FEATURE_PAGE1_AUDIT_MODIFY",
    "FEATURE_PAGE1_AUDIT_TODO",
    "FEATURE_PAGE1_TRANSLATE",
    "FEATURE_PAGE1_EXAM_CENTER",
    "FEATURE_PAGE1_SIGN",
    "FEATURE_PAGE1_PRINT",
    "FEATURE_LITERATURE_SEARCH",
    "FEATURE_DOCUMENT_CONTROL",
    "FEATURE_PROJECT_KB",
    "FEATURE_VERSION_TASK_GENERATOR",
)

# 页面2：任务行按钮与考试中心
USER_PAGE2_FEATURE_KEYS: tuple[str, ...] = (
    "FEATURE_PAGE2_UPLOAD_REPLACE",
    "FEATURE_PAGE2_DRAFT_GEN",
    "FEATURE_PAGE2_AUDIT_MODIFY",
    "FEATURE_PAGE2_TRANSLATE",
    "FEATURE_PAGE2_EXAM_CENTER",
)

USER_MANAGED_FEATURE_KEYS: tuple[str, ...] = tuple(
    dict.fromkeys(
        USER_PAGE0_FEATURE_KEYS + USER_PAGE1_FEATURE_KEYS + USER_PAGE2_FEATURE_KEYS
    )
)

# 账号管理 · 功能权限 UI 分组（新建/编辑/批量共用；前端通过 API 拉取，勿在 app.js 重复维护）
USER_FEATURE_PERM_GROUP_DEFS: tuple[dict[str, Any], ...] = (
    {
        "id": "page0",
        "title": "页面0 · 文档工具",
        "keys": USER_PAGE0_FEATURE_KEYS,
    },
    {
        "id": "page1",
        "title": "页面1（含页面3）",
        "keys": USER_PAGE1_FEATURE_KEYS,
    },
    {
        "id": "page2",
        "title": "页面2",
        "keys": USER_PAGE2_FEATURE_KEYS,
    },
)

# 分级角色在账号管理中可见的分组（新建/编辑/批量均按所选角色过滤）
USER_FEATURE_PERM_ROLE_VISIBLE_GROUP_IDS: dict[str, tuple[str, ...]] = {
    "company": ("page0",),
    "project": ("page1", "page2"),
    "none": ("page2",),
}

ADMIN_ROLE_LABELS_FOR_BATCH: dict[str, str] = {
    "none": "普通用户",
    "project": "项目管理员",
    "company": "公司管理员",
}

USER_FEATURE_LABELS: dict[str, str] = {
    "FEATURE_PAGE0_DRAFT_GEN": "页面0 · 初稿生成",
    "FEATURE_PAGE0_AUDIT": "页面0 · 文档审核",
    "FEATURE_PAGE0_AUDIT_MODIFY": "页面0 · 审核后修改",
    "FEATURE_PAGE0_AUDIT_TODO": "页面0 · 生成审核待办",
    "FEATURE_PAGE0_TRANSLATE": "页面0 · 文档翻译",
    "FEATURE_PAGE0_KNOWLEDGE_TRAIN": "页面0 · 知识库训练",
    "FEATURE_PAGE0_DEFICIENCY": "页面0 · 发补记录",
    "FEATURE_PAGE1_DRAFT_GEN": "页面1 · 初稿生成",
    "FEATURE_PAGE1_AUDIT": "页面1 · 文档审核",
    "FEATURE_PAGE1_AUDIT_MODIFY": "页面1 · 审核后修改",
    "FEATURE_PAGE1_AUDIT_TODO": "页面1 · 生成审核待办",
    "FEATURE_PAGE1_TRANSLATE": "页面1 · 文档翻译",
    "FEATURE_PAGE1_EXAM_CENTER": "页面1/3 · 考试训练中心",
    "FEATURE_PAGE1_SIGN": "页面1 · 去签字",
    "FEATURE_PAGE1_PRINT": "页面1 · 去打印",
    "FEATURE_PAGE2_UPLOAD_REPLACE": "页面2 · 上传/替换",
    "FEATURE_PAGE2_DRAFT_GEN": "页面2 · 初稿生成",
    "FEATURE_PAGE2_AUDIT_MODIFY": "页面2 · 审核后修改",
    "FEATURE_PAGE2_TRANSLATE": "页面2 · 文档翻译",
    "FEATURE_PAGE2_EXAM_CENTER": "页面2 · 考试训练中心",
    "FEATURE_LITERATURE_SEARCH": "文献检索",
    "FEATURE_DOCUMENT_CONTROL": "文控中心",
    "FEATURE_PROJECT_KB": "项目知识库协同",
    "FEATURE_VERSION_TASK_GENERATOR": "版本任务清单生成",
}

# 账号未配置时禁止、不跟随系统全局开关（含 1.0.5 后新入口，以及签字/打印）。
USER_FEATURE_KEYS_DEFAULT_DENY: frozenset[str] = frozenset(
    {
        "FEATURE_LITERATURE_SEARCH",
        "FEATURE_DOCUMENT_CONTROL",
        "FEATURE_PROJECT_KB",
        "FEATURE_VERSION_TASK_GENERATOR",
        "FEATURE_PAGE0_KNOWLEDGE_TRAIN",
        "FEATURE_PAGE0_DEFICIENCY",
        "FEATURE_PAGE1_SIGN",
        "FEATURE_PAGE1_PRINT",
    }
)

# 旧版账号 JSON 键 → 新键（读取时复制，写入时不再使用旧键）
_USER_LEGACY_PERM_MIRROR: dict[str, tuple[str, ...]] = {
    "FEATURE_PAGE2_DRAFT_GEN": ("FEATURE_PAGE1_DRAFT_GEN", "FEATURE_PAGE2_DRAFT_GEN"),
    "FEATURE_PAGE2_AUDIT": ("FEATURE_PAGE1_AUDIT",),
    "FEATURE_PAGE2_AUDIT_MODIFY": ("FEATURE_PAGE1_AUDIT_MODIFY", "FEATURE_PAGE2_AUDIT_MODIFY"),
    "FEATURE_PAGE2_TRANSLATE": ("FEATURE_PAGE1_TRANSLATE", "FEATURE_PAGE2_TRANSLATE"),
    "FEATURE_EXAM_CENTER": ("FEATURE_PAGE1_EXAM_CENTER", "FEATURE_PAGE2_EXAM_CENTER"),
}


def user_managed_feature_keys() -> tuple[str, ...]:
    return USER_MANAGED_FEATURE_KEYS


def feature_permission_schema_for_client() -> dict[str, Any]:
    """新建/编辑账号与「批量功能权限」共用字段定义。"""
    groups = [
        {
            "id": g["id"],
            "title": g["title"],
            "defs": [
                {"key": k, "label": _feature_perm_short_label(k)}
                for k in g["keys"]
            ],
        }
        for g in USER_FEATURE_PERM_GROUP_DEFS
    ]
    return {
        "groups": groups,
        "roleVisibleGroupIds": {
            role: list(ids) for role, ids in USER_FEATURE_PERM_ROLE_VISIBLE_GROUP_IDS.items()
        },
        "defaultDenyKeys": sorted(USER_FEATURE_KEYS_DEFAULT_DENY),
    }


def _feature_perm_short_label(key: str) -> str:
    """账号管理下拉用短标签（去掉「页面N ·」前缀）。"""
    full = USER_FEATURE_LABELS.get(key, key)
    if " · " in full:
        return full.split(" · ", 1)[1]
    return full


def _coerce_feature_permissions_raw(raw: Any) -> Any:
    """SQLite TEXT / 双重 JSON 编码时仍解析为 dict。"""
    if raw is None or isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            parsed = json.loads(s)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
    return raw


def _expand_legacy_user_permissions(raw: dict[str, Any]) -> dict[str, Any]:
    out = dict(raw)
    for old_key, new_keys in _USER_LEGACY_PERM_MIRROR.items():
        if old_key not in raw:
            continue
        val = raw.get(old_key)
        for nk in new_keys:
            if nk not in out:
                out[nk] = val
    return out


def apply_default_deny_permissions(perms: Optional[dict[str, bool]]) -> dict[str, bool]:
    """新功能入口未配置时写入禁止，避免跟随系统后自动开放。"""
    out = dict(perms or {})
    for key in USER_FEATURE_KEYS_DEFAULT_DENY:
        out.setdefault(key, False)
    return out


def normalize_user_feature_permissions(raw: Any) -> dict[str, bool]:
    """仅保留受管键且值为 bool 的显式覆盖。"""
    raw = _coerce_feature_permissions_raw(raw)
    if not isinstance(raw, dict):
        return apply_default_deny_permissions({})
    raw = _expand_legacy_user_permissions(raw)
    out: dict[str, bool] = {}
    for key in USER_MANAGED_FEATURE_KEYS:
        if key not in raw:
            continue
        val = raw.get(key)
        if isinstance(val, bool):
            out[key] = val
        elif val in (0, 1, "0", "1", "true", "false", "True", "False"):
            out[key] = str(val).lower() in {"1", "true"}
    return apply_default_deny_permissions(out)


def read_user_feature_permissions(user: Optional[User]) -> dict[str, bool]:
    if not user:
        return apply_default_deny_permissions({})
    return normalize_user_feature_permissions(getattr(user, "feature_permissions_json", None))


def parse_feature_permissions_field(data: dict[str, Any]) -> Optional[dict[str, bool]]:
    """API 入参：省略=不修改；null=不修改；{}=新入口禁止、其余无覆盖。"""
    if "featurePermissions" not in data:
        return None
    raw = data.get("featurePermissions")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("featurePermissions 须为对象或 null")
    return normalize_user_feature_permissions(raw)


def write_user_feature_permissions(user: User, perms: Optional[dict[str, bool]]) -> None:
    """写入账号功能权限并标记 JSON 列已变更（避免 ORM 漏刷）。"""
    from sqlalchemy.orm.attributes import flag_modified

    normalized = apply_default_deny_permissions(normalize_user_feature_permissions(perms))
    user.feature_permissions_json = normalized
    flag_modified(user, "feature_permissions_json")


def merge_user_feature_flags(
    global_flags: dict[str, bool],
    user_overrides: dict[str, bool],
) -> dict[str, bool]:
    """全局开关 ∧ 账号覆盖：禁止优先；允许须全局已开启；新入口缺省禁止；其余无覆盖则跟随全局。"""
    overrides = apply_default_deny_permissions(user_overrides)
    out = dict(global_flags)
    for key in USER_MANAGED_FEATURE_KEYS:
        if key not in overrides:
            continue
        if overrides[key] is False:
            out[key] = False
        else:
            out[key] = bool(global_flags.get(key)) and bool(overrides[key])
    return out


def _feature_permission_page_label(key: str) -> str:
    in_p0 = key in USER_PAGE0_FEATURE_KEYS
    in_p1 = key in USER_PAGE1_FEATURE_KEYS
    if in_p0 and in_p1:
        return "0/1"
    if in_p0:
        return "0"
    if in_p1:
        return "1"
    return "2"


def serialize_user_feature_permissions(user: User) -> dict[str, Any]:
    perms = read_user_feature_permissions(user)
    return {
        "featurePermissions": perms,
        "featurePermissionMeta": [
            {
                "key": k,
                "label": USER_FEATURE_LABELS.get(k, k),
                "page": _feature_permission_page_label(k),
            }
            for k in USER_MANAGED_FEATURE_KEYS
        ],
    }


def apply_feature_permission_patch(
    existing: dict[str, bool],
    patch: dict[str, str],
) -> dict[str, bool]:
    """批量合并功能权限：patch 值为 allow / deny / inherit。
    inherit：原有项移除覆盖（跟随系统）；新入口仍落成禁止。"""
    out = dict(existing)
    for key, action in patch.items():
        if key not in USER_MANAGED_FEATURE_KEYS:
            continue
        act = (action or "").strip().lower()
        if act in ("", "skip", "unchanged", "nochange"):
            continue
        if act == "inherit":
            if key in USER_FEATURE_KEYS_DEFAULT_DENY:
                out[key] = False
            else:
                out.pop(key, None)
        elif act in ("allow", "true", "1"):
            out[key] = True
        elif act in ("deny", "false", "0"):
            out[key] = False
    return apply_default_deny_permissions(out)


def parse_batch_feature_permission_patch(data: dict[str, Any]) -> dict[str, str]:
    raw = data.get("featurePermissionPatches")
    if raw is None:
        raw = data.get("patches")
    if not isinstance(raw, dict):
        raise ValueError("featurePermissionPatches 须为对象")
    out: dict[str, str] = {}
    for key in USER_MANAGED_FEATURE_KEYS:
        if key not in raw:
            continue
        val = raw.get(key)
        if val is None:
            continue
        act = str(val).strip().lower()
        if act in ("", "skip", "unchanged", "nochange"):
            continue
        if act not in ("inherit", "allow", "deny", "true", "false", "0", "1"):
            raise ValueError(f"功能权限 {key} 的值无效")
        out[key] = act
    return out


def normalize_admin_role_for_feature_perms(role: str | None) -> str:
    r = (role or ADMIN_ROLE_NONE).strip()
    return r if r in ADMIN_ROLES else ADMIN_ROLE_NONE


def feature_permission_group_ids_for_role(role: str | None) -> tuple[str, ...]:
    r = normalize_admin_role_for_feature_perms(role)
    return USER_FEATURE_PERM_ROLE_VISIBLE_GROUP_IDS.get(
        r, USER_FEATURE_PERM_ROLE_VISIBLE_GROUP_IDS[ADMIN_ROLE_NONE]
    )


def feature_permission_keys_for_role(role: str | None) -> frozenset[str]:
    allowed_ids = set(feature_permission_group_ids_for_role(role))
    keys: list[str] = []
    for group in USER_FEATURE_PERM_GROUP_DEFS:
        if group["id"] in allowed_ids:
            keys.extend(group["keys"])
    return frozenset(keys)


def filter_batch_patch_for_role(role: str | None, patch: dict[str, str]) -> dict[str, str]:
    allowed = feature_permission_keys_for_role(role)
    return {k: v for k, v in patch.items() if k in allowed}


def validate_homogeneous_batch_users(users: list[User]) -> tuple[str | None, str | None]:
    """批量功能权限：所选账号须同一分级角色。返回 (role, error_message)。"""
    if not users:
        return None, "请至少选择一个账号"
    roles = {
        normalize_admin_role_for_feature_perms(getattr(u, "admin_role", None)) for u in users
    }
    if len(roles) > 1:
        return None, (
            "所选账号分级角色不一致，请仅勾选同一角色"
            "（普通用户 / 项目管理员 / 公司管理员）后再批量设置功能权限"
        )
    return next(iter(roles)), None


def backfill_default_deny_user_feature_permissions() -> int:
    """已有账号未配置的新功能入口从「跟随系统」落成禁止。返回更新条数。"""
    from . import db
    from .models import User

    updated = 0
    try:
        users = User.query.all()
    except Exception:
        return 0
    for user in users:
        raw = _coerce_feature_permissions_raw(getattr(user, "feature_permissions_json", None))
        stored = raw if isinstance(raw, dict) else {}
        if stored:
            stored = _expand_legacy_user_permissions(stored)
        if all(k in stored for k in USER_FEATURE_KEYS_DEFAULT_DENY):
            continue
        write_user_feature_permissions(user, stored)
        db.session.add(user)
        updated += 1
    if updated:
        db.session.commit()
    return updated
