# -*- coding: utf-8 -*-
"""页面0/1/2 功能入口：逗号分隔 slug 配置，展开为 legacy FEATURE_PAGE* 开关。"""
from __future__ import annotations

from typing import Optional

# 页面0 仅文档工具（手动上传，不带任务）
PAGE0_TOOL_SLUGS: tuple[str, ...] = ("draft_gen", "audit", "audit_modify", "translate")

# 页面1：文档工具 + 任务行签字/打印 + 顶栏考试中心
PAGE1_TOOL_SLUGS: tuple[str, ...] = PAGE0_TOOL_SLUGS + ("sign", "print", "exam_center")

# 页面2：任务行按钮 + 顶栏考试中心
PAGE2_TOOL_SLUGS: tuple[str, ...] = (
    "upload_replace",
    "draft_gen",
    "audit_modify",
    "translate",
    "exam_center",
)

SLUG_LABELS: dict[str, str] = {
    "draft_gen": "初稿生成",
    "audit": "文档审核",
    "audit_modify": "审核后修改",
    "translate": "文档翻译",
    "sign": "去签字",
    "print": "去打印",
    "exam_center": "考试训练中心",
    "upload_replace": "上传/替换",
}

PAGE0_SLUG_TO_FLAG: dict[str, str] = {
    "draft_gen": "FEATURE_PAGE0_DRAFT_GEN",
    "audit": "FEATURE_PAGE0_AUDIT",
    "audit_modify": "FEATURE_PAGE0_AUDIT_MODIFY",
    "translate": "FEATURE_PAGE0_TRANSLATE",
}

PAGE1_SLUG_TO_FLAG: dict[str, str] = {
    "draft_gen": "FEATURE_PAGE1_DRAFT_GEN",
    "audit": "FEATURE_PAGE1_AUDIT",
    "audit_modify": "FEATURE_PAGE1_AUDIT_MODIFY",
    "translate": "FEATURE_PAGE1_TRANSLATE",
    "sign": "FEATURE_PAGE1_SIGN",
    "print": "FEATURE_PAGE1_PRINT",
    "exam_center": "FEATURE_PAGE1_EXAM_CENTER",
}

PAGE2_SLUG_TO_FLAG: dict[str, str] = {
    "upload_replace": "FEATURE_PAGE2_UPLOAD_REPLACE",
    "draft_gen": "FEATURE_PAGE2_DRAFT_GEN",
    "audit_modify": "FEATURE_PAGE2_AUDIT_MODIFY",
    "translate": "FEATURE_PAGE2_TRANSLATE",
    "exam_center": "FEATURE_PAGE2_EXAM_CENTER",
}

FEATURE_TOOLS_CSV_KEYS: tuple[str, ...] = (
    "FEATURE_TOOLS_PAGE0",
    "FEATURE_TOOLS_PAGE1",
    "FEATURE_TOOLS_PAGE2",
)

PAGE0_DERIVED_FLAG_KEYS: tuple[str, ...] = tuple(PAGE0_SLUG_TO_FLAG.values())


def parse_feature_tools_csv(raw: Optional[str]) -> set[str]:
    if not raw:
        return set()
    out: set[str] = set()
    for part in str(raw).replace("，", ",").split(","):
        slug = part.strip().lower()
        if slug:
            out.add(slug)
    return out


def feature_tools_csv_from_slugs(slugs: set[str], *, allowed: tuple[str, ...]) -> str:
    order = {s: i for i, s in enumerate(allowed)}
    picked = [s for s in allowed if s in slugs]
    picked.sort(key=lambda s: order.get(s, 999))
    return ",".join(picked)


def feature_tools_csv_from_legacy_flags(
    flags: dict[str, bool],
    slug_to_flag: dict[str, str],
    *,
    allowed: tuple[str, ...],
) -> str:
    slugs = {slug for slug, key in slug_to_flag.items() if flags.get(key)}
    return feature_tools_csv_from_slugs(slugs, allowed=allowed)


def _legacy_page0_flags_from_page1(flags: dict[str, bool]) -> dict[str, bool]:
    """未配置 FEATURE_TOOLS_PAGE0 时，页面0 文档工具回退为页面1 同名文档工具开关。"""
    out: dict[str, bool] = {}
    for slug in PAGE0_TOOL_SLUGS:
        p0_key = PAGE0_SLUG_TO_FLAG[slug]
        p1_key = PAGE1_SLUG_TO_FLAG.get(slug)
        out[p0_key] = bool(flags.get(p1_key)) if p1_key else False
    return out


def _apply_slug_map_to_flags(flags: dict[str, bool], slugs: set[str], slug_to_flag: dict[str, str]) -> None:
    for slug, flag_key in slug_to_flag.items():
        flags[flag_key] = slug in slugs


def feature_tools_csv_configured_in_db(key: str, app=None) -> bool:
    from .app_settings import _feature_flag_configured_in_db

    return _feature_flag_configured_in_db(key, app)


def apply_feature_tools_csv_to_flags(flags: dict[str, bool], app=None) -> None:
    """按 FEATURE_TOOLS_PAGE* 覆盖 legacy 开关；并写入 FEATURE_PAGE0_* 衍生键。

    仅当 CSV 非空时才按 slug 覆盖；库中仅有空占位或未配置时仍读 legacy FEATURE_PAGE* 单项开关。
    """
    from .app_settings import get_setting

    page0_csv = (get_setting("FEATURE_TOOLS_PAGE0", default="", app=app) or "").strip()
    page1_csv = (get_setting("FEATURE_TOOLS_PAGE1", default="", app=app) or "").strip()
    page2_csv = (get_setting("FEATURE_TOOLS_PAGE2", default="", app=app) or "").strip()

    if page1_csv:
        _apply_slug_map_to_flags(flags, parse_feature_tools_csv(page1_csv), PAGE1_SLUG_TO_FLAG)
    if page2_csv:
        _apply_slug_map_to_flags(flags, parse_feature_tools_csv(page2_csv), PAGE2_SLUG_TO_FLAG)

    if page0_csv:
        page0_slugs = parse_feature_tools_csv(page0_csv)
        _apply_slug_map_to_flags(flags, page0_slugs, PAGE0_SLUG_TO_FLAG)
    else:
        for k, v in _legacy_page0_flags_from_page1(flags).items():
            flags[k] = v

    flags["FEATURE_EXAM_CENTER"] = bool(
        flags.get("FEATURE_PAGE1_EXAM_CENTER") or flags.get("FEATURE_PAGE2_EXAM_CENTER")
    )


def ensure_feature_tools_csv_in_settings(settings: dict[str, str]) -> None:
    """GET 系统配置：若 CSV 键为空，用当前 legacy 开关拼出默认展示值。"""
    flags = {k: bool(v and str(v).strip().lower() in {"1", "true", "yes", "on"}) for k, v in settings.items()}

    if not (settings.get("FEATURE_TOOLS_PAGE0") or "").strip():
        page0 = _legacy_page0_flags_from_page1(flags)
        settings["FEATURE_TOOLS_PAGE0"] = feature_tools_csv_from_legacy_flags(
            page0, PAGE0_SLUG_TO_FLAG, allowed=PAGE0_TOOL_SLUGS
        )
    if not (settings.get("FEATURE_TOOLS_PAGE1") or "").strip():
        settings["FEATURE_TOOLS_PAGE1"] = feature_tools_csv_from_legacy_flags(
            flags, PAGE1_SLUG_TO_FLAG, allowed=PAGE1_TOOL_SLUGS
        )
    if not (settings.get("FEATURE_TOOLS_PAGE2") or "").strip():
        settings["FEATURE_TOOLS_PAGE2"] = feature_tools_csv_from_legacy_flags(
            flags, PAGE2_SLUG_TO_FLAG, allowed=PAGE2_TOOL_SLUGS
        )


def sync_legacy_flags_from_tools_csv_updates(updates: dict[str, str]) -> list[str]:
    """保存系统配置：将 CSV 展开写入对应 FEATURE_PAGE* 键（未列出的 slug 置空关闭）。返回已写入的键名。"""
    from .app_settings import _upsert_config

    written: list[str] = []
    pairs = (
        ("FEATURE_TOOLS_PAGE1", PAGE1_SLUG_TO_FLAG),
        ("FEATURE_TOOLS_PAGE2", PAGE2_SLUG_TO_FLAG),
    )
    for csv_key, slug_map in pairs:
        if csv_key not in updates:
            continue
        slugs = parse_feature_tools_csv(updates.get(csv_key))
        raw_csv = (updates.get(csv_key) or "").strip()
        _upsert_config(csv_key, raw_csv)
        written.append(csv_key)
        for slug, flag_key in slug_map.items():
            _upsert_config(flag_key, "1" if slug in slugs else "")
            written.append(flag_key)
    if "FEATURE_TOOLS_PAGE0" in updates:
        raw_csv = (updates.get("FEATURE_TOOLS_PAGE0") or "").strip()
        _upsert_config("FEATURE_TOOLS_PAGE0", raw_csv)
        written.append("FEATURE_TOOLS_PAGE0")
    return written


def legacy_flags_synced_from_tools_csv() -> frozenset[str]:
    """由 FEATURE_TOOLS_PAGE1/2 CSV 同步写入的 legacy 键（保存时跳过表单重复写入）。"""
    return frozenset(PAGE1_SLUG_TO_FLAG.values()) | frozenset(PAGE2_SLUG_TO_FLAG.values())


def feature_tools_slug_hint(page: str) -> str:
    """供系统配置分区 hint 展示可选 slug。"""
    m = {
        "0": ", ".join(PAGE0_TOOL_SLUGS),
        "1": ", ".join(PAGE1_TOOL_SLUGS),
        "2": ", ".join(PAGE2_TOOL_SLUGS),
    }
    return m.get(page, "")
