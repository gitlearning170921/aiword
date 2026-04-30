# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import hashlib
import uuid
import socket
from datetime import date, datetime, time
from functools import wraps
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import or_
from urllib.error import HTTPError, URLError
from urllib.parse import quote as _urlquote
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from flask import (
    Blueprint,
    current_app,
    make_response,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

from . import db
from .doc_service import (
    download_template_from_url,
    extract_placeholders,
    extract_placeholders_from_bytes,
    generate_document,
)
from .models import (
    GenerateRecord, GenerationSummary, NoteAttachmentFile, UploadRecord, User,
    TaskTypeConfig, CompletionStatusConfig, AuditStatusConfig, NotifyTemplateConfig, AppConfig,
    Project, ModuleCascadeReminder, now_local,
    ExamBankIngestJob,
    ExamSetReviewJob,
    ExamCenterActivity,
    ExamCenterAssignment,
    ExamCenterActivityDetail,
    ExamCenterAssignmentExtra,
    ExamCenterAssignmentAudience,
    ExamAttempt,
    ExamAttemptItem,
    ExamGradingJob,
)
from . import dingtalk_service

bp = Blueprint("pages", __name__)


def _dingtalk_webhook_str() -> str:
    from .app_settings import get_setting
    return (get_setting("DINGTALK_WEBHOOK") or "").strip()


def _dingtalk_secret_opt() -> Optional[str]:
    from .app_settings import get_setting
    s = (get_setting("DINGTALK_SECRET") or "").strip()
    return s or None


def _quiz_api_base_url() -> str:
    from .app_settings import get_setting

    raw = get_setting(
        "QUIZ_API_BASE_URL",
        default=str(current_app.config.get("QUIZ_API_BASE_URL") or ""),
    )
    return (raw or "").strip().rstrip("/")


def _quiz_api_timeout_seconds() -> int:
    from .app_settings import get_setting

    raw = (
        get_setting(
            "QUIZ_API_TIMEOUT_SECONDS",
            default=str(current_app.config.get("QUIZ_API_TIMEOUT_SECONDS") or "20"),
        )
        or "20"
    ).strip()
    try:
        val = int(raw)
    except ValueError:
        val = 20
    if val < 3:
        return 3
    if val > 120:
        return 120
    return val


def _stats_upstream_quick_timeout_seconds() -> int:
    """带本地兜底（quiz/stats/*）的 GET：限制上游阻塞，默认最多 8s，仍可被较大 QUIZ_API_TIMEOUT_SECONDS 压低。"""
    return max(3, min(8, _quiz_api_timeout_seconds()))


def _quiz_attempt_answers_quick_timeout_seconds() -> int:
    """quiz/attempts/*/answers：题目列表略大，允许略长于 stats 兜底，但仍限制整段阻塞。"""
    return max(5, min(15, _quiz_api_timeout_seconds()))


def _items_from_activity_detail_snapshot(det: ExamCenterActivityDetail | None) -> list[Any]:
    """从提交时落库的 upstream_payload 尝试恢复题目行，供上游不可用时降级展示。"""
    if not det or not det.upstream_payload or not isinstance(det.upstream_payload, dict):
        return []
    pl = det.upstream_payload
    for key in ("items", "questions", "details", "attempt_items"):
        v = pl.get(key)
        if isinstance(v, list) and len(v) > 0:
            return v
    inner = pl.get("data") if isinstance(pl.get("data"), dict) else None
    if isinstance(inner, dict):
        for key in ("items", "questions", "details"):
            v = inner.get(key)
            if isinstance(v, list) and len(v) > 0:
                return v
    return []


def _quiz_api_headers() -> dict[str, str]:
    from .app_settings import get_setting

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    bearer = (get_setting("QUIZ_API_BEARER_TOKEN") or "").strip()
    secret = (get_setting("QUIZ_API_SECRET") or "").strip()
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if secret:
        headers["X-Integration-Secret"] = secret
    return headers


def _quiz_api_call(
    upstream_path: str,
    method: str = "GET",
    payload: Optional[dict[str, Any]] = None,
    query: Optional[dict[str, Any]] = None,
    timeout_seconds: Optional[int] = None,
) -> tuple[int, dict[str, Any]]:
    base_url = _quiz_api_base_url()
    trace_id = uuid.uuid4().hex
    req_method = (method or "GET").upper()
    request_url = ""
    if not base_url:
        return 503, {
            "code": "QUIZ_API_NOT_CONFIGURED",
            "message": "未配置考试训练中心后端地址，请在页面3系统配置中设置 QUIZ_API_BASE_URL",
            "data": None,
            "trace_id": trace_id,
            "request": {"url": request_url, "method": req_method, "upstreamPath": upstream_path},
        }

    url = f"{base_url}/{upstream_path.lstrip('/')}"
    if query:
        q = {k: v for k, v in query.items() if v is not None and str(v).strip() != ""}
        if q:
            url = f"{url}?{urlencode(q)}"
    request_url = url

    body_bytes = None
    if payload is not None and req_method in {"POST", "PUT", "PATCH", "DELETE"}:
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = Request(
        url=url,
        data=body_bytes,
        headers=_quiz_api_headers(),
        method=req_method,
    )

    try:
        _timeout = _quiz_api_timeout_seconds() if timeout_seconds is None else int(timeout_seconds)
        if _timeout < 1:
            _timeout = 1
        if _timeout > 120:
            _timeout = 120
        with urlopen(req, timeout=_timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw}
            return 200, {
                "code": 0,
                "message": "ok",
                "data": data,
                "trace_id": trace_id,
                "request": {"url": request_url, "method": req_method, "upstreamPath": upstream_path},
            }
    except HTTPError as e:
        raw = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        try:
            upstream = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            upstream = {"raw": raw}
        msg = (
            upstream.get("message")
            or upstream.get("detail")
            or f"考试训练中心请求失败（HTTP {e.code}）"
        )
        return e.code, {
            "code": "QUIZ_API_UPSTREAM_ERROR",
            "message": str(msg),
            "data": upstream,
            "trace_id": trace_id,
            "request": {"url": request_url, "method": req_method, "upstreamPath": upstream_path},
        }
    except URLError as e:
        return 503, {
            "code": "QUIZ_API_NETWORK_ERROR",
            "message": f"无法连接考试训练中心后端：{e.reason}",
            "data": None,
            "trace_id": trace_id,
            "request": {"url": request_url, "method": req_method, "upstreamPath": upstream_path},
        }
    except socket.timeout:
        return 504, {
            "code": "QUIZ_API_TIMEOUT",
            "message": (
                "考试训练中心后端响应超时。"
                "请检查 QUIZ_API_BASE_URL 是否正确、aicheckword 服务是否在运行，"
                "或在系统配置中调大 QUIZ_API_TIMEOUT_SECONDS（如 60）。"
            ),
            "data": {"timeoutSeconds": _timeout},
            "trace_id": trace_id,
            "request": {"url": request_url, "method": req_method, "upstreamPath": upstream_path},
        }
    except Exception as e:
        return 500, {
            "code": "QUIZ_API_UNKNOWN_ERROR",
            "message": f"考试训练中心请求异常：{e}",
            "data": None,
            "trace_id": trace_id,
            "request": {"url": request_url, "method": req_method, "upstreamPath": upstream_path},
        }


def _quiz_try_paths(
    paths: list[str],
    *,
    method: str,
    payload: Optional[dict[str, Any]] = None,
    query: Optional[dict[str, Any]] = None,
) -> tuple[int, dict[str, Any], list[str]]:
    """依次尝试多个上游路径（新旧路由不一致时兼容）。"""
    tried: list[str] = []
    last_status = 502
    last_payload: dict[str, Any] = {
        "code": "QUIZ_API_UNKNOWN_ERROR",
        "message": "未尝试任何上游请求",
        "data": None,
        "trace_id": uuid.uuid4().hex,
    }
    for p in paths:
        pp = (p or "").strip().lstrip("/")
        if not pp:
            continue
        tried.append(pp)
        st, pl = _quiz_api_call(pp, method=method, payload=payload, query=query)
        last_status, last_payload = int(st), pl if isinstance(pl, dict) else {"data": pl}
        if 200 <= last_status < 300:
            return last_status, last_payload, tried
        if last_status in (404, 405):
            continue
        return last_status, last_payload, tried
    return last_status, last_payload, tried


def _unwrap_quiz_api_success_data(pl: Any) -> Any:
    """_quiz_api_call 成功时整包为 {code:0, data: 上游JSON}，取出上游根对象。"""
    if not isinstance(pl, dict):
        return {}
    if pl.get("code") == 0 and "data" in pl:
        return pl.get("data")
    return pl


def _exam_activity_upstream_root_ok(root: dict[str, Any]) -> bool:
    """上游 JSON 根若含 code 字段，则仅当为成功码时视为业务成功。"""
    if "code" not in root:
        return True
    return root.get("code") in (0, "0", None, "")


def _json_sanitize_for_db(obj: Any, *, max_bytes: int = 4 * 1024 * 1024) -> dict[str, Any]:
    """将嵌套结构转为可被 db.JSON/MySQL 稳定序列化的 plain dict（避免 Decimal 等类型导致 flush 静默失败）。"""
    if not isinstance(obj, dict):
        obj = {}
    try:
        raw = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return {"aiword_upstream_payload_sanitize_error": True, "hint": "json.dumps_failed"}
    if len(raw.encode("utf-8")) > max_bytes:
        return {
            "aiword_upstream_payload_truncated": True,
            "max_bytes": max_bytes,
            "preview": raw[:8192],
        }
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {"aiword_upstream_payload_wrap": True, "value": out}
    except Exception:
        return {"aiword_upstream_payload_sanitize_error": True, "hint": "json.loads_failed"}


def _scan_grading_pending_failed(obj: Any, depth: int = 0) -> tuple[bool, bool]:
    """在嵌套字典中查找 grading_status：pending → 阅卷中；failed → 阅卷失败。"""
    if depth > 16 or obj is None:
        return False, False
    if isinstance(obj, list):
        p = f = False
        for x in obj:
            if isinstance(x, (dict, list)):
                cp, cf = _scan_grading_pending_failed(x, depth + 1)
                p = p or cp
                f = f or cf
        return p, f
    if not isinstance(obj, dict):
        return False, False
    g = str(obj.get("grading_status") or "").strip().casefold()
    pend = g == "pending"
    failed = g == "failed"
    for _k, v in obj.items():
        if isinstance(v, (dict, list)):
            cp, cf = _scan_grading_pending_failed(v, depth + 1)
            pend = pend or cp
            failed = failed or cf
        if pend and failed:
            break
    return pend, failed


def _extract_result_metrics(root: Any) -> dict[str, Any]:
    """尽量从上游结果中提取分数/对错/薄弱项建议（字段名兼容多形态）。"""
    if not isinstance(root, dict):
        return {}
    inner = root.get("data") if isinstance(root.get("data"), dict) else {}

    def _pick(*vals):
        for v in vals:
            if v is not None and str(v).strip() != "":
                return v
        return None

    score = _pick(root.get("score"), root.get("total_score"), inner.get("score"), inner.get("total_score"))
    total = _pick(root.get("max_score"), root.get("full_score"), inner.get("max_score"), inner.get("full_score"))
    correct = _pick(root.get("correct_count"), root.get("correct"), inner.get("correct_count"), inner.get("correct"))
    wrong = _pick(root.get("wrong_count"), root.get("wrong"), inner.get("wrong_count"), inner.get("wrong"))
    weakness = _pick(root.get("weakness"), root.get("weak_points"), inner.get("weakness"), inner.get("weak_points"))
    reco = _pick(
        root.get("next_step"), root.get("recommendation"), root.get("suggestion"),
        inner.get("next_step"), inner.get("recommendation"), inner.get("suggestion")
    )
    gp, gf = _scan_grading_pending_failed(root)
    out: dict[str, Any] = {
        "score": None,
        "total_score": None,
        "correct_count": None,
        "wrong_count": None,
        "grading_pending": gp,
        "grading_failed": gf,
    }
    try:
        out["score"] = float(score) if score is not None else None
    except Exception:
        out["score"] = None
    try:
        out["total_score"] = float(total) if total is not None else None
    except Exception:
        out["total_score"] = None
    try:
        out["correct_count"] = int(correct) if correct is not None else None
    except Exception:
        out["correct_count"] = None
    try:
        out["wrong_count"] = int(wrong) if wrong is not None else None
    except Exception:
        out["wrong_count"] = None
    if gp:
        out["score"] = None
        out["total_score"] = None
        out["correct_count"] = None
        out["wrong_count"] = None
    out["weakness"] = str(weakness)[:1000] if weakness is not None and str(weakness).strip() else None
    out["recommendation"] = str(reco)[:1000] if reco is not None and str(reco).strip() else None
    return out


def _exam_pass_score() -> float:
    from .app_settings import get_setting

    raw = str(get_setting("EXAM_PASS_SCORE") or "80").strip()
    try:
        v = float(raw)
    except Exception:
        v = 80.0
    if v < 0:
        v = 0.0
    if v > 1000:
        v = 1000.0
    return v


def _norm_answer_plain(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        try:
            return json.dumps(v, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(v)
    return str(v).strip()


def _activity_item_options(row: dict[str, Any]) -> list[Any]:
    raw = row.get("options") or row.get("choices")
    if isinstance(raw, str) and raw.strip():
        try:
            p = json.loads(raw)
            return list(p) if isinstance(p, list) else []
        except Exception:
            return []
    return list(raw) if isinstance(raw, list) else []


def _letter_choice_index_activity(raw: Any) -> int | None:
    if raw is None or isinstance(raw, (dict, list)):
        return None
    s = str(raw).strip().upper()
    if len(s) != 1 or s < "A" or s > "Z":
        return None
    return ord(s) - ord("A")


def _resolve_letter_to_option_aiword(value: Any, options: list[Any]) -> Any:
    if not options:
        return value
    ix = _letter_choice_index_activity(value)
    if ix is None or ix >= len(options):
        return value
    return options[ix]


def _true_false_to_bool_aiword(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v) != 0.0
    if isinstance(v, str):
        t = v.strip().lower()
        if t in ("false", "0", "no", "n", "f", "wrong", "错误", "错", "否", "不正确", "不对"):
            return False
        if t in ("true", "1", "yes", "y", "t", "正确", "对", "是", "√"):
            return True
        return False
    return False


def _tf_maybe_literal_aiword(v: Any) -> bool:
    if isinstance(v, bool):
        return True
    if not isinstance(v, str):
        return False
    s = v.strip()
    sl = s.lower()
    if sl in ("true", "false", "1", "0"):
        return True
    return s in ("正确", "错误", "对", "错", "是", "否")


def _norm_single_choice_key_aiword(value: Any, options: list[Any]) -> str:
    v = _resolve_letter_to_option_aiword(value, options)
    if v is None:
        return ""
    return str(v).strip().lower()


def _norm_multiple_choice_set_aiword(raw: Any, options: list[Any]) -> set[str]:
    if raw is None:
        return set()
    items = raw if isinstance(raw, list) else [raw]
    out: set[str] = set()
    for x in items:
        v = _resolve_letter_to_option_aiword(x, options)
        k = str(v).strip().lower() if v is not None else ""
        if k:
            out.add(k)
    return out


def _question_type_from_activity_row(row: dict[str, Any]) -> str:
    return str(row.get("question_type") or row.get("type") or "").strip().lower()


def _objective_answers_equivalent_aiword(row: dict[str, Any], ua: Any, ca: Any) -> bool:
    """与 aicheckword quiz 判分维度对齐：选项字母先解析为选项原文，判断题再按真假比较。"""
    opts = _activity_item_options(row)
    qt = _question_type_from_activity_row(row)
    if qt == "true_false":
        aa = _resolve_letter_to_option_aiword(ca, opts)
        uu = _resolve_letter_to_option_aiword(ua, opts)
        return _true_false_to_bool_aiword(aa) == _true_false_to_bool_aiword(uu)
    if qt == "single_choice":
        return _norm_single_choice_key_aiword(ua, opts) == _norm_single_choice_key_aiword(ca, opts)
    if qt == "multiple_choice":
        s_ca = _norm_multiple_choice_set_aiword(ca, opts)
        s_ua = _norm_multiple_choice_set_aiword(ua, opts)
        return bool(s_ca) and s_ca == s_ua
    if opts:
        if _norm_single_choice_key_aiword(ua, opts) == _norm_single_choice_key_aiword(ca, opts):
            return True
        u_r = _resolve_letter_to_option_aiword(ua, opts)
        c_r = _resolve_letter_to_option_aiword(ca, opts)
        if isinstance(c_r, bool) or _tf_maybe_literal_aiword(c_r) or _tf_maybe_literal_aiword(u_r):
            return _true_false_to_bool_aiword(c_r) == _true_false_to_bool_aiword(u_r)
    return _norm_answer_plain(ua) == _norm_answer_plain(ca)


def _exam_activity_history_result_text(mode: str, metrics: dict[str, Any], raw_msg: Any) -> str:
    """列表「结果」列：用分数推导通过/不通过，避免出现英文 ok。"""
    try:
        if metrics.get("grading_pending"):
            return "阅卷中"
        if metrics.get("grading_failed"):
            return "阅卷失败"
        sc = metrics.get("score")
        if sc is not None:
            thr = float(_exam_pass_score())
            fv = float(sc)
            return "通过" if fv >= thr - 1e-9 else "不通过"
    except Exception:
        pass
    s = str(raw_msg or "").strip()
    low = s.casefold()
    if not s or low in ("ok", "success"):
        return "已提交"
    return s[:500]


def _first_nested_item_list(up: Any, depth: int = 6) -> list[dict[str, Any]]:
    """从上游结果树中挑出首个「题目明细」数组（dict list）。"""
    if depth <= 0 or not isinstance(up, dict):
        return []
    for key in ("items", "questions", "attempt_items", "details"):
        raw = up.get(key)
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):
            return [x for x in raw if isinstance(x, dict)]
    inn = up.get("data") if isinstance(up.get("data"), dict) else None
    if isinstance(inn, dict):
        nested = _first_nested_item_list(inn, depth - 1)
        if nested:
            return nested
    return []


def _qid_from_any_row(it: dict[str, Any]) -> str:
    return str(it.get("question_id") or it.get("questionId") or it.get("id") or "").strip()


def _upstream_row_user_answer(base: dict[str, Any]) -> Any:
    for k in (
        "user_answer",
        "selected_answer",
        "userAnswer",
        "student_answer",
        "response",
        "selected",
        "response_text",
    ):
        if k in base and base.get(k) not in (None, ""):
            return base.get(k)
    return None


def _standard_answer_any_row(it: dict[str, Any]) -> Any:
    return (
        it.get("correct_answer")
        if it.get("correct_answer") is not None
        else it.get("answer")
        if it.get("answer") is not None
        else (
            it.get("standard_answer")
            if it.get("standard_answer") is not None
            else it.get("solution")
        )
    )


def _merge_upstream_snapshot_with_submitted_answers(up_root: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """
    合并请求体中学生作答与题干快照（submission_questions_snapshot），写入顶层 items，
    供详情弹窗降级为本地快照时仍能展示 student_answer（user_answer）。
    """
    out = dict(up_root or {})
    raw_answers = body.get("answers") or []
    ans_rows: list[dict[str, Any]] = []
    if isinstance(raw_answers, dict):
        ans_rows = [{"question_id": str(k), "answer": v} for k, v in raw_answers.items() if str(k).strip()]
    elif isinstance(raw_answers, list):
        ans_rows = [x for x in raw_answers if isinstance(x, dict)]
    by_qid: dict[str, Any] = {}
    for r in ans_rows:
        q = str(r.get("question_id") or "").strip()
        if not q:
            continue
        if r.get("answer") is not None:
            by_qid[q] = r.get("answer")
        elif r.get("user_answer") is not None:
            by_qid[q] = r.get("user_answer")
    stem_map: dict[str, str] = {}
    snaps = body.get("submission_questions_snapshot") or body.get("questions_snapshot") or []
    if isinstance(snaps, list):
        for s in snaps:
            if isinstance(s, dict):
                qi = _qid_from_any_row(s)
                if qi:
                    stem_map[qi] = str(s.get("stem") or s.get("title") or "").strip()

    upstream_items = _first_nested_item_list(out)

    def _finalize_row(base: dict[str, Any], qid: str) -> dict[str, Any]:
        row = dict(base)
        ua_v = _upstream_row_user_answer(row)
        if ua_v is None:
            ua_v = by_qid.get(qid)
        row["user_answer"] = ua_v
        stem_f = stem_map.get(qid) or ""
        if stem_f and not str(row.get("stem") or "").strip():
            row["stem"] = stem_f
        ca_v = row.get("correct_answer")
        if ca_v is None:
            ca_v = _standard_answer_any_row(row)
            if ca_v is not None:
                row.setdefault("answer", ca_v)

        needs_compare = ua_v is not None and ca_v is not None
        ic_any = row.get("is_correct")
        if ic_any is None:
            ic_any = row.get("isCorrect")
        if ic_any in (0, 1, True, False):
            row["is_correct"] = bool(ic_any)
        elif needs_compare:
            row["is_correct"] = _objective_answers_equivalent_aiword(row, ua_v, ca_v)
        else:
            row["is_correct"] = None
        return row

    merged: list[dict[str, Any]] = []

    if upstream_items:
        by_up: dict[str, dict[str, Any]] = {}
        ordered_ids: list[str] = []
        for ix, x in enumerate(upstream_items):
            qid = _qid_from_any_row(x) or ("uq-" + str(ix))
            if qid not in by_up:
                ordered_ids.append(qid)
                by_up[qid] = dict(x)
        for qid in by_qid:
            if qid not in by_up:
                ordered_ids.append(qid)

        ids = ordered_ids if ordered_ids else sorted(by_qid.keys())

        if not ids:
            ids = [
                (_qid_from_any_row(upstream_items[idx]) or ("uq-" + str(idx)))
                for idx in range(len(upstream_items))
            ]

        seen: set[str] = set()

        def _consume(qid: str) -> dict[str, Any]:
            blk = dict(by_up[qid]) if qid in by_up else {"question_id": qid}
            return _finalize_row(blk, qid)

        for qid in ids:
            qid_key = qid.strip()
            if not qid_key or qid_key in seen:
                continue
            merged.append(_consume(qid_key))
            seen.add(qid_key)

    if not merged and by_qid:
        for qid, ua in sorted(by_qid.items()):
            merged.append(_finalize_row({"question_id": qid}, qid))

    if merged:
        out["items"] = merged
        out["attempt_items"] = merged
        out["attempt_snapshot_aiword_v1"] = True
        if isinstance(out.get("data"), dict):
            od = dict(out["data"])
            od["items"] = merged
            out["data"] = od

    elif ans_rows:
        mini = [
            {
                "question_id": str(a.get("question_id") or ""),
                "stem": stem_map.get(str(a.get("question_id") or ""), ""),
                "user_answer": a.get("answer"),
                "answer": None,
                "is_correct": None,
            }
            for a in ans_rows
            if isinstance(a, dict)
        ]
        out["attempt_items"] = mini
        out["items"] = mini
        out["attempt_snapshot_aiword_v1"] = True

    return out


def _log_student_exam_center_activity(
    *,
    mode: str,
    exam_track: str | None,
    set_id: str | None,
    assignment_id: str | None,
    assignment_label: str | None,
    attempt_id: str | None,
    upstream_http_status: int,
    upstream_trace_id: str | None,
    result_summary: str | None,
    upstream_result_payload: dict[str, Any] | None = None,
) -> None:
    uid = str(session.get("user_id") or "").strip()
    if not uid:
        try:
            current_app.logger.warning("exam_center_activity_skip_no_uid_in_session mode=%s", mode)
        except Exception:
            pass
        return
    try:
        # 优先使用当前会话身份，保证记录名与页面2当前登录用户一致
        s_username = str(session.get("username") or "").strip()
        s_display_name = str(session.get("display_name") or "").strip()
        u = User.query.filter_by(id=uid).first()
        username = s_username or (u.username if u else "")
        display_name = s_display_name or ((u.display_name or u.username) if u else "")
        row = ExamCenterActivity(
            user_id=uid,
            username=str(username) if username else None,
            display_name=str(display_name) if display_name else None,
            mode=str(mode or "").strip()[:16] or "unknown",
            exam_track=(exam_track or "").strip() or None,
            set_id=(set_id or "").strip() or None,
            assignment_id=(assignment_id or "").strip() or None,
            assignment_label=(assignment_label or "").strip() or None,
            attempt_id=(attempt_id or "").strip() or None,
            upstream_http_status=int(upstream_http_status),
            upstream_trace_id=(upstream_trace_id or "").strip() or None,
            result_summary=(result_summary or "").strip()[:500] or None,
        )
        db.session.add(row)
        db.session.flush()

        if upstream_result_payload and isinstance(upstream_result_payload, dict):
            try:
                safe_pl = _json_sanitize_for_db(upstream_result_payload)
                m = _extract_result_metrics(safe_pl)
                detail = ExamCenterActivityDetail(
                    activity_id=row.id,
                    mode=row.mode,
                    score=m.get("score"),
                    total_score=m.get("total_score"),
                    correct_count=m.get("correct_count"),
                    wrong_count=m.get("wrong_count"),
                    weakness=m.get("weakness"),
                    recommendation=m.get("recommendation"),
                    upstream_payload=safe_pl,
                )
                # 明细写入失败不应拖垮主表 INSERT（原先整段 rollback 会变成「看起来像没落库」）
                with db.session.begin_nested():
                    db.session.add(detail)
            except Exception as detail_exc:
                try:
                    current_app.logger.warning(
                        "exam_center_activity_detail_skipped uid=%s mode=%s activity_id=%s: %s",
                        uid,
                        mode,
                        row.id,
                        detail_exc,
                        exc_info=True,
                    )
                except Exception:
                    pass

        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        try:
            current_app.logger.exception(
                "exam_center_activity_persist_failed uid=%s mode=%s attempt_id=%s: %s",
                uid,
                mode,
                (attempt_id or "").strip(),
                exc,
            )
        except Exception:
            pass


def _extract_assignments_from_quiz_root(root: Any) -> list[dict[str, Any]]:
    if not isinstance(root, dict):
        return []
    inner = root.get("data") if isinstance(root.get("data"), dict) else None
    cands: list[Any] = [
        root.get("assignments"),
        root.get("items"),
        inner.get("assignments") if inner else None,
        inner.get("items") if inner else None,
    ]
    for c in cands:
        if isinstance(c, list) and c:
            return [x for x in c if isinstance(x, dict)]
    for c in cands:
        if isinstance(c, list):
            return [x for x in c if isinstance(x, dict)]
    return []


_ASSIGNMENT_DUE_KEYS: tuple[str, ...] = (
    "due_at",
    "dueAt",
    "due_date",
    "dueDate",
    "deadline",
    "complete_before",
    "completeBefore",
)


def _parse_assignment_due_from_request(req: dict[str, Any]) -> tuple[Optional[datetime], bool]:
    """从老师下发请求解析截止完成时间。(due_at, 是否应更新镜像字段)；未出现任何 due 相关键则第二项为 False。"""
    if not isinstance(req, dict):
        return None, False
    specified = False
    raw: Any = None
    for k in _ASSIGNMENT_DUE_KEYS:
        if k not in req:
            continue
        specified = True
        v = req.get(k)
        if v is not None and str(v).strip() != "":
            raw = v
            break
    if not specified:
        return None, False
    if raw is None:
        return None, True
    s = str(raw).strip()
    if not s:
        return None, True
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s) and "T" not in s and " " not in s:
        try:
            d0 = date.fromisoformat(s)
            return datetime.combine(d0, time(23, 59, 59)), True
        except ValueError:
            return None, True
    s_norm = s.replace("Z", "+00:00")
    cand = s_norm.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(cand)
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        return dt, True
    except ValueError:
        return None, True


def _deadline_completion_from_exam_rows(
    rows: list[Any], due_end: Optional[datetime]
) -> dict[str, Any]:
    """按 assignment 下每名用户首次 mode=exam 的 created_at 与截止时刻统计按时/逾期。"""
    first: dict[str, datetime] = {}
    for r in rows:
        if str(getattr(r, "mode", None) or "").lower() != "exam":
            continue
        uid = str(getattr(r, "user_id", None) or "").strip()
        ca = getattr(r, "created_at", None)
        if not uid or not ca:
            continue
        prev = first.get(uid)
        if prev is None or ca < prev:
            first[uid] = ca
    out: dict[str, Any] = {
        "due_at": due_end.isoformat() if due_end else None,
        "exam_students_submitted": len(first),
        "on_time_count": None,
        "late_count": None,
    }
    if not due_end:
        out["note"] = "未配置截止时间，无法区分按时/逾期。"
        return out
    on_time = 0
    late = 0
    for _uid, ts in first.items():
        if ts <= due_end:
            on_time += 1
        else:
            late += 1
    out["on_time_count"] = on_time
    out["late_count"] = late
    out["note"] = "按每名学生在任务下首次考试提交时间与截止时刻比对（本地 activity.created_at）。"
    return out


def _normalize_student_assignment_row(x: dict[str, Any]) -> dict[str, Any]:
    aid = str(x.get("assignment_id") or x.get("id") or x.get("assignmentId") or "").strip()
    title = str(x.get("title") or x.get("name") or x.get("label") or aid).strip() or aid
    row: dict[str, Any] = {"id": aid, "name": title, "label": title}
    diff = str(x.get("difficulty") or x.get("difficulty_level") or x.get("difficultyLevel") or "").strip().lower()
    if diff in ("easy", "medium", "hard"):
        row["difficulty"] = diff
    for dk in ("due_at", "dueAt", "due_date", "dueDate"):
        dv = x.get(dk)
        if dv is not None and str(dv).strip():
            row["due_at"] = str(dv).strip()
            break
    return row


def _difficulty_from_quiz_get_set_payload(pl: dict[str, Any]) -> str:
    """从 quiz/sets/{id} 网关响应中解析套题难度（与 aicheckword set_config.difficulty 一致）。"""
    up = _unwrap_quiz_api_success_data(pl)
    if not isinstance(up, dict):
        return ""
    root = up.get("data") if up.get("ok") is True and isinstance(up.get("data"), dict) else up
    if not isinstance(root, dict):
        return ""
    cfg = root.get("set_config") or root.get("setConfig") or {}
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    if not isinstance(cfg, dict):
        return ""
    d = str(cfg.get("difficulty") or "").strip().lower()
    return d if d in ("easy", "medium", "hard") else ""


def _extract_assignment_from_quiz_payload(payload: dict[str, Any]) -> tuple[str, str, str | None]:
    """从 quiz/assignments 返回中提取 assignment_id/title/set_id。"""
    root = _unwrap_quiz_api_success_data(payload)
    if not isinstance(root, dict):
        root = {}
    inner = root.get("data") if isinstance(root.get("data"), dict) else {}
    aid = str(
        root.get("assignment_id")
        or root.get("assignmentId")
        or root.get("id")
        or inner.get("assignment_id")
        or inner.get("assignmentId")
        or inner.get("id")
        or ""
    ).strip()
    title = str(
        root.get("title")
        or root.get("name")
        or root.get("label")
        or inner.get("title")
        or inner.get("name")
        or inner.get("label")
        or aid
    ).strip() or aid
    set_id = str(root.get("set_id") or root.get("setId") or inner.get("set_id") or inner.get("setId") or "").strip() or None
    return aid, title, set_id


def _expand_question_count_aliases(body: dict[str, Any]) -> dict[str, Any]:
    """aicheckword 各版本字段名不一致时，把题量同步写入多种常见键名。"""
    out = dict(body or {})
    raw = (
        out.get("question_count")
        or out.get("questionCount")
        or out.get("count")
        or out.get("size")
        or out.get("num_questions")
        or out.get("numQuestions")
        or out.get("n")
        or out.get("target_count")
        or out.get("targetCount")
    )
    try:
        n = int(raw) if raw is not None and str(raw).strip() != "" else None
    except (TypeError, ValueError):
        n = None
    if n is None:
        return out
    n = max(1, min(n, 500))
    for key in (
        "question_count",
        "questionCount",
        "count",
        "size",
        "num_questions",
        "numQuestions",
        "n",
        "target_count",
        "targetCount",
    ):
        out[key] = n
    return out


def _expand_exam_track_and_difficulty_aliases(body: dict[str, Any]) -> dict[str, Any]:
    """体考类型、难度与页面设置对齐：写入多种常见键名，避免上游只认 camelCase 或其它字段。"""
    out = dict(body or {})
    track_raw = (
        out.get("exam_track")
        or out.get("examTrack")
        or out.get("track")
        or out.get("exam_type")
        or out.get("examType")
        or out.get("exam_track_code")
        or ""
    )
    track = str(track_raw).strip() or "cn"
    for key in (
        "exam_track",
        "examTrack",
        "track",
        "exam_type",
        "examType",
    ):
        out[key] = track

    diff_raw = (
        out.get("difficulty")
        or out.get("difficulty_level")
        or out.get("difficultyLevel")
        or out.get("level")
        or out.get("diffLevel")
    )
    if diff_raw is None or str(diff_raw).strip() == "":
        return out
    diff = str(diff_raw).strip()
    for key in ("difficulty", "difficulty_level", "difficultyLevel", "level", "diffLevel"):
        out[key] = diff
    return out


_EXAM_TRACK_REQUIREMENT_PROFILES: dict[str, dict[str, Any]] = {
    "cn": {
        "title": "国内体考",
        "scopes": ["GMP", "核查指南"],
        "min_total_questions": 200,
        "topic_groups": [
            {"topic": "GMP", "keywords": ["gmp", "药品生产质量管理规范", "生产质量管理规范"]},
            {"topic": "核查指南", "keywords": ["核查指南", "核查要点", "检查指南"]},
        ],
    },
    "iso13485": {
        "title": "13485体考",
        "scopes": ["ISO13485", "MDR"],
        "min_total_questions": 180,
        "topic_groups": [
            {"topic": "ISO13485", "keywords": ["iso13485", "iso 13485", "13485"]},
            {"topic": "MDR", "keywords": ["mdr", "eu 2017/745", "2017/745"]},
        ],
    },
    "mdsap": {
        "title": "MDSAP体考",
        "scopes": ["MDSAP", "5国法规"],
        "min_total_questions": 220,
        "topic_groups": [
            {"topic": "MDSAP", "keywords": ["mdsap", "审计方法", "audit model"]},
            {"topic": "美国法规", "keywords": ["fda", "21 cfr", "usa", "美国"]},
            {"topic": "加拿大法规", "keywords": ["canada", "sor/98-282", "cmdr", "加拿大"]},
            {"topic": "巴西法规", "keywords": ["anvisa", "brazil", "巴西"]},
            {"topic": "日本法规", "keywords": ["pmda", "mhlw", "japan", "日本"]},
            {"topic": "澳大利亚法规", "keywords": ["tga", "australia", "澳大利亚"]},
        ],
    },
}
_EXAM_BATCH_INGEST_SIZE = 50
_EXAM_REQUIREMENT_BASELINE_KEY = "EXAM_BANK_REQUIREMENT_BASELINES_JSON"


def _exam_track_policy_version_key(track: str) -> str:
    return f"EXAM_TRACK_REG_POLICY_VERSION_{_normalize_exam_track(track).upper()}"


def _get_exam_track_policy_version(track: str) -> str:
    """人工配置法规版本（兜底/强制覆盖）。"""
    row = AppConfig.query.filter_by(config_key=_exam_track_policy_version_key(track)).first()
    return str(row.config_value if row and row.config_value is not None else "").strip()


def _set_exam_track_policy_version(track: str, version_value: str) -> None:
    key = _exam_track_policy_version_key(track)
    row = AppConfig.query.filter_by(config_key=key).first()
    v = str(version_value or "").strip()
    if row:
        row.config_value = v
    else:
        db.session.add(AppConfig(config_key=key, config_value=v))


def _extract_policy_version_tokens_from_text(text: str) -> list[str]:
    s = str(text or "")
    if not s:
        return []
    pats = [
        r"ISO\s*13485[:：]?\s*\d{4}",
        r"(?:EU\s*)?20\d{2}\s*/\s*\d{3,4}",
        r"MDSAP(?:\s*Audit\s*Model)?\s*(?:v|V)?\d+(?:\.\d+)?",
        r"21\s*CFR(?:\s*Part)?\s*\d+",
        r"SOR\s*/\s*\d{2,4}\s*-\s*\d+",
        r"YY/T\s*\d{3,6}(?:\.\d+)?(?:-\d{4})?",
        r"GB\s*/\s*T\s*\d{3,6}(?:\.\d+)?(?:-\d{4})?",
        r"(?:GMP|核查指南|MDR|FDA|ANVISA|PMDA|TGA)[^,\n;，；]{0,18}(?:20\d{2}|v\d+(?:\.\d+)?)",
    ]
    out: list[str] = []
    for p in pats:
        try:
            for m in re.findall(p, s, flags=re.IGNORECASE):
                t = str(m).strip()
                if t and t not in out:
                    out.append(t)
        except Exception:
            continue
    return out


def _get_exam_track_policy_version_auto(track_raw: Any) -> dict[str, Any]:
    """自动识别法规版本，返回版本+置信度+证据。"""
    track = _normalize_exam_track(track_raw)
    empty = {"version": "", "confidence": "none", "evidence": None}
    track_keys_map: dict[str, list[str]] = {
        "cn": ["gmp", "核查", "核查指南", "检查指南", "生产质量管理规范"],
        "iso13485": ["iso13485", "iso 13485", "13485", "mdr", "2017/745", "eu 2017"],
        "mdsap": ["mdsap", "fda", "21 cfr", "anvisa", "pmda", "tga", "sor/", "canada"],
    }
    keys = track_keys_map.get(track, [])
    rows = UploadRecord.query.order_by(UploadRecord.updated_at.desc()).limit(3000).all()
    for r in rows:
        txt = " ".join(
            [
                str(getattr(r, "task_type", None) or ""),
                str(getattr(r, "file_name", None) or ""),
                str(getattr(r, "project_name", None) or ""),
                str(getattr(r, "notes", None) or ""),
                str(getattr(r, "project_notes", None) or ""),
            ]
        )
        txt_l = txt.lower()
        if keys and not any(k in txt_l for k in keys):
            continue
        ev_base = {
            "upload_id": str(getattr(r, "id", "") or ""),
            "file_name": str(getattr(r, "file_name", "") or ""),
            "updated_at": getattr(r, "updated_at", None).isoformat() if getattr(r, "updated_at", None) else None,
        }
        fv = str(getattr(r, "file_version", None) or "").strip()
        rv = str(getattr(r, "registration_version", None) or "").strip()
        if fv:
            return {
                "version": fv,
                "confidence": "high",
                "evidence": {**ev_base, "matched_by": "file_version"},
            }
        if rv:
            return {
                "version": rv,
                "confidence": "high",
                "evidence": {**ev_base, "matched_by": "registration_version"},
            }
        toks = _extract_policy_version_tokens_from_text(txt)
        if toks:
            return {
                "version": toks[0],
                "confidence": "medium",
                "evidence": {**ev_base, "matched_by": "text_regex", "matched_token": toks[0]},
            }
    return empty


def _resolve_exam_track_policy_version(track_raw: Any) -> dict[str, Any]:
    """返回生效版本、来源、置信度与证据。"""
    track = _normalize_exam_track(track_raw)
    auto_info = _get_exam_track_policy_version_auto(track)
    auto_v = str(auto_info.get("version") or "").strip() if isinstance(auto_info, dict) else ""
    fallback_v = _get_exam_track_policy_version(track)
    if auto_v:
        return {
            "effective_policy_version": auto_v,
            "policy_version_source": "auto",
            "auto_policy_version": auto_v,
            "fallback_policy_version": fallback_v,
            "policy_version_confidence": str(auto_info.get("confidence") or "medium"),
            "policy_version_evidence": auto_info.get("evidence"),
        }
    if fallback_v:
        return {
            "effective_policy_version": fallback_v,
            "policy_version_source": "fallback",
            "auto_policy_version": "",
            "fallback_policy_version": fallback_v,
            "policy_version_confidence": "fallback",
            "policy_version_evidence": None,
        }
    return {
        "effective_policy_version": "",
        "policy_version_source": "none",
        "auto_policy_version": "",
        "fallback_policy_version": "",
        "policy_version_confidence": "none",
        "policy_version_evidence": None,
    }


def _normalize_exam_track(v: Any) -> str:
    s = str(v or "").strip().lower()
    if s in _EXAM_TRACK_REQUIREMENT_PROFILES:
        return s
    if s in {"iso", "13485", "iso_13485"}:
        return "iso13485"
    if s in {"cn", "china"}:
        return "cn"
    if s in {"mdsap", "m_dsap"}:
        return "mdsap"
    return "cn"


def _app_config_get_json(config_key: str, fallback: Any) -> Any:
    row = AppConfig.query.filter_by(config_key=config_key).first()
    raw = str(row.config_value).strip() if row and row.config_value is not None else ""
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _app_config_set_json(config_key: str, value: Any) -> None:
    row = AppConfig.query.filter_by(config_key=config_key).first()
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if row:
        row.config_value = payload
    else:
        db.session.add(AppConfig(config_key=config_key, config_value=payload))


def _extract_total_from_bank_payload(payload: dict[str, Any]) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    root = _unwrap_quiz_api_success_data(payload)
    if not isinstance(root, dict):
        root = {}
    inner = root.get("data") if isinstance(root.get("data"), dict) else {}
    cands = [
        root.get("total"),
        root.get("count"),
        root.get("matched_total"),
        inner.get("total"),
        inner.get("count"),
        inner.get("matched_total"),
    ]
    for c in cands:
        try:
            if c is None or str(c).strip() == "":
                continue
            n = int(c)
            if n >= 0:
                return n
        except Exception:
            continue
    items = _extract_bank_items_from_list_root(root)
    if isinstance(items, list):
        return len(items)
    return None


def _query_bank_total_for_track(track: str, keyword: str | None = None) -> int:
    q: dict[str, Any] = {
        "limit": "1",
        "offset": "0",
        "exam_track": track,
        "examTrack": track,
        "track": track,
    }
    if keyword:
        q["q"] = keyword
    st, pl, _ = _quiz_try_paths(
        ["quiz/bank/questions", "quiz/questions", "quiz/bank/question-list"],
        method="GET",
        query=q,
    )
    if not (200 <= int(st) < 300 and isinstance(pl, dict)):
        return 0
    n = _extract_total_from_bank_payload(pl)
    return max(0, int(n or 0))


def _collect_exam_knowledge_markers(track: str) -> dict[str, Optional[datetime]]:
    track = _normalize_exam_track(track)
    track_keys_map: dict[str, list[str]] = {
        "cn": ["gmp", "核查", "核查指南", "检查指南", "生产质量管理规范"],
        "iso13485": ["iso13485", "13485", "mdr", "2017/745", "欧盟"],
        "mdsap": ["mdsap", "fda", "anvisa", "pmda", "tga", "canada", "5国", "五国"],
    }
    track_keys = track_keys_map.get(track, [])
    regs_global = ["法规", "regulation", "guideline", "指南", "标准", "standard"]
    proc_keys = ["程序", "procedure", "sop", "作业指导", "管理规程"]
    case_keys = ["案例", "case", "项目案例", "project case"]
    marker: dict[str, Optional[datetime]] = {
        "regulations_at": None,
        "procedures_at": None,
        "project_case_at": None,
    }
    rows = UploadRecord.query.order_by(UploadRecord.updated_at.desc()).limit(3000).all()
    for r in rows:
        upd = getattr(r, "updated_at", None)
        if not upd:
            continue
        txt = " ".join(
            [
                str(getattr(r, "task_type", None) or ""),
                str(getattr(r, "file_name", None) or ""),
                str(getattr(r, "project_name", None) or ""),
                str(getattr(r, "notes", None) or ""),
                str(getattr(r, "project_notes", None) or ""),
            ]
        ).lower()
        if any(k in txt for k in (track_keys + regs_global)):
            if marker["regulations_at"] is None or upd > marker["regulations_at"]:
                marker["regulations_at"] = upd
        if any(k in txt for k in proc_keys):
            if marker["procedures_at"] is None or upd > marker["procedures_at"]:
                marker["procedures_at"] = upd
        if any(k in txt for k in case_keys):
            if marker["project_case_at"] is None or upd > marker["project_case_at"]:
                marker["project_case_at"] = upd
    return marker


def _build_exam_bank_requirement_status(track_raw: Any) -> dict[str, Any]:
    track = _normalize_exam_track(track_raw)
    prof = _EXAM_TRACK_REQUIREMENT_PROFILES.get(track) or _EXAM_TRACK_REQUIREMENT_PROFILES["cn"]
    total = _query_bank_total_for_track(track, keyword=None)
    topic_checks: list[dict[str, Any]] = []
    missing_topics: list[str] = []
    for g in prof.get("topic_groups") or []:
        kws = [str(k).strip() for k in (g.get("keywords") or []) if str(k).strip()]
        # 每个主题只取第 1 关键词做轻量检索，避免单次检查请求过多。
        k0 = kws[0] if kws else ""
        hit = _query_bank_total_for_track(track, keyword=k0) if k0 else 0
        ok = hit > 0
        topic_checks.append({"topic": g.get("topic") or k0, "keyword": k0, "hit_count": hit, "is_met": ok})
        if not ok:
            missing_topics.append(str(g.get("topic") or k0))

    min_total = int(prof.get("min_total_questions") or 0)
    missing_cnt = max(0, min_total - total)
    baseline_all = _app_config_get_json(_EXAM_REQUIREMENT_BASELINE_KEY, {})
    base = baseline_all.get(track) if isinstance(baseline_all, dict) else None
    if not isinstance(base, dict):
        base = {}

    marker_now = _collect_exam_knowledge_markers(track)
    pv_info = _resolve_exam_track_policy_version(track)
    current_policy_ver = str(pv_info.get("effective_policy_version") or "").strip()
    policy_source = str(pv_info.get("policy_version_source") or "none")
    auto_policy_ver = str(pv_info.get("auto_policy_version") or "").strip()
    fallback_policy_ver = str(pv_info.get("fallback_policy_version") or "").strip()
    policy_conf = str(pv_info.get("policy_version_confidence") or "none")
    policy_evidence = pv_info.get("policy_version_evidence")
    base_policy_ver = str(base.get("policy_version") or "").strip()

    def _parse_iso(v: Any) -> Optional[datetime]:
        s = str(v or "").strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            return None

    changed_flags: dict[str, bool] = {}
    for k in ("regulations_at", "procedures_at", "project_case_at"):
        cur = marker_now.get(k)
        old = _parse_iso(base.get(k))
        changed_flags[k] = bool(cur and (old is None or cur > old))
    changed_flags["policy_version"] = bool(current_policy_ver and current_policy_ver != base_policy_ver)

    reasons: list[str] = []
    if missing_cnt > 0:
        reasons.append(f"当前题量 {total}，低于达标题量 {min_total}。")
    if missing_topics:
        reasons.append("主题覆盖不足：" + "、".join(missing_topics) + "。")
    if not base:
        reasons.append("尚未建立“达标基线”，请补全后点击“设为当前达标基线”。")
    if changed_flags.get("policy_version"):
        reasons.append("法规版本标识已变化，需补充新发布/升级要求对应题目。")
    if changed_flags.get("regulations_at"):
        reasons.append("检测到法规资料有新增/修改，需补充题库。")
    if changed_flags.get("procedures_at"):
        reasons.append("检测到程序文件有新增/修改，建议补全题库。")
    if changed_flags.get("project_case_at"):
        reasons.append("检测到项目案例知识有新增/修改，建议补全题库。")
    is_satisfied = len(reasons) == 0
    return {
        "track": track,
        "track_label": prof.get("title") or track,
        "scopes": prof.get("scopes") or [],
        "required_min_total": min_total,
        "bank_total": total,
        "missing_total_count": missing_cnt,
        "topic_checks": topic_checks,
        "is_satisfied": is_satisfied,
        "reasons": reasons,
        "next_batch_target_count": _EXAM_BATCH_INGEST_SIZE,
        "can_continue_ingest": True,
        "knowledge_markers": {
            "current": {k: (v.isoformat() if v else None) for k, v in marker_now.items()},
            "baseline": {
                "regulations_at": base.get("regulations_at"),
                "procedures_at": base.get("procedures_at"),
                "project_case_at": base.get("project_case_at"),
                "policy_version": base.get("policy_version"),
                "checked_at": base.get("checked_at"),
            },
            "changed_flags": changed_flags,
            "current_policy_version": current_policy_ver,
            "policy_version_source": policy_source,
            "policy_version_confidence": policy_conf,
            "policy_version_evidence": policy_evidence,
            "auto_policy_version": auto_policy_ver,
            "fallback_policy_version": fallback_policy_ver,
        },
        "recommendations": {
            "teacher_generate_count": 20 if track == "cn" else (25 if track == "iso13485" else 30),
            "teacher_generate_difficulty": "easy" if track == "cn" else ("medium" if track == "iso13485" else "hard"),
            "student_practice_count": 20 if track == "cn" else (25 if track == "iso13485" else 30),
            "student_practice_difficulty": "easy" if track == "cn" else ("medium" if track == "iso13485" else "hard"),
            "ingest_batch_size": _EXAM_BATCH_INGEST_SIZE,
        },
    }


def _normalize_answers_list_shape(out: dict[str, Any]) -> dict[str, Any]:
    """answers 统一为 list[{question_id, answer, user_answer}]；上游 aicheckword落库字段为 user_answer。"""
    answers = out.get("answers")
    if isinstance(answers, dict):
        out["answers"] = [
            {"question_id": str(k), "answer": v, "user_answer": v}
            for k, v in answers.items()
            if str(k).strip() != ""
        ]
    elif isinstance(answers, list):
        normed: list[dict[str, Any]] = []
        for it in answers:
            if not isinstance(it, dict):
                continue
            row = dict(it)
            ua = row.get("user_answer")
            if ua is None:
                ua = row.get("answer")
            if ua is None:
                ua = row.get("value") or row.get("selected") or row.get("response")
            if ua is not None:
                row["user_answer"] = ua
            normed.append(row)
        out["answers"] = normed
    return out


def _coerce_attempt_id_int_str(v: Any) -> str:
    """将任意 attempt 标识归一成可被 int 解析的字符串。"""
    raw = str(v or "").strip()
    if not raw:
        return ""
    m = re.search(r"\d+", raw)
    if m:
        return m.group(0)
    # 纯字符串/UUID 等无数字时，退化为稳定正整数（避免上游 int_parsing）
    h = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    try:
        n = int(h, 16)
    except Exception:
        n = 1
    if n <= 0:
        n = 1
    return str(n)


def _normalize_practice_submit_upstream_body(body: dict[str, Any]) -> dict[str, Any]:
    """练习提交：会话 id / set_id 常见别名一并带上，避免上游只认其中一种字段名。"""
    raw = body if isinstance(body, dict) else {}
    out = dict(raw)
    # 上游有些版本要求 attemptId 为整数；空串会触发 422，故空值直接移除
    if str(out.get("attempt_id") or "").strip() == "":
        out.pop("attempt_id", None)
    if str(out.get("attemptId") or "").strip() == "":
        out.pop("attemptId", None)
    sid = str(
        out.get("practice_session_id")
        or out.get("session_id")
        or out.get("practiceSessionId")
        or out.get("sessionId")
        or ""
    ).strip()
    if sid:
        out["practice_session_id"] = sid
        out["session_id"] = sid
        out["practiceSessionId"] = sid
        out["sessionId"] = sid
    aid_raw = str(
        out.get("attempt_id")
        or out.get("attemptId")
        or out.get("practice_attempt_id")
        or out.get("practiceAttemptId")
        or out.get("practice_id")
        or out.get("practiceId")
        or out.get("id")
        or sid
        or ""
    ).strip()
    aid = _coerce_attempt_id_int_str(aid_raw)
    if aid:
        out["attempt_id"] = aid
        out["attemptId"] = aid
    # 空串 set_id 会导致上游 int_parsing，先移除再尝试从嵌套对象补齐
    if str(out.get("set_id") or "").strip() == "":
        out.pop("set_id", None)
    if str(out.get("setId") or "").strip() == "":
        out.pop("setId", None)
    set_id = str(out.get("set_id") or out.get("setId") or _extract_set_id_from_any(out) or "").strip()
    if set_id:
        out["set_id"] = set_id
        out["setId"] = set_id
    return _normalize_answers_list_shape(out)


def _normalize_exam_submit_upstream_body(body: dict[str, Any], attempt_id: str) -> dict[str, Any]:
    raw = body if isinstance(body, dict) else {}
    out = dict(raw)
    aid = _coerce_attempt_id_int_str(attempt_id)
    if aid:
        out["attempt_id"] = aid
        out["attemptId"] = aid
    return _normalize_answers_list_shape(out)


def _extract_bank_items_from_list_root(root: Any) -> list[dict[str, Any]]:
    """从题库列表上游 JSON 根对象中取出题目 dict 列表。"""
    if not isinstance(root, dict):
        return []
    inner = root.get("data") if isinstance(root.get("data"), dict) else None
    cands: list[Any] = [
        root.get("items"),
        root.get("questions"),
        inner.get("items") if inner else None,
        inner.get("questions") if inner else None,
    ]
    for c in cands:
        if isinstance(c, list) and c:
            return [x for x in c if isinstance(x, dict)]
    for c in cands:
        if isinstance(c, list):
            return [x for x in c if isinstance(x, dict)]
    return []


def _question_id_from_bank_item(it: dict[str, Any]) -> str:
    return str(it.get("question_id") or it.get("questionId") or it.get("id") or "").strip()


def _find_set_item_dicts(root: Any, depth: int = 0) -> list[dict[str, Any]]:
    """从 GET quiz/sets/{id} 上游根对象中取出套内题目/条目 dict 列表。"""
    if depth > 10:
        return []
    cand_keys = ("items", "questions", "question_items", "questionItems", "entries")
    if isinstance(root, list):
        return [x for x in root if isinstance(x, dict)]
    if not isinstance(root, dict):
        return []
    for hop in ("load_set", "set", "quiz_set", "quizSet", "payload", "result"):
        inner = root.get(hop)
        if isinstance(inner, dict):
            got = _find_set_item_dicts(inner, depth + 1)
            if got:
                return got
    for k in cand_keys:
        v = root.get(k)
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return [x for x in v if isinstance(x, dict)]
    for k in cand_keys:
        v = root.get(k)
        if isinstance(v, list):
            out = [x for x in v if isinstance(x, dict)]
            if out:
                return out
    inner = root.get("data")
    if isinstance(inner, dict):
        return _find_set_item_dicts(inner, depth + 1)
    return []


def _question_id_from_set_item(it: dict[str, Any]) -> str:
    for key in (
        "question_id",
        "questionId",
        "id",
        "bank_question_id",
        "bankQuestionId",
        "question_bank_id",
        "questionBankId",
        "ref_question_id",
        "refQuestionId",
    ):
        v = it.get(key)
        if v is not None and str(v).strip():
            return str(v).strip()
    q = it.get("question")
    if isinstance(q, dict):
        for key in ("id", "question_id", "questionId", "bank_question_id", "bankQuestionId"):
            v = q.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
    return ""


def _ordered_question_ids_from_set_upstream_root(root: Any) -> list[str]:
    out: list[str] = []
    for it in _find_set_item_dicts(root):
        qid = _question_id_from_set_item(it)
        if qid:
            out.append(qid)
    return out


def _bank_row_matches_set_id(it: dict[str, Any], set_sid: str) -> bool:
    want = str(set_sid).strip()
    if not want:
        return False
    blobs: list[dict[str, Any]] = [it]
    q = it.get("question")
    if isinstance(q, dict):
        blobs.append(q)
    for mk in ("meta", "metadata"):
        m = it.get(mk)
        if isinstance(m, dict):
            blobs.append(m)
    id_keys = (
        "set_id",
        "setId",
        "quiz_set_id",
        "quizSetId",
        "parent_set_id",
        "parentSetId",
        "exam_set_id",
        "examSetId",
    )
    list_keys = ("set_ids", "setIds", "quiz_set_ids", "quizSetIds")
    for cur in blobs:
        if not isinstance(cur, dict):
            continue
        for k in id_keys:
            v = cur.get(k)
            if v is None or v == "":
                continue
            if str(v).strip() == want:
                return True
        for lk in list_keys:
            v = cur.get(lk)
            if isinstance(v, list) and want in {str(x).strip() for x in v}:
                return True
    return False


# ---------- 辅助函数 ----------

def _save_file(file_storage, target_dir: Path) -> tuple[str, str]:
    filename = secure_filename(file_storage.filename)
    generated_name = f"{now_local().strftime('%Y%m%d%H%M%S%f')}_{filename}"
    file_path = target_dir / generated_name
    file_storage.save(file_path)
    return generated_name, str(file_path)


def _project_priority_label(priority: int | None) -> str:
    p = int(priority or Project.PRIORITY_MEDIUM)
    if p >= Project.PRIORITY_HIGH:
        return "高"
    if p <= Project.PRIORITY_LOW:
        return "低"
    return "中"


def _project_status_label(status: str | None) -> str:
    s = (status or "").strip().lower()
    return "已结束" if s == Project.STATUS_ENDED else "进行中"


def _sort_upload_records_by_project_priority(
    records: list[UploadRecord], proj_meta: dict[str, dict[str, Any]]
) -> list[UploadRecord]:
    """按项目优先级降序（数值越大越靠前），同优先级按 sort_order 升序、创建时间升序。"""

    def _created_ts(r: UploadRecord) -> float:
        ct = getattr(r, "created_at", None)
        if not ct:
            return 0.0
        try:
            return float(ct.timestamp())
        except (OSError, OverflowError, ValueError):
            return 0.0

    def _key(r: UploadRecord) -> tuple:
        pr = int((proj_meta.get(r.project_name) or {}).get("priority") or Project.PRIORITY_MEDIUM)
        so = int(r.sort_order or 0)
        return (-pr, so, _created_ts(r))

    return sorted(records, key=_key)


def _project_display_label_from_fields(
    name: str | None,
    registered_country: str | None,
    registered_category: str | None,
) -> str:
    n = (name or "").strip()
    c = (registered_country or "").strip()
    cat = (registered_category or "").strip()
    if not c and not cat:
        return n
    return f"{n}（{c or '—'} / {cat or '—'}）"


def _project_display_label(p: Project) -> str:
    return _project_display_label_from_fields(
        p.name,
        getattr(p, "registered_country", None),
        getattr(p, "registered_category", None),
    )


def _filter_nullable_eq(q, col, value):
    """value=None 用 IS NULL；否则用 =。避免 MySQL 生成 `IS 'xxx'` 导致 500。"""
    return q.filter(col.is_(None)) if value is None else q.filter(col == value)


def _backfill_project_ids() -> None:
    """将历史 upload_records/module_cascade_reminders/generation_summary 的 project_id 回填（按展示键匹配）。"""
    from .models import UploadRecord, ModuleCascadeReminder, GenerationSummary
    rows = Project.query.order_by(Project.updated_at.asc(), Project.id.asc()).all()
    # 同一展示键可能有重复项目：选择最早的作为“主项目ID”
    key_to_pid: dict[str, str] = {}
    for p in rows:
        k = _project_display_label(p)
        if k and k not in key_to_pid:
            key_to_pid[k] = p.id

    for k, pid in key_to_pid.items():
        UploadRecord.query.filter(UploadRecord.project_id.is_(None), UploadRecord.project_name == k).update(
            {"project_id": pid}
        )
        ModuleCascadeReminder.query.filter(ModuleCascadeReminder.project_id.is_(None), ModuleCascadeReminder.project_name == k).update(
            {"project_id": pid}
        )
        try:
            GenerationSummary.query.filter(GenerationSummary.project_id.is_(None), GenerationSummary.project_name == k).update(
                {"project_id": pid}
            )
        except Exception:
            pass
    db.session.commit()


def _ensure_project_row(project_name: str) -> Project | None:
    # 兼容旧数据：project_name 可能是 base name，也可能是展示键(label)
    label = (project_name or "").strip()
    if not label:
        return None

    # 先按展示键匹配（支持未来：projectId 为空时，仍可“查到已有项目”）
    for p in Project.query.all():
        if _project_display_label(p) == label:
            return p

    row = Project(
        name=label,
        priority=Project.PRIORITY_MEDIUM,
        status=Project.STATUS_ACTIVE,
        registered_country=None,
        registered_category=None,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        # commit 失败时返回任意可用行（避免 None 造成后续空指针）
        for p in Project.query.all():
            if _project_display_label(p) == label:
                return p
        return None
    return row


def _project_meta_map(auto_create_from_uploads: bool = False) -> dict[str, dict[str, Any]]:
    """
    返回项目元信息映射：name -> {priority, status}。
    若 auto_create_from_uploads=True，会把 upload_records 中出现但 projects 表不存在的项目补齐（默认中/进行中）。
    """
    if auto_create_from_uploads:
        labels = (
            db.session.query(UploadRecord.project_name)
            .filter(UploadRecord.project_name.isnot(None), UploadRecord.project_name != "")
            .distinct()
            .all()
        )
        for (lab,) in labels:
            _ensure_project_row(lab)

    rows = Project.query.order_by(Project.priority.desc(), Project.name.asc()).all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        if not (r.name or "").strip():
            continue
        key = _project_display_label(r)
        out[key] = {
            "priority": int(r.priority or Project.PRIORITY_MEDIUM),
            "status": r.status or Project.STATUS_ACTIVE,
            "baseName": r.name,
            "registeredCountry": getattr(r, "registered_country", None),
            "registeredCategory": getattr(r, "registered_category", None),
        }
    return out


def _ended_project_names() -> set[str]:
    rows = Project.query.filter(Project.status == Project.STATUS_ENDED).all()
    return {_project_display_label(r) for r in rows if (r.name or "").strip()}


def _normalize_doc_link(line: str) -> str:
    """截断 https 之前的内容，返回从 http(s) 开始的有效可打开地址。"""
    line = (line or "").strip()
    if not line:
        return line
    lower = line.lower()
    for prefix in ("https://", "http://"):
        idx = lower.find(prefix)
        if idx != -1:
            return line[idx:]
    return line


def _normalize_template_links(value: str) -> str:
    """多行文档地址，每行截断 https 之前的信息后合并。"""
    if not value or not value.strip():
        return value.strip() or ""
    lines = [_normalize_doc_link(ln) for ln in value.split("\n") if ln.strip()]
    return "\n".join(ln for ln in lines if ln)


def _is_valid_doc_link(value: str) -> bool:
    """校验文档链接是否合理：每行经归一化后需以 http:// 或 https:// 开头。"""
    if not value or not value.strip():
        return True
    for line in value.strip().split("\n"):
        ln = (line or "").strip()
        if not ln:
            continue
        normalized = _normalize_doc_link(ln)
        lower = normalized.lower()
        if not (lower.startswith("http://") or lower.startswith("https://")):
            return False
    return True


def _prepare_summary(upload: UploadRecord) -> GenerationSummary:
    if upload.summary:
        return upload.summary
    summary = GenerationSummary(
        upload=upload,
        project_name=upload.project_name,
        file_name=upload.file_name,
        author=upload.author,
    )
    db.session.add(summary)
    return summary


def _get_template_path_for_upload(upload: UploadRecord, link_index: int = 0) -> str:
    """返回上传记录对应的模板本地路径：库内模板先落盘，否则 storage_path，链接则下载到 uploads/。"""
    if upload.template_file_blob:
        uploads_dir = Path(current_app.config["UPLOAD_FOLDER"])
        mat = uploads_dir / f"_dbtpl_{upload.id}.docx"
        if not mat.exists() or mat.stat().st_size != len(upload.template_file_blob):
            mat.write_bytes(upload.template_file_blob)
        return str(mat)
    if upload.storage_path and Path(upload.storage_path).exists():
        return upload.storage_path
    links = upload.get_template_links_list()
    if links and link_index < len(links):
        uploads_dir = Path(current_app.config["UPLOAD_FOLDER"])
        save_path = uploads_dir / f"link_{upload.id}_{link_index}.docx"
        if not save_path.exists():
            download_template_from_url(links[link_index], str(save_path))
        return str(save_path)
    raise ValueError("上传记录未关联有效模板（文件或链接）")


def _build_option_tree(records: list[UploadRecord]) -> list[dict[str, Any]]:
    projects: dict[str, dict[str, Any]] = {}
    for record in records:
        proj = projects.setdefault(
            record.project_name,
            {"projectName": record.project_name, "files": {}},
        )
        file_entry = proj["files"].setdefault(
            record.file_name,
            {"fileName": record.file_name, "authors": []},
        )
        file_entry["authors"].append(
            {
                "author": record.author,
                "uploadId": record.id,
                "hasLinks": bool(record.template_links),
                "taskStatus": record.task_status,
                "quickCompleted": record.quick_completed,
            }
        )
    formatted = []
    for project in projects.values():
        files = list(project["files"].values())
        project["files"] = files
        formatted.append(project)
    return formatted


def _summary_payload():
    """
    统计逻辑：
    - completion_status 有值 => 已完成
    - completion_status 为空 => 未完成
    - 项目+人员统计融合各完成状态数量
    """
    proj_meta = _project_meta_map(auto_create_from_uploads=True)
    ended = {n for n, m in proj_meta.items() if (m.get("status") or "").strip().lower() == Project.STATUS_ENDED}
    q = UploadRecord.query
    if ended:
        q = q.filter(~UploadRecord.project_name.in_(list(ended)))
    uploads = _sort_upload_records_by_project_priority(
        q.order_by(UploadRecord.sort_order.asc(), UploadRecord.created_at.asc()).all(),
        proj_meta,
    )
    total_files = len(uploads)
    
    def _rate(done: int, total: int) -> float:
        return round(done / total, 4) if total else 0.0
    
    completed_files = sum(1 for u in uploads if u.completion_status)
    
    by_project: dict[str, dict[str, Any]] = {}
    by_author: dict[str, dict[str, Any]] = {}
    by_project_author: dict[str, dict[str, Any]] = {}

    for u in uploads:
        proj_key = u.project_name
        auth_key = u.author
        proj_auth_key = f"{u.project_name}__{u.author}"
        is_completed = bool(u.completion_status)
        status = u.completion_status or "未完成"

        for bucket, key in (
            (by_project, proj_key),
            (by_author, auth_key),
            (by_project_author, proj_auth_key),
        ):
            stats = bucket.setdefault(key, {
                "total": 0, "completed": 0, "pending": 0,
                "byStatus": {}, "pendingAuthors": set(),
                "auditRejectCount": 0,
            })
            stats["total"] += 1
            if is_completed:
                stats["completed"] += 1
            else:
                stats["pending"] += 1
                stats["pendingAuthors"].add(u.author)
            stats["byStatus"][status] = stats["byStatus"].get(status, 0) + 1
            stats["auditRejectCount"] = stats.get("auditRejectCount", 0) + (getattr(u, "audit_reject_count", None) or 0)

    def _format_with_status(bucket: dict[str, dict[str, Any]], label_join: str = "", include_project_author_keys: bool = False):
        formatted = []
        for key, stats in bucket.items():
            label = key
            if label_join and "__" in key:
                parts = key.split("__")
                label = label_join.join(parts)
            by_status_list = [
                {"status": s, "count": c}
                for s, c in sorted(stats["byStatus"].items(), key=lambda x: (x[0] != "未完成", -x[1]))
            ]
            item = {
                "label": label,
                "completed": stats["completed"],
                "pending": stats["pending"],
                "total": stats["total"],
                "rate": _rate(stats["completed"], stats["total"]),
                "byStatus": by_status_list,
                "pendingAuthors": list(stats["pendingAuthors"]),
                "auditRejectCount": stats.get("auditRejectCount", 0),
            }
            if not include_project_author_keys:
                # byProject / byAuthor
                if bucket is by_project:
                    m = proj_meta.get(key) or {}
                    item["projectPriority"] = int(m.get("priority") or Project.PRIORITY_MEDIUM)
                    item["projectStatus"] = (m.get("status") or Project.STATUS_ACTIVE)
            if include_project_author_keys and "__" in key:
                p, a = key.split("__", 1)
                item["projectName"] = p
                item["author"] = a
                m = proj_meta.get(p) or {}
                item["projectPriority"] = int(m.get("priority") or Project.PRIORITY_MEDIUM)
                item["projectStatus"] = (m.get("status") or Project.STATUS_ACTIVE)
            formatted.append(item)
        return formatted

    detail_rows = [
        {
            "seq": idx + 1,
            "uploadId": u.id,
            "projectName": u.project_name,
            "fileName": u.file_name,
            "taskType": u.task_type,
            "author": u.author,
            "completionStatus": u.completion_status,
            "isCompleted": bool(u.completion_status),
            "dueDate": u.due_date.strftime("%Y-%m-%d") if u.due_date else None,
            "sortOrder": u.sort_order,
            "businessSide": u.business_side,
            "product": u.product,
            "country": u.country,
            "projectCode": getattr(u, "project_code", None),
            "projectPriority": int((proj_meta.get(u.project_name) or {}).get("priority") or Project.PRIORITY_MEDIUM),
            "fileVersion": getattr(u, "file_version", None),
            "documentDisplayDate": (lambda d: d.strftime("%Y-%m-%d") if d else None)(getattr(u, "document_display_date", None)),
            "reviewer": getattr(u, "reviewer", None),
            "approver": getattr(u, "approver", None),
            "belongingModule": getattr(u, "belonging_module", None),
            "displayedAuthor": getattr(u, "displayed_author", None),
            "docLink": (u.get_template_links_list() or [None])[0] or None,
            "createdAt": u.created_at.isoformat() if u.created_at else None,
            "notes": u.notes,
            "projectNotes": getattr(u, "project_notes", None),
            "executionNotes": u.execution_notes,
            "registeredProductName": getattr(u, "registered_product_name", None),
            "model": getattr(u, "model", None),
            "registrationVersion": getattr(u, "registration_version", None),
        }
        for idx, u in enumerate(uploads)
    ]

    return {
        "overall": {
            "completed": completed_files,
            "pending": total_files - completed_files,
            "total": total_files,
            "rate": _rate(completed_files, total_files),
        },
        "byProject": sorted(
            _format_with_status(by_project),
            key=lambda x: (-int(x.get("projectPriority") or Project.PRIORITY_MEDIUM), str(x.get("label") or "")),
        ),
        "byAuthor": _format_with_status(by_author),
        "byProjectAuthor": sorted(
            _format_with_status(by_project_author, label_join=" / ", include_project_author_keys=True),
            key=lambda x: (-int(x.get("projectPriority") or Project.PRIORITY_MEDIUM), str(x.get("label") or "")),
        ),
        "detail": detail_rows,
    }


# ---------- 登录验证装饰器 ----------

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"message": "请先登录", "needsLogin": True}), 401
            return redirect(url_for("pages.login_page"))
        return f(*args, **kwargs)
    return decorated_function


def _page13_or_login_required(f):
    """登录 或 已通过页面1/3 访问密码 任一即可（供页面1 未登录时也能加载配置、页面2 仅登录即可）。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _page13_password_configured():
            return f(*args, **kwargs)
        if session.get("user_id"):
            return f(*args, **kwargs)
        if session.get("page13_authenticated"):
            return f(*args, **kwargs)
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/api/"):
            return jsonify({"message": "需要输入访问密码", "needsPage13Auth": True}), 401
        next_url = request.path or "/upload"
        return render_template("page13_gate.html", next_url=next_url, gate_page=True)
    return decorated_function


def _page13_password_configured() -> bool:
    from .app_settings import get_setting
    p = get_setting("PAGE13_ACCESS_PASSWORD", default=str(current_app.config.get("PAGE13_ACCESS_PASSWORD") or ""))
    return bool(p and str(p).strip())


def page13_access_required(f):
    """页面1、页面3 及其相关 API 的访问密码校验。密码不在网络中传输，使用 nonce+hash 校验。"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not _page13_password_configured():
            return f(*args, **kwargs)
        if session.get("page13_authenticated"):
            return f(*args, **kwargs)
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.path.startswith("/api/"):
            return jsonify({"message": "需要输入访问密码", "needsPage13Auth": True}), 401
        next_url = request.path or "/upload"
        return render_template("page13_gate.html", next_url=next_url, gate_page=True)
    return decorated_function


# ---------- 页面路由 ----------

@bp.route("/favicon.ico")
def favicon():
    """避免浏览器请求 favicon 时 404，返回空响应。"""
    return "", 204


@bp.route("/")
def index():
    # 两套用户体系：
    # - page13（管理员/老师/统计端）：进入页面1/3
    # - user_id（学生端/页面2）：进入页面2
    if session.get("page13_authenticated"):
        return redirect(url_for("pages.upload_page"))
    if session.get("user_id"):
        return redirect(url_for("pages.generate_page"))
    return redirect(url_for("pages.login_page"))


@bp.route("/upload")
@page13_access_required
def upload_page():
    return render_template("upload.html")


@bp.route("/login")
def login_page():
    return render_template("login.html")


@bp.route("/generate")
@login_required
def generate_page():
    return render_template("generate.html")


@bp.route("/dashboard")
@page13_access_required
def dashboard_page():
    return render_template("dashboard.html")


def _exam_center_display_user() -> str:
    if session.get("user_id") is not None:
        name = (session.get("display_name") or session.get("username") or "").strip()
        if name:
            return name
        return str(session.get("user_id"))
    if session.get("page13_authenticated"):
        return "页面3已验证"
    return ""


@bp.route("/exam-center")
def exam_center_page():
    role_arg = request.args.get("role")
    if role_arg is None or str(role_arg).strip() == "":
        # 兼容“从页面1/3进入考试中心”的默认行为：管理员体系默认进入老师端；
        # 学生体系默认进入学生端（并由下方逻辑要求已登录）。
        role = "teacher" if session.get("page13_authenticated") else "student"
    else:
        role = str(role_arg).strip().lower()
    if role not in {"teacher", "student", "analytics"}:
        role = "student"

    # 两套体系可叠加：登录(user_id)→学生端；page13→老师端/统计端
    allowed_roles = []
    if session.get("user_id"):
        allowed_roles.append("student")
    if session.get("page13_authenticated"):
        allowed_roles.extend(["teacher", "analytics"])

    if role in {"teacher", "analytics"}:
        if _page13_password_configured() and not session.get("page13_authenticated"):
            next_url = request.full_path or request.path or "/upload"
            if next_url.endswith("?"):
                next_url = next_url[:-1]
            return render_template("page13_gate.html", next_url=next_url, gate_page=True)
    else:
        if not session.get("user_id"):
            return redirect(url_for("pages.login_page"))

    return render_template(
        "exam_center.html",
        exam_role=role,
        exam_allowed_roles=allowed_roles,
        exam_display_user=_exam_center_display_user(),
        hide_main_nav=(role == "student"),
    )


# ---------- 认证 API ----------

@bp.post("/api/login")
def api_login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"message": "用户名和密码不能为空"}), 400
    user = User.query.filter_by(username=username).first()
    if not user or not user.check_password(password):
        return jsonify({"message": "用户名或密码错误"}), 401
    session["user_id"] = user.id
    session["username"] = user.username
    session["display_name"] = user.display_name or user.username
    return jsonify({
        "message": "登录成功",
        "user": {
            "id": user.id,
            "username": user.username,
            "displayName": user.display_name,
        },
    })


@bp.post("/api/logout")
def api_logout():
    session.clear()
    return jsonify({"message": "已退出登录"})


@bp.get("/api/me")
def api_me():
    if not session.get("user_id"):
        return jsonify({"loggedIn": False})
    return jsonify({
        "loggedIn": True,
        "user": {
            "id": session.get("user_id"),
            "username": session.get("username"),
            "displayName": session.get("display_name"),
        },
    })


@bp.get("/api/page13-auth-state")
def api_page13_auth_state():
    """获取页面1/3 是否需密码及本次验证用的 nonce（不校验身份，任何人可调）。"""
    required = _page13_password_configured()
    authenticated = bool(session.get("page13_authenticated"))
    if not required:
        return jsonify({"required": False, "authenticated": True})
    if authenticated:
        return jsonify({"required": True, "authenticated": True})
    nonce = secrets.token_hex(16)
    session["page13_nonce"] = nonce
    return jsonify({"required": True, "authenticated": False, "nonce": nonce})


@bp.post("/api/page13-auth")
def api_page13_auth():
    """提交 hash(nonce+password)，校验通过后设置 session，密码不明文传输。"""
    if not _page13_password_configured():
        return jsonify({"success": True, "message": "未配置访问密码"})
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    client_hash = (data.get("hash") or "").strip()
    if not client_hash:
        return jsonify({"message": "缺少校验参数"}), 400
    nonce = session.get("page13_nonce")
    if not nonce:
        return jsonify({"message": "请先获取验证码（刷新页面后重试）"}), 400
    from .app_settings import get_setting
    raw = get_setting("PAGE13_ACCESS_PASSWORD", default=str(current_app.config.get("PAGE13_ACCESS_PASSWORD") or ""))
    password = (str(raw).replace("\ufeff", "").strip() if raw else "")
    expected = hashlib.sha256((nonce + password).encode("utf-8")).hexdigest()
    session.pop("page13_nonce", None)
    if not secrets.compare_digest(expected, client_hash):
        return jsonify({"message": "访问密码错误"}), 401
    session["page13_authenticated"] = True
    return jsonify({"success": True, "message": "验证成功"})


# ---------- 考试训练中心 API（aiword 代理） ----------

def _json_payload() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def _guess_job_id_from_payload(p: dict[str, Any]) -> str:
    """从代理层整包中提取上游 ingest 的 job_id。上游常见形态：p['data'] = {ok, data: {job_id, set_id}}。"""
    if not isinstance(p, dict):
        return ""
    data = p.get("data")
    if isinstance(data, dict):
        for k in ("job_id", "jobId", "id", "jobID"):
            v = data.get(k)
            if v:
                return str(v).strip()
        inner = data.get("data")
        if isinstance(inner, dict):
            for k in ("job_id", "jobId", "id", "jobID"):
                v = inner.get(k)
                if v:
                    return str(v).strip()
    for k in ("job_id", "jobId", "id", "jobID"):
        v = p.get(k)
        if v:
            return str(v).strip()
    return ""


def _normalize_job_status_from_upstream_data(upstream_data: Any) -> str:
    if not isinstance(upstream_data, dict):
        return "unknown"
    raw = (
        upstream_data.get("status")
        or upstream_data.get("state")
        or upstream_data.get("job_status")
        or upstream_data.get("jobStatus")
        or ""
    )
    if not raw:
        inner = upstream_data.get("data")
        if isinstance(inner, dict):
            raw = (
                inner.get("status")
                or inner.get("state")
                or inner.get("job_status")
                or inner.get("jobStatus")
                or ""
            )
        job = upstream_data.get("job")
        if not raw and isinstance(job, dict):
            raw = job.get("status") or job.get("state") or ""
    s = str(raw).strip().lower()
    if s in {"done", "success", "completed"}:
        return "done"
    if s in {"failed", "error"}:
        return "failed"
    if s in {"running", "processing", "in_progress", "progress"}:
        return "running"
    if s in {"pending", "queued", "created"}:
        return "pending"
    return s or "unknown"


def _extract_set_id_from_dict(obj: Any) -> str:
    """从任意 dict 中尽力提取上游 set_id（兼容 setId / quiz_sets.id 等常见形态）。"""
    if not isinstance(obj, dict):
        return ""
    for k in ("set_id", "setId", "quiz_set_id", "quizSetId"):
        v = obj.get(k)
        if v:
            s = str(v).strip()
            if s:
                return s
    inner = obj.get("set")
    if isinstance(inner, dict):
        for k in ("id", "set_id", "setId"):
            v = inner.get(k)
            if v:
                s = str(v).strip()
                if s:
                    return s
    return ""


def _extract_set_id_from_any(obj: Any) -> str:
    """递归浅层扫描：优先顶层字段，其次常见嵌套 data/job/result。"""
    sid = _extract_set_id_from_dict(obj) if isinstance(obj, dict) else ""
    if sid:
        return sid
    if not isinstance(obj, dict):
        return ""
    for child_key in ("data", "job", "result", "payload"):
        child = obj.get(child_key)
        if isinstance(child, dict):
            sid = _extract_set_id_from_dict(child)
            if sid:
                return sid
        if isinstance(child, list) and child and isinstance(child[0], dict):
            sid = _extract_set_id_from_dict(child[0])
            if sid:
                return sid
    return ""


def _extract_set_id_from_quiz_proxy_payload(payload: Any) -> str:
    """
    aiword 代理返回结构通常是 {code,message,data,request,trace_id}，
    其中 data 可能是 dict 或 list；set_id 可能在 data 内或更深。
    """
    if not isinstance(payload, dict):
        return ""
    sid = _extract_set_id_from_any(payload.get("data"))
    if sid:
        return sid
    return _extract_set_id_from_any(payload)


@bp.post("/api/exam-center/teacher/sets/generate")
@page13_access_required
def api_exam_teacher_generate_set():
    body = _expand_exam_track_and_difficulty_aliases(_expand_question_count_aliases(_json_payload()))
    status, payload = _quiz_api_call("quiz/sets/generate", method="POST", payload=body)
    return jsonify(payload), status


@bp.post("/api/exam-center/teacher/bank/ingest-by-ai")
@page13_access_required
def api_exam_teacher_ingest_bank():
    req_payload = _expand_exam_track_and_difficulty_aliases(_expand_question_count_aliases(_json_payload()))
    req_payload["target_count"] = _EXAM_BATCH_INGEST_SIZE
    req_payload["targetCount"] = _EXAM_BATCH_INGEST_SIZE
    req_payload["question_count"] = _EXAM_BATCH_INGEST_SIZE
    req_payload["questionCount"] = _EXAM_BATCH_INGEST_SIZE
    status, payload = _quiz_api_call("quiz/bank/ingest-by-ai", method="POST", payload=req_payload)

    # 成功拿到 job_id 后：落库生成任务记录（用于后续从记录查询轮询状态与结果）
    if 200 <= int(status) < 300 and isinstance(payload, dict):
        upstream_job_id = _guess_job_id_from_payload(payload)
        if upstream_job_id:
            created_by = (session.get("display_name") or session.get("username") or "").strip() or None
            exam_track = (req_payload.get("exam_track") or req_payload.get("examTrack") or "").strip() or None
            try:
                target_count = int(req_payload.get("target_count") or req_payload.get("targetCount") or 0) or None
            except Exception:
                target_count = None
            review_mode = (req_payload.get("review_mode") or req_payload.get("reviewMode") or "").strip() or None
            row = ExamBankIngestJob.query.filter_by(upstream_job_id=upstream_job_id).first()
            if not row:
                row = ExamBankIngestJob(
                    upstream_job_id=upstream_job_id,
                    exam_track=exam_track,
                    target_count=target_count,
                    review_mode=review_mode,
                    status="pending",
                    created_by=created_by,
                )
            row.last_upstream_http_status = int(status)
            row.last_upstream_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload.get("data")
            row.last_upstream_request_url = ((payload.get("request") or {}).get("url") if isinstance(payload.get("request"), dict) else None) or None
            row.last_upstream_trace_id = (payload.get("trace_id") or None)
            row.last_message = (payload.get("message") or None)
            set_id = _extract_set_id_from_quiz_proxy_payload(payload)
            if set_id:
                row.upstream_set_id = set_id
            db.session.add(row)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                if isinstance(payload, dict):
                    payload["job_record_error"] = f"aiword 落库失败（不影响上游任务）：{e}"
            else:
                if isinstance(payload, dict):
                    payload["job_record"] = {
                        "id": row.id,
                        "upstream_job_id": row.upstream_job_id,
                        "upstream_set_id": row.upstream_set_id,
                        "status": row.status,
                    }

    return jsonify(payload), status


@bp.get("/api/exam-center/teacher/bank/requirements-check")
@page13_access_required
def api_exam_teacher_bank_requirements_check():
    track = _normalize_exam_track(
        request.args.get("exam_track")
        or request.args.get("examTrack")
        or request.args.get("track")
        or "cn"
    )
    data = _build_exam_bank_requirement_status(track)
    msg = "当前题库已满足体考要求。仍可继续录题以增强覆盖。" if data.get("is_satisfied") else "当前题库尚未满足体考要求。"
    return jsonify({"code": 0, "message": msg, "data": data, "trace_id": uuid.uuid4().hex}), 200


@bp.get("/api/exam-center/teacher/bank/policy-version")
@page13_access_required
def api_exam_teacher_bank_policy_version_get():
    track = _normalize_exam_track(
        request.args.get("exam_track")
        or request.args.get("examTrack")
        or request.args.get("track")
        or "cn"
    )
    pv_info = _resolve_exam_track_policy_version(track)
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "track": track,
                "policy_version": pv_info.get("fallback_policy_version"),
                "auto_policy_version": pv_info.get("auto_policy_version"),
                "effective_policy_version": pv_info.get("effective_policy_version"),
                "policy_version_source": pv_info.get("policy_version_source"),
                "policy_version_confidence": pv_info.get("policy_version_confidence"),
                "policy_version_evidence": pv_info.get("policy_version_evidence"),
            },
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.put("/api/exam-center/teacher/bank/policy-version")
@page13_access_required
def api_exam_teacher_bank_policy_version_put():
    body = _json_payload()
    track = _normalize_exam_track(
        body.get("exam_track")
        or body.get("examTrack")
        or body.get("track")
        or request.args.get("exam_track")
        or "cn"
    )
    version_value = str(body.get("policy_version") or body.get("policyVersion") or "").strip()
    _set_exam_track_policy_version(track, version_value)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": "DB_ERROR", "message": f"保存法规版本失败：{e}", "data": None, "trace_id": uuid.uuid4().hex}), 500
    return jsonify(
        {
            "code": 0,
            "message": "法规版本标识（兜底）已保存。",
            "data": {"track": track, "policy_version": version_value},
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.post("/api/exam-center/teacher/bank/requirements-baseline")
@page13_access_required
def api_exam_teacher_bank_requirements_baseline():
    body = _json_payload()
    track = _normalize_exam_track(
        body.get("exam_track")
        or body.get("examTrack")
        or body.get("track")
        or request.args.get("exam_track")
        or "cn"
    )
    snap = _build_exam_bank_requirement_status(track)
    km = snap.get("knowledge_markers") if isinstance(snap, dict) else {}
    current = km.get("current") if isinstance(km, dict) else {}
    policy_v = km.get("current_policy_version") if isinstance(km, dict) else ""
    all_base = _app_config_get_json(_EXAM_REQUIREMENT_BASELINE_KEY, {})
    if not isinstance(all_base, dict):
        all_base = {}
    all_base[track] = {
        "regulations_at": (current.get("regulations_at") if isinstance(current, dict) else None),
        "procedures_at": (current.get("procedures_at") if isinstance(current, dict) else None),
        "project_case_at": (current.get("project_case_at") if isinstance(current, dict) else None),
        "policy_version": str(policy_v or "").strip(),
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "checked_by": (session.get("display_name") or session.get("username") or "").strip() or None,
    }
    _app_config_set_json(_EXAM_REQUIREMENT_BASELINE_KEY, all_base)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": "DB_ERROR", "message": f"写入基线失败：{e}", "data": None, "trace_id": uuid.uuid4().hex}), 500
    latest = _build_exam_bank_requirement_status(track)
    return jsonify({"code": 0, "message": "已设置当前达标基线。", "data": latest, "trace_id": uuid.uuid4().hex}), 200


@bp.get("/api/exam-center/teacher/bank/ingest-jobs/<job_id>")
@page13_access_required
def api_exam_teacher_ingest_job(job_id: str):
    job_id = (job_id or "").strip()
    if not job_id:
        return (
            jsonify(
                {
                    "code": "BAD_REQUEST",
                    "message": "缺少 job_id",
                    "data": None,
                    "trace_id": uuid.uuid4().hex,
                    "request": {"url": "", "method": "GET", "upstreamPath": ""},
                }
            ),
            400,
        )
    # 1) 先查本地任务记录（如果不存在，也允许继续向上游查询）
    row = ExamBankIngestJob.query.filter_by(upstream_job_id=job_id).first()

    # 2) 默认刷新上游状态（refresh=0 可只看本地快照）
    refresh = (request.args.get("refresh") or "1").strip()
    if refresh not in {"0", "false", "no"}:
        status, payload = _quiz_api_call(
            f"quiz/bank/ingest-jobs/{job_id}",
            method="GET",
            query={k: v for k, v in request.args.to_dict().items() if k != "refresh"},
        )
        # 回写本地快照
        if row is None:
            row = ExamBankIngestJob(upstream_job_id=job_id, status="unknown")
        row.last_upstream_http_status = int(status)
        if isinstance(payload, dict):
            row.last_message = (payload.get("message") or None)
            row.last_upstream_trace_id = (payload.get("trace_id") or None)
            req_meta = payload.get("request") if isinstance(payload.get("request"), dict) else {}
            row.last_upstream_request_url = (req_meta.get("url") or None)
            row.last_upstream_data = payload.get("data")
            row.status = _normalize_job_status_from_upstream_data(payload.get("data"))
            set_id = _extract_set_id_from_quiz_proxy_payload(payload)
            if set_id:
                row.upstream_set_id = set_id
        db.session.add(row)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            if isinstance(payload, dict):
                payload["job_record_error"] = f"aiword 落库失败（不影响上游查询）：{e}"
        else:
            if isinstance(payload, dict):
                payload["job_record"] = {
                    "id": row.id,
                    "upstream_job_id": row.upstream_job_id,
                    "upstream_set_id": row.upstream_set_id,
                    "status": row.status,
                }
        return jsonify(payload), status

    # 仅返回本地记录快照
    if row is None:
        return jsonify({"code": "NOT_FOUND", "message": "本地无该任务记录", "data": None, "trace_id": uuid.uuid4().hex}), 404
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "job_record": {
                    "id": row.id,
                    "upstream_job_id": row.upstream_job_id,
                    "upstream_set_id": getattr(row, "upstream_set_id", None),
                    "status": row.status,
                    "exam_track": row.exam_track,
                    "target_count": row.target_count,
                    "review_mode": row.review_mode,
                    "created_by": row.created_by,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "last_message": row.last_message,
                    "last_upstream_http_status": row.last_upstream_http_status,
                    "last_upstream_request_url": row.last_upstream_request_url,
                    "last_upstream_trace_id": row.last_upstream_trace_id,
                    "last_upstream_data": row.last_upstream_data,
                }
            },
            "trace_id": uuid.uuid4().hex,
        }
    )


@bp.get("/api/exam-center/teacher/bank/ingest-jobs")
@page13_access_required
def api_exam_teacher_ingest_jobs_list():
    limit_raw = (request.args.get("limit") or "20").strip()
    try:
        limit = int(limit_raw)
    except ValueError:
        limit = 20
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    rows = (
        ExamBankIngestJob.query.order_by(ExamBankIngestJob.created_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "jobs": [
                    {
                        "id": r.id,
                        "upstream_job_id": r.upstream_job_id,
                        "upstream_set_id": getattr(r, "upstream_set_id", None),
                        "status": r.status,
                        "exam_track": r.exam_track,
                        "target_count": r.target_count,
                        "review_mode": r.review_mode,
                        "created_by": r.created_by,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                        "last_message": r.last_message,
                        "last_upstream_http_status": r.last_upstream_http_status,
                        "last_upstream_request_url": r.last_upstream_request_url,
                        "last_upstream_trace_id": r.last_upstream_trace_id,
                    }
                    for r in rows
                ]
            },
            "trace_id": uuid.uuid4().hex,
        }
    )


@bp.get("/api/exam-center/teacher/sets")
@page13_access_required
def api_exam_teacher_sets_list():
    """老师端：套题列表（上游）+ 本地 ingest 关联。"""
    status, payload = _quiz_api_call("quiz/sets", method="GET", query=request.args.to_dict())
    rows = (
        ExamBankIngestJob.query.order_by(ExamBankIngestJob.created_at.desc())
        .limit(200)
        .all()
    )
    by_set: dict[str, Any] = {}
    without_set: list[dict[str, Any]] = []
    for r in rows:
        sid = (getattr(r, "upstream_set_id", None) or "").strip()
        jr = {
            "id": r.id,
            "upstream_job_id": r.upstream_job_id,
            "upstream_set_id": getattr(r, "upstream_set_id", None),
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        if sid:
            if sid not in by_set:
                by_set[sid] = jr
        else:
            without_set.append(jr)
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            data.setdefault("aiword", {})
            if isinstance(data.get("aiword"), dict):
                data["aiword"]["ingest_jobs_by_set_id"] = by_set
                data["aiword"]["ingest_jobs_without_set_id"] = without_set[:50]
    return jsonify(payload), status


@bp.get("/api/exam-center/teacher/sets/<set_id>")
@page13_access_required
def api_exam_teacher_set_detail(set_id: str):
    """老师端：套题详情（上游透传）。"""
    sid = (set_id or "").strip()
    if not sid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 set_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    status, payload = _quiz_api_call(f"quiz/sets/{sid}", method="GET", query=request.args.to_dict())
    return jsonify(payload), status


@bp.delete("/api/exam-center/teacher/sets/<set_id>")
@page13_access_required
def api_exam_teacher_delete_set(set_id: str):
    """老师端：删除套题（上游透传）。"""
    sid = (set_id or "").strip()
    if not sid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 set_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    status, payload = _quiz_api_call(f"quiz/sets/{sid}", method="DELETE", payload=_json_payload())
    return jsonify(payload), status


@bp.get("/api/exam-center/teacher/bank/questions")
@page13_access_required
def api_exam_teacher_bank_questions_list():
    """
    老师端：题库题目列表。
    无 set_id：GET quiz/bank/questions 透传（多路径尝试）。
    有 set_id：先 GET quiz/sets/{id} 取题序并与题库分页扫描求交（上游常忽略 set_id 查询参数）。
    """
    args = dict(request.args.items())
    set_sid = str(
        args.get("set_id")
        or args.get("setId")
        or args.get("bank_set_id")
        or args.get("bankSetId")
        or ""
    ).strip()
    paths = [
        "quiz/bank/questions",
        "quiz/questions",
        "quiz/bank/question-list",
    ]
    if not set_sid:
        status, payload, tried = _quiz_try_paths(paths, method="GET", query=args)
        if isinstance(payload, dict) and not (200 <= int(status) < 300):
            payload.setdefault("aiword_upstream_tried_paths", tried)
            payload.setdefault(
                "message",
                (payload.get("message") or "上游题库列表接口不可用")
                + "（已尝试路径：" + ", ".join(tried) + "）",
            )
        return jsonify(payload), status

    _strip_bank = frozenset({"set_id", "setId", "bank_set_id", "bankSetId"})
    bank_args = {k: v for k, v in args.items() if k not in _strip_bank}
    trace_id = uuid.uuid4().hex

    def _int_arg(name: str, default: int, lo: int, hi: int) -> int:
        try:
            v = int(str(bank_args.get(name) or default))
        except (TypeError, ValueError):
            v = default
        return max(lo, min(hi, v))

    user_off = _int_arg("offset", 0, 0, 500000)
    user_lim = _int_arg("limit", 50, 1, 200)
    scan_lim = 200
    max_scan = 12000

    def _pull_bank_page(off: int) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
        q = dict(bank_args)
        q["limit"] = str(scan_lim)
        q["offset"] = str(off)
        st_b, pl_b, _tried = _quiz_try_paths(paths, method="GET", query=q)
        if not (200 <= int(st_b) < 300):
            return [], int(st_b), pl_b if isinstance(pl_b, dict) else {"data": pl_b}
        root_b = _unwrap_quiz_api_success_data(pl_b)
        if not isinstance(root_b, dict):
            root_b = {}
        items_page = _extract_bank_items_from_list_root(root_b)
        return items_page, 200, pl_b

    st_set, pl_set = _quiz_api_call(f"quiz/sets/{set_sid}", method="GET", query={})
    root_set = _unwrap_quiz_api_success_data(pl_set) if isinstance(pl_set, dict) else {}
    qids_ordered: list[str] = []
    if 200 <= int(st_set) < 300:
        qids_ordered = _ordered_question_ids_from_set_upstream_root(root_set)

    collected_in_order: list[dict[str, Any]] = []

    if qids_ordered:
        wanted = set(qids_ordered)
        by_id: dict[str, dict[str, Any]] = {}
        scan_off = 0
        while len(by_id) < len(wanted) and scan_off < max_scan:
            items_page, st_b, pl_err = _pull_bank_page(scan_off)
            if st_b != 200:
                return jsonify(pl_err), st_b
            for it in items_page:
                bid = _question_id_from_bank_item(it)
                if bid in wanted and bid not in by_id:
                    by_id[bid] = it
            if len(items_page) < scan_lim:
                break
            scan_off += scan_lim
        collected_in_order = [by_id[q] for q in qids_ordered if q in by_id]
    else:
        scan_off = 0
        while scan_off < max_scan:
            items_page, st_b, pl_err = _pull_bank_page(scan_off)
            if st_b != 200:
                if scan_off == 0:
                    return jsonify(pl_err), st_b
                break
            for it in items_page:
                if _bank_row_matches_set_id(it, set_sid):
                    collected_in_order.append(it)
            if len(items_page) < scan_lim:
                break
            scan_off += scan_lim

    total = len(collected_in_order)
    sliced = collected_in_order[user_off : user_off + user_lim]
    note = (
        "aiword：已按套题合并过滤。"
        + ("题序来自 GET quiz/sets。" if qids_ordered else "套题明细无题序，已按题目上的 set_id 类字段扫描题库。")
    )
    out_payload: dict[str, Any] = {
        "code": 0,
        "message": "ok",
        "data": {
            "items": sliced,
            "total": total,
            "limit": user_lim,
            "offset": user_off,
            "meta": {
                "aiword_bank_set_filter": True,
                "aiword_set_id": set_sid,
                "aiword_note": note,
                "aiword_set_detail_http": int(st_set),
                "aiword_set_ordered_ids_count": len(qids_ordered),
            },
        },
        "trace_id": trace_id,
        "request": {"url": "", "method": "GET", "upstreamPath": "quiz/bank/questions + aiword set merge"},
    }
    return jsonify(out_payload), 200


@bp.patch("/api/exam-center/teacher/bank/questions/<question_id>")
@page13_access_required
def api_exam_teacher_bank_question_update(question_id: str):
    qid = (question_id or "").strip()
    if not qid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 question_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    status, payload = _quiz_api_call(
        f"quiz/bank/questions/{qid}",
        method="PATCH",
        payload=_json_payload(),
        query=request.args.to_dict(),
    )
    return jsonify(payload), status


@bp.delete("/api/exam-center/teacher/bank/questions/<question_id>")
@page13_access_required
def api_exam_teacher_bank_question_delete(question_id: str):
    qid = (question_id or "").strip()
    if not qid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 question_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    status, payload = _quiz_api_call(
        f"quiz/bank/questions/{qid}",
        method="DELETE",
        payload=_json_payload(),
        query=request.args.to_dict(),
    )
    return jsonify(payload), status


def _exam_stats_options_local() -> dict[str, Any]:
    students_map: dict[str, dict[str, str]] = {}
    try:
        # 与 _local_stats_overview_all / 按学生表同源：按 user_id 去重，取最近一条活动的展示名
        rows = (
            db.session.query(
                ExamCenterActivity.user_id,
                ExamCenterActivity.display_name,
                ExamCenterActivity.username,
            )
            .filter(ExamCenterActivity.user_id.isnot(None))
            .filter(ExamCenterActivity.user_id != "")
            .order_by(ExamCenterActivity.user_id.asc(), ExamCenterActivity.created_at.desc())
            .all()
        )
        for uid, dname, uname in rows:
            sid = str(uid or "").strip()
            if not sid or sid in students_map:
                continue
            label = str(dname or uname or sid).strip() or sid
            students_map[sid] = {"id": sid, "name": label, "label": label}
    except Exception:
        students_map = {}
    students = sorted(students_map.values(), key=lambda x: str(x.get("name") or ""))
    assignments_map: dict[str, dict[str, str]] = {}
    try:
        rows = (
            db.session.query(ExamCenterActivity.assignment_id, ExamCenterActivity.assignment_label)
            .filter(ExamCenterActivity.assignment_id.isnot(None))
            .filter(ExamCenterActivity.assignment_id != "")
            .distinct()
            .limit(500)
            .all()
        )
        for aid, alab in rows:
            k = str(aid or "").strip()
            if not k:
                continue
            lab = str(alab or "").strip() or k
            assignments_map[k] = {"id": k, "name": lab, "label": lab}
        local_rows = (
            ExamCenterAssignment.query.filter(
                or_(
                    ExamCenterAssignment.status.is_(None),
                    ~ExamCenterAssignment.status.in_(("inactive", "cancelled", "archived", "deleted")),
                )
            )
            .limit(500)
            .all()
        )
        for r in local_rows:
            k = str(r.assignment_id or "").strip()
            if not k:
                continue
            lab = str(r.title or "").strip() or k
            assignments_map[k] = {"id": k, "name": lab, "label": lab}
    except Exception:
        assignments_map = {}
    assignments = sorted(assignments_map.values(), key=lambda x: str(x.get("name") or ""))
    return {"students": students, "assignments": assignments}


def _local_focus_flags_for_student(practice_count: int, wrong_total: int, exam_started: int, exam_submitted: int) -> list[str]:
    flags: list[str] = []
    if practice_count < 3:
        flags.append("练习次数少")
    if wrong_total >= 10:
        flags.append("错题多")
    if exam_started > exam_submitted:
        flags.append("未完成考试")
    return flags


def _local_stats_for_student(user_id: str) -> dict[str, Any]:
    uid = str(user_id or "").strip()
    if not uid:
        return {}
    rows = ExamCenterActivity.query.filter_by(user_id=uid).order_by(ExamCenterActivity.created_at.desc()).all()
    if not rows:
        return {
            "student_id": uid,
            "student_name": uid,
            "practice_count": 0,
            "exam_submitted_count": 0,
            "exam_started_count": 0,
            "wrong_total": 0,
            "pass_count": 0,
            "fail_count": 0,
            "pass_rate_percent": None,
            "focus_flags": ["练习次数少"],
        }
    ids = [str(r.id) for r in rows if getattr(r, "id", None)]
    det_map: dict[str, ExamCenterActivityDetail] = {}
    if ids:
        ds = ExamCenterActivityDetail.query.filter(ExamCenterActivityDetail.activity_id.in_(ids)).all()
        det_map = {str(d.activity_id): d for d in ds}
    pass_score = _exam_pass_score()
    practice_count = 0
    exam_submitted = 0
    exam_started = 0
    wrong_total = 0
    pass_count = 0
    fail_count = 0
    student_name = ""
    for r in rows:
        if not student_name:
            student_name = str(r.display_name or r.username or r.user_id or "").strip()
        m = str(r.mode or "").strip().lower()
        if m == "practice":
            practice_count += 1
        if m == "exam":
            exam_submitted += 1
        if r.assignment_id:
            exam_started += 1
        d = det_map.get(str(r.id))
        if d and d.wrong_count is not None:
            wrong_total += int(d.wrong_count)
        if d and d.score is not None and m == "exam":
            if float(d.score) >= pass_score:
                pass_count += 1
            else:
                fail_count += 1
    if exam_started < exam_submitted:
        exam_started = exam_submitted
    graded = pass_count + fail_count
    pass_rate = round((pass_count * 100.0 / graded), 2) if graded > 0 else None
    return {
        "student_id": uid,
        "student_name": student_name or uid,
        "practice_count": practice_count,
        "exam_submitted_count": exam_submitted,
        "exam_started_count": exam_started,
        "wrong_total": wrong_total,
        "pass_score": pass_score,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_rate_percent": pass_rate,
        "focus_flags": _local_focus_flags_for_student(practice_count, wrong_total, exam_started, exam_submitted),
    }


def _local_stats_all_students_rows() -> list[dict[str, Any]]:
    """按学生在本地聚合多行指标（与会话下拉中的学生列表同源）。"""
    opts = _exam_stats_options_local()
    studs = opts.get("students") if isinstance(opts.get("students"), list) else []
    rows: list[dict[str, Any]] = []
    for s in studs:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        row = _local_stats_for_student(sid)
        if not row:
            continue
        pc = int(row.get("pass_count") or 0)
        fc = int(row.get("fail_count") or 0)
        row["graded_exam_count"] = pc + fc
        row["total_learning_count"] = int(row.get("practice_count") or 0) + int(row.get("exam_submitted_count") or 0)
        rows.append(row)
    rows.sort(key=lambda x: str(x.get("student_name") or x.get("student_id") or ""))
    return rows


def _local_stats_rows_student_by_mode() -> list[dict[str, Any]]:
    """学生 ×（考试/练习）交叉分组：记录数、已判分、通过/不通过/通过率；判分口径与 /stats/mode 一致（有 score 即计分）。"""
    opts = _exam_stats_options_local()
    studs = opts.get("students") if isinstance(opts.get("students"), list) else []
    pass_score = _exam_pass_score()
    out: list[dict[str, Any]] = []
    for s in studs:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        label = str(s.get("label") or s.get("name") or sid).strip() or sid
        rows_u = ExamCenterActivity.query.filter_by(user_id=sid).order_by(ExamCenterActivity.created_at.desc()).all()
        ids = [str(r.id) for r in rows_u if getattr(r, "id", None)]
        det_map: dict[str, ExamCenterActivityDetail] = {}
        if ids:
            ds = ExamCenterActivityDetail.query.filter(ExamCenterActivityDetail.activity_id.in_(ids)).all()
            det_map = {str(d.activity_id): d for d in ds}
        for mode_key, mode_label in (("exam", "考试"), ("practice", "练习")):
            subset = [r for r in rows_u if str(r.mode or "").strip().lower() == mode_key]
            total = len(subset)
            graded = 0
            pc = 0
            fc = 0
            for r in subset:
                d = det_map.get(str(r.id))
                if not d or d.score is None:
                    continue
                graded += 1
                if float(d.score) >= pass_score:
                    pc += 1
                else:
                    fc += 1
            pr = round((pc * 100.0 / graded), 2) if graded > 0 else None
            out.append(
                {
                    "student_id": sid,
                    "student_name": label,
                    "mode": mode_key,
                    "mode_label": mode_label,
                    "total_count": total,
                    "graded_count": graded,
                    "pass_score": pass_score,
                    "pass_count": pc,
                    "fail_count": fc,
                    "pass_rate_percent": pr,
                }
            )
    out.sort(key=lambda x: (str(x.get("student_name") or ""), 0 if x.get("mode") == "exam" else 1))
    return out


def _local_stats_overview_all() -> dict[str, Any]:
    """全库聚合（不按条数截断），与 /stats/mode、按学生聚合口径一致。"""
    pass_score = _exam_pass_score()
    practice_count = ExamCenterActivity.query.filter_by(mode="practice").count()
    exam_act = ExamCenterActivity.query.filter_by(mode="exam").all()
    exam_count = len(exam_act)
    ids_exam = [str(r.id) for r in exam_act if getattr(r, "id", None)]
    det_map: dict[str, ExamCenterActivityDetail] = {}
    if ids_exam:
        ds = ExamCenterActivityDetail.query.filter(ExamCenterActivityDetail.activity_id.in_(ids_exam)).all()
        det_map = {str(d.activity_id): d for d in ds}
    pass_count = 0
    fail_count = 0
    for r in exam_act:
        d = det_map.get(str(r.id))
        if not d or d.score is None:
            continue
        if float(d.score) >= pass_score:
            pass_count += 1
        else:
            fail_count += 1
    graded_exam_count = pass_count + fail_count
    pass_rate = round((pass_count * 100.0 / graded_exam_count), 2) if graded_exam_count > 0 else None
    try:
        urows = (
            db.session.query(ExamCenterActivity.user_id)
            .filter(ExamCenterActivity.user_id.isnot(None))
            .filter(ExamCenterActivity.user_id != "")
            .distinct()
            .all()
        )
        uid_list = [str(u[0]).strip() for u in urows if u and u[0]]
    except Exception:
        uid_list = []
    by_student: dict[str, dict[str, Any]] = {}
    for uid in uid_list:
        by_student[uid] = _local_stats_for_student(uid)
    focus_students = [v for v in by_student.values() if v.get("focus_flags")]
    return {
        "practice_count": practice_count,
        "exam_count": exam_count,
        "graded_exam_count": graded_exam_count,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "pass_score": pass_score,
        "pass_rate_percent": pass_rate,
        "students_total": len(by_student),
        "focus_students": focus_students,
    }


def _exam_stats_recent_activity_local(limit: int) -> list[dict[str, Any]]:
    lim = max(1, min(200, int(limit or 80)))
    out: list[dict[str, Any]] = []
    pass_score = _exam_pass_score()
    try:
        rows = ExamCenterActivity.query.order_by(ExamCenterActivity.created_at.desc()).limit(lim).all()
        ids = [str(r.id) for r in rows if getattr(r, "id", None)]
        det_map: dict[str, ExamCenterActivityDetail] = {}
        if ids:
            ds = ExamCenterActivityDetail.query.filter(ExamCenterActivityDetail.activity_id.in_(ids)).all()
            det_map = {str(d.activity_id): d for d in ds}
        for a in rows:
            d = det_map.get(str(a.id))
            mode = str(a.mode or "").strip().lower()
            mode_label = "练习" if mode == "practice" else ("考试" if mode == "exam" else mode or "-")
            who = (a.display_name or a.username or a.user_id or "-").strip() or "-"
            tgt = (a.assignment_label or a.set_id or a.attempt_id or "-") or "-"
            res = (a.result_summary or "").strip() or "-"
            out.append(
                {
                    "id": a.id,
                    "created_at": a.created_at.isoformat() if a.created_at else "",
                    "user_id": a.user_id,
                    "student_name": who,
                    "mode": a.mode,
                    "mode_label": mode_label,
                    "assignment_id": str(a.assignment_id).strip() if getattr(a, "assignment_id", None) else "",
                    "target_label": str(tgt),
                    "result": res[:500],
                    "score": d.score if d else None,
                    "total_score": d.total_score if d else None,
                    "correct_count": d.correct_count if d else None,
                    "wrong_count": d.wrong_count if d else None,
                    "pass_score": pass_score,
                    "passed": (d.score is not None and float(d.score) >= pass_score) if d and d.score is not None else None,
                    "weakness": d.weakness if d else None,
                    "recommendation": d.recommendation if d else None,
                }
            )
    except Exception:
        return []
    return out


@bp.get("/api/exam-center/stats/options")
@page13_access_required
def api_exam_stats_options():
    local = _exam_stats_options_local()
    return jsonify(
        {
            "code": 0,
            "message": "ok（本地统计）",
            "data": local,
            "trace_id": uuid.uuid4().hex,
            "request": {"url": "", "method": "GET", "upstreamPath": "local aggregate"},
        }
    ), 200


@bp.get("/api/exam-center/stats/recent-activity")
@page13_access_required
def api_exam_stats_recent_activity():
    try:
        lim = int(str(request.args.get("limit") or "80"))
    except (TypeError, ValueError):
        lim = 80
    recs = _exam_stats_recent_activity_local(lim)
    # 本地筛选：仅影响“记录列表”，不影响看板
    want_uid = str(request.args.get("student_id") or request.args.get("user_id") or "").strip()
    want_aid = str(request.args.get("assignment_id") or "").strip()
    if want_uid:
        recs = [x for x in recs if str((x or {}).get("user_id") or "").strip() == want_uid]
    if want_aid:
        recs = [x for x in recs if str((x or {}).get("assignment_id") or "").strip() == want_aid]
    return jsonify(
        {
            "code": 0,
            "message": "ok（本地统计）",
            "data": {"records": recs},
            "trace_id": uuid.uuid4().hex,
            "request": {"url": "", "method": "GET", "upstreamPath": "local aggregate"},
        }
    ), 200


@bp.post("/api/exam-center/teacher/sets/review-by-ai")
@page13_access_required
def api_exam_teacher_review_set():
    data = _json_payload()
    set_id = (data.pop("set_id", "") or "").strip()
    if not set_id:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 set_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    status, payload = _quiz_api_call(
        f"quiz/sets/{set_id}/review-by-ai",
        method="POST",
        payload=data,
    )
    # 异步复审：上游立即返回 job_id；本地落库便于轮询与任务列表（与录题 ingest 一致）
    if 200 <= int(status) < 300 and isinstance(payload, dict):
        upstream_job_id = _guess_job_id_from_payload(payload)
        if upstream_job_id:
            created_by = (session.get("display_name") or session.get("username") or "").strip() or None
            row = ExamSetReviewJob.query.filter_by(upstream_job_id=upstream_job_id).first()
            if not row:
                row = ExamSetReviewJob(
                    upstream_job_id=upstream_job_id,
                    set_id=set_id,
                    status="pending",
                    created_by=created_by,
                )
            row.last_upstream_http_status = int(status)
            row.last_upstream_data = payload.get("data") if isinstance(payload.get("data"), dict) else payload.get("data")
            row.last_upstream_request_url = ((payload.get("request") or {}).get("url") if isinstance(payload.get("request"), dict) else None) or None
            row.last_upstream_trace_id = (payload.get("trace_id") or None)
            row.last_message = (payload.get("message") or None)
            row.status = _normalize_job_status_from_upstream_data(payload.get("data")) or "running"
            db.session.add(row)
            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                if isinstance(payload, dict):
                    payload["job_record_error"] = f"aiword 落库失败（不影响上游任务）：{e}"
            else:
                if isinstance(payload, dict):
                    payload["job_record"] = {
                        "id": row.id,
                        "upstream_job_id": row.upstream_job_id,
                        "set_id": row.set_id,
                        "status": row.status,
                    }
    return jsonify(payload), status


@bp.get("/api/exam-center/teacher/sets/review-jobs/<job_id>")
@page13_access_required
def api_exam_teacher_review_job(job_id: str):
    job_id = (job_id or "").strip()
    if not job_id:
        return (
            jsonify(
                {
                    "code": "BAD_REQUEST",
                    "message": "缺少 job_id",
                    "data": None,
                    "trace_id": uuid.uuid4().hex,
                    "request": {"url": "", "method": "GET", "upstreamPath": ""},
                }
            ),
            400,
        )
    row = ExamSetReviewJob.query.filter_by(upstream_job_id=job_id).first()
    refresh = (request.args.get("refresh") or "1").strip()
    if refresh not in {"0", "false", "no"}:
        status, payload = _quiz_api_call(
            f"quiz/sets/review-jobs/{job_id}",
            method="GET",
            query={k: v for k, v in request.args.to_dict().items() if k != "refresh"},
        )
        if row is None:
            row = ExamSetReviewJob(upstream_job_id=job_id, status="unknown")
        row.last_upstream_http_status = int(status)
        if isinstance(payload, dict):
            row.last_message = (payload.get("message") or None)
            row.last_upstream_trace_id = (payload.get("trace_id") or None)
            req_meta = payload.get("request") if isinstance(payload.get("request"), dict) else {}
            row.last_upstream_request_url = (req_meta.get("url") or None)
            row.last_upstream_data = payload.get("data")
            row.status = _normalize_job_status_from_upstream_data(payload.get("data"))
        db.session.add(row)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            if isinstance(payload, dict):
                payload["job_record_error"] = f"aiword 落库失败（不影响上游查询）：{e}"
        else:
            if isinstance(payload, dict):
                payload["job_record"] = {
                    "id": row.id,
                    "upstream_job_id": row.upstream_job_id,
                    "set_id": row.set_id,
                    "status": row.status,
                }
        return jsonify(payload), status

    if row is None:
        return jsonify({"code": "NOT_FOUND", "message": "本地无该任务记录", "data": None, "trace_id": uuid.uuid4().hex}), 404
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "job_record": {
                    "id": row.id,
                    "upstream_job_id": row.upstream_job_id,
                    "set_id": row.set_id,
                    "status": row.status,
                    "created_by": row.created_by,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "last_message": row.last_message,
                    "last_upstream_http_status": row.last_upstream_http_status,
                    "last_upstream_request_url": row.last_upstream_request_url,
                    "last_upstream_trace_id": row.last_upstream_trace_id,
                    "last_upstream_data": row.last_upstream_data,
                }
            },
            "trace_id": uuid.uuid4().hex,
        }
    )


@bp.get("/api/exam-center/teacher/sets/review-jobs")
@page13_access_required
def api_exam_teacher_review_jobs_list():
    limit_raw = (request.args.get("limit") or "20").strip()
    try:
        limit = int(limit_raw)
    except ValueError:
        limit = 20
    if limit < 1:
        limit = 1
    if limit > 200:
        limit = 200

    rows = ExamSetReviewJob.query.order_by(ExamSetReviewJob.created_at.desc()).limit(limit).all()
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "jobs": [
                    {
                        "id": r.id,
                        "upstream_job_id": r.upstream_job_id,
                        "set_id": r.set_id,
                        "status": r.status,
                        "created_by": r.created_by,
                        "created_at": r.created_at.isoformat() if r.created_at else None,
                        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                        "last_message": r.last_message,
                        "last_upstream_http_status": r.last_upstream_http_status,
                        "last_upstream_request_url": r.last_upstream_request_url,
                        "last_upstream_trace_id": r.last_upstream_trace_id,
                    }
                    for r in rows
                ]
            },
            "trace_id": uuid.uuid4().hex,
        }
    )


@bp.post("/api/exam-center/teacher/sets/publish")
@page13_access_required
def api_exam_teacher_publish_set():
    data = _json_payload()
    set_id = (data.pop("set_id", "") or "").strip()
    if not set_id:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 set_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    status, payload = _quiz_api_call(
        f"quiz/sets/{set_id}/publish",
        method="POST",
        payload=data,
    )
    return jsonify(payload), status


@bp.post("/api/exam-center/teacher/papers")
@page13_access_required
def api_exam_teacher_create_paper():
    status, payload = _quiz_api_call("quiz/papers", method="POST", payload=_json_payload())
    return jsonify(payload), status


@bp.post("/api/exam-center/teacher/assignments")
@page13_access_required
def api_exam_teacher_create_assignment():
    req = _json_payload()
    due_val, due_update = _parse_assignment_due_from_request(req)
    forward = dict(req) if isinstance(req, dict) else {}
    if due_val and "due_at" not in forward and "dueAt" not in forward:
        forward["due_at"] = due_val.isoformat(sep=" ", timespec="seconds")
    # 上游（aicheckword）在部分版本中不提供 quiz/assignments 下发接口；
    # 404/405 时回退为“仅本地下发”（学生端列表已有上游失败→本地镜像兜底）。
    status, payload, tried = _quiz_try_paths(
        [
            "quiz/assignments",  # 某些上游实现
            "quiz/teacher/assignments",
            "quiz/exam-center/assignments",
        ],
        method="POST",
        payload=forward,
        query=None,
    )
    if isinstance(payload, dict) and tried:
        payload.setdefault("request", {})
        if isinstance(payload.get("request"), dict):
            payload["request"]["upstreamTried"] = tried

    if int(status) in (404, 405) or (
        isinstance(payload, dict)
        and payload.get("code") in ("QUIZ_API_UPSTREAM_ERROR", "QUIZ_API_NOT_CONFIGURED")
        and int(status) in (404, 405, 503)
    ):
        # 本地下发：生成 assignment_id 并写入镜像表
        aid_local = "loc-" + uuid.uuid4().hex[:24]
        title_local = str(req.get("title") or req.get("name") or req.get("label") or "").strip() or None
        set_id_local = str(req.get("set_id") or req.get("setId") or "").strip() or None
        exam_track_local = str(req.get("exam_track") or req.get("examTrack") or "").strip() or None
        diff_req = str(req.get("difficulty") or req.get("difficultyLevel") or "").strip().lower()
        if diff_req not in ("easy", "medium", "hard"):
            diff_req = ""
        row = ExamCenterAssignment(assignment_id=aid_local)
        row.title = title_local
        row.set_id = set_id_local
        row.exam_track = exam_track_local
        row.difficulty = diff_req or None
        row.status = "published"
        row.created_by = (session.get("display_name") or session.get("username") or "").strip() or None
        if due_update:
            row.due_at = due_val
        db.session.add(row)
        try:
            db.session.commit()
            return (
                jsonify(
                    {
                        "code": 0,
                        "message": "ok（上游不支持下发接口，已改为仅本地下发）",
                        "data": {
                            "assignment_id": row.assignment_id,
                            "title": row.title,
                            "set_id": row.set_id,
                            "exam_track": row.exam_track,
                            "difficulty": row.difficulty,
                            "status": row.status,
                            "due_at": row.due_at.isoformat(timespec="seconds") if getattr(row, "due_at", None) else None,
                            "aiword_local_only": True,
                        },
                        "trace_id": uuid.uuid4().hex,
                    }
                ),
                200,
            )
        except Exception as e:
            db.session.rollback()
            return jsonify({"code": "DB_ERROR", "message": str(e), "data": None, "trace_id": uuid.uuid4().hex}), 500

    if 200 <= int(status) < 300 and isinstance(payload, dict):
        aid, title, set_id = _extract_assignment_from_quiz_payload(payload)
        if aid:
            row = ExamCenterAssignment.query.filter_by(assignment_id=aid).first()
            if not row:
                row = ExamCenterAssignment(assignment_id=aid)
            row.title = title or row.title
            row.set_id = set_id or row.set_id or str(req.get("set_id") or req.get("setId") or "").strip() or None
            row.exam_track = str(req.get("exam_track") or req.get("examTrack") or "").strip() or row.exam_track
            diff_req = str(req.get("difficulty") or req.get("difficultyLevel") or "").strip().lower()
            if diff_req in ("easy", "medium", "hard"):
                row.difficulty = diff_req
            if due_update:
                row.due_at = due_val
            sid = str(row.set_id or "").strip()
            if sid and (not row.difficulty or row.difficulty not in ("easy", "medium", "hard")):
                st_set, pl_set = _quiz_api_call(f"quiz/sets/{_urlquote(sid, safe='')}", method="GET", query=None)
                if 200 <= int(st_set) < 300 and isinstance(pl_set, dict):
                    d2 = _difficulty_from_quiz_get_set_payload(pl_set)
                    if d2:
                        row.difficulty = d2
            row.status = "published"
            row.created_by = (session.get("display_name") or session.get("username") or "").strip() or row.created_by
            db.session.add(row)
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
            else:
                payload.setdefault("aiword", {})
                if isinstance(payload.get("aiword"), dict):
                    payload["aiword"]["assignment"] = {
                        "assignment_id": row.assignment_id,
                        "title": row.title,
                        "set_id": row.set_id,
                        "exam_track": row.exam_track,
                    }
    return jsonify(payload), status


@bp.post("/api/exam-center/teacher/assignments/issue")
@page13_access_required
def api_exam_teacher_issue_assignments_modal():
    """老师端弹窗：本地下发考试任务（含受众/截止/目的），学生端仅受众可见。"""
    req = _json_payload()
    due_val, due_update = _parse_assignment_due_from_request(req)
    purpose = str(req.get("purpose") or req.get("exam_purpose") or "").strip() or None
    exam_track = str(req.get("exam_track") or req.get("examTrack") or "").strip() or None

    aud = req.get("audience_user_ids") or req.get("audienceUserIds") or req.get("user_ids") or []
    audience_ids = [str(x).strip() for x in aud] if isinstance(aud, list) else []
    audience_ids = [x for x in audience_ids if x]

    items = req.get("items")
    set_ids: list[str] = []
    title_by_set: dict[str, str] = {}
    if isinstance(items, list) and items:
        for it in items:
            if not isinstance(it, dict):
                continue
            sid = str(it.get("set_id") or it.get("setId") or "").strip()
            if not sid:
                continue
            set_ids.append(sid)
            ttl = str(it.get("title") or it.get("name") or "").strip()
            if ttl:
                title_by_set[sid] = ttl
    else:
        sid0 = str(req.get("set_id") or req.get("setId") or "").strip()
        if sid0:
            set_ids = [sid0]
            ttl0 = str(req.get("title") or req.get("name") or "").strip()
            if ttl0:
                title_by_set[sid0] = ttl0

    if not set_ids:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 set_id/items", "data": None, "trace_id": uuid.uuid4().hex}), 400
    if not audience_ids:
        return jsonify({"code": "BAD_REQUEST", "message": "请选择考试对象（至少1人）", "data": None, "trace_id": uuid.uuid4().hex}), 400

    created: list[dict[str, Any]] = []
    try:
        for sid in set_ids:
            aid_local = "loc-" + uuid.uuid4().hex[:24]
            title = (title_by_set.get(sid) or "").strip()
            if title:
                nm = title + " 考试任务"
            else:
                nm = f"{sid} 考试任务"
            row = ExamCenterAssignment(assignment_id=aid_local)
            row.title = nm
            row.set_id = sid
            row.exam_track = exam_track
            row.status = "published"
            row.created_by = (session.get("display_name") or session.get("username") or "").strip() or None
            if due_update:
                row.due_at = due_val
            db.session.add(row)
            db.session.flush()

            if purpose:
                ex = ExamCenterAssignmentExtra.query.filter_by(assignment_id=aid_local).first()
                if not ex:
                    ex = ExamCenterAssignmentExtra(assignment_id=aid_local)
                ex.purpose = purpose
                db.session.add(ex)

            for uid in audience_ids:
                db.session.add(ExamCenterAssignmentAudience(assignment_id=aid_local, user_id=uid))

            created.append(
                {
                    "assignment_id": aid_local,
                    "title": nm,
                    "set_id": sid,
                    "exam_track": exam_track,
                    "due_at": due_val.isoformat(timespec="seconds") if (due_update and due_val) else None,
                    "purpose": purpose,
                    "audience_user_ids": audience_ids,
                    "aiword_local_only": True,
                }
            )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": "DB_ERROR", "message": str(e), "data": None, "trace_id": uuid.uuid4().hex}), 500

    return jsonify({"code": 0, "message": "ok", "data": {"created": created}, "trace_id": uuid.uuid4().hex}), 200


def _exam_try_upstream_modify_assignment_proxy(assignment_id: str, op: str) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    """对已下发任务调用上游可变路径；不要求全部成功以便本地仍可收口。"""
    aid = (assignment_id or "").strip()
    q = _urlquote(aid, safe="")
    attempts: list[dict[str, Any]] = []
    last_status = 599
    last_pl: dict[str, Any] = {}
    ops = []
    op_l = op.lower().strip()
    if op_l == "delete":
        ops = [(f"quiz/assignments/{q}", "DELETE", None)]
    elif op_l == "unpublish":
        ops = [
            # 常见语义：设为无效/归档
            (
                f"quiz/assignments/{q}",
                "PATCH",
                {"status": "inactive", "is_active": False, "cancelled": True},
            ),
            (f"quiz/assignments/{q}/cancel", "POST", {}),
        ]
    for path, meth, bod in ops:
        st0, pl0 = _quiz_api_call(path.strip("/"), method=meth, payload=bod if isinstance(bod, dict) else None)
        attempts.append({"path": path, "method": meth, "http_status": int(st0)})
        last_status = int(st0)
        last_pl = pl0 if isinstance(pl0, dict) else {}
        if 200 <= int(st0) < 300:
            break
        if int(st0) == 204:
            break
    return attempts, last_status, last_pl


@bp.get("/api/exam-center/teacher/assignments-local")
@page13_access_required
def api_teacher_assignments_local_list():
    """老师端：列出 aiword 本地镜像的考试任务。"""
    try:
        rows = ExamCenterAssignment.query.order_by(ExamCenterAssignment.created_at.desc()).limit(500).all()
    except Exception as e:
        return jsonify(
            {
                "code": "DB_ERROR",
                "message": f"查询失败：{e}",
                "data": {"rows": []},
                "trace_id": uuid.uuid4().hex,
            }
        ), 500
    out_rows: list[dict[str, Any]] = []
    for r in rows:
        out_rows.append(
            {
                "assignment_id": r.assignment_id,
                "title": (r.title or r.assignment_id or "").strip(),
                "set_id": r.set_id,
                "exam_track": r.exam_track,
                "difficulty": (r.difficulty or "").strip() if getattr(r, "difficulty", None) else "",
                "status": (r.status or "").strip(),
                "due_at": r.due_at.isoformat(timespec="seconds") if getattr(r, "due_at", None) else None,
                "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else "",
            }
        )
    return jsonify(
        {"code": 0, "message": "ok", "data": {"rows": out_rows}, "trace_id": uuid.uuid4().hex}
    ), 200


@bp.delete("/api/exam-center/teacher/assignments/<assignment_id>")
@page13_access_required
def api_teacher_delete_local_assignment(assignment_id: str):
    aid = (assignment_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 assignment_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    attempts, last_st, last_pl = _exam_try_upstream_modify_assignment_proxy(aid, "delete")
    row = ExamCenterAssignment.query.filter_by(assignment_id=aid).first()
    if row:
        try:
            ExamCenterAssignment.query.filter_by(assignment_id=aid).delete()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"code": "DB_ERROR", "message": str(e), "data": None, "trace_id": uuid.uuid4().hex}), 500
    return jsonify(
        {
            "code": 0,
            "message": "已删除本地任务记录" + ("；上游返回值见 data.last_upstream。" if attempts else ""),
            "data": {"assignment_id": aid, "upstream_attempts": attempts, "last_upstream": last_pl, "last_http_status": last_st},
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.post("/api/exam-center/teacher/assignments/<assignment_id>/unpublish")
@page13_access_required
def api_teacher_unpublish_local_assignment(assignment_id: str):
    aid = (assignment_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 assignment_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    attempts, last_st, last_pl = _exam_try_upstream_modify_assignment_proxy(aid, "unpublish")
    row = ExamCenterAssignment.query.filter_by(assignment_id=aid).first()
    if row:
        try:
            row.status = "inactive"
            db.session.add(row)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"code": "DB_ERROR", "message": str(e), "data": None, "trace_id": uuid.uuid4().hex}), 500
    return jsonify(
        {
            "code": 0,
            "message": "已标记本地任务下架（inactive）；" + ("上游返回码=" + str(last_st)),
            "data": {"assignment_id": aid, "upstream_attempts": attempts, "last_upstream": last_pl, "last_http_status": last_st},
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.post("/api/exam-center/student/practice/generate-set")
@login_required
def api_exam_student_generate_practice_set():
    body = _expand_exam_track_and_difficulty_aliases(_expand_question_count_aliases(_json_payload()))
    uid = str(session.get("user_id") or "").strip()
    if uid:
        body["user_id"] = uid
        body["userId"] = uid
    status, payload = _quiz_api_call("quiz/practice/generate-set", method="POST", payload=body)
    return jsonify(payload), status


@bp.post("/api/exam-center/student/practice/submit")
@login_required
def api_exam_student_submit_practice():
    body = _normalize_practice_submit_upstream_body(_json_payload())
    uid = str(session.get("user_id") or "").strip()
    if uid:
        body.setdefault("user_id", uid)
        body.setdefault("userId", uid)
    attempt_q = str(body.get("attempt_id") or body.get("attemptId") or "").strip()
    q = {"attempt_id": attempt_q} if attempt_q else None
    status, payload = _quiz_api_call("quiz/practice/submit", method="POST", payload=body, query=q)
    if 200 <= int(status) < 300 and isinstance(payload, dict):
        # HTTP 成功即落库：上游 data 内 code 非成功时过去会跳过写库，导致历史「丢记录」
        up_raw = payload.get("data")
        up_root = up_raw if isinstance(up_raw, dict) else {}
        merged = _merge_upstream_snapshot_with_submitted_answers(up_root, body)
        if isinstance(up_raw, dict) and not _exam_activity_upstream_root_ok(up_raw):
            merged["aiword_upstream_business_uncertain"] = True
        inner_m = merged.get("data") if isinstance(merged.get("data"), dict) else {}
        mx = _extract_result_metrics(merged)
        summ = _exam_activity_history_result_text(
            "practice",
            mx,
            merged.get("message") or payload.get("message"),
        )
        set_id = str(body.get("set_id") or inner_m.get("set_id") or inner_m.get("setId") or "").strip() or None
        etrack = str(body.get("exam_track") or "").strip() or None
        _log_student_exam_center_activity(
            mode="practice",
            exam_track=etrack,
            set_id=set_id,
            assignment_id=None,
            assignment_label=None,
            attempt_id=str(body.get("attempt_id") or body.get("attemptId") or body.get("session_id") or "").strip() or None,
            upstream_http_status=int(status),
            upstream_trace_id=str(payload.get("trace_id") or "").strip() or None,
            result_summary=summ,
            upstream_result_payload=merged,
        )
    return jsonify(payload), status


@bp.get("/api/exam-center/student/quiz/grading-status/<path:attempt_id>")
@login_required
def api_student_quiz_grading_status(attempt_id: str):
    aid = (attempt_id or "").strip().lstrip("/")
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 attempt_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    st, pl = _quiz_api_call(f"quiz/attempts/{_urlquote(aid, safe='')}/grading-status", method="GET")
    return jsonify(pl), st


@bp.post("/api/exam-center/student/quiz/sync-attempt-result")
@login_required
def api_student_sync_quiz_attempt_result():
    body = _json_payload()
    aid = str(body.get("attempt_id") or body.get("attemptId") or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 attempt_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    uid = str(session.get("user_id") or "").strip()
    if not uid:
        return jsonify({"code": "UNAUTHORIZED", "message": "未登录", "data": None, "trace_id": uuid.uuid4().hex}), 401

    row = (
        ExamCenterActivity.query.filter_by(user_id=uid, attempt_id=aid)
        .order_by(ExamCenterActivity.created_at.desc())
        .first()
    )
    if not row:
        return jsonify(
            {"code": "NOT_FOUND", "message": "未找到与该 attempt 匹配的本地记录", "data": {"updated": False}, "trace_id": uuid.uuid4().hex}
        ), 404

    st, pl = _quiz_api_call(f"quiz/attempts/{_urlquote(aid, safe='')}/grading-status", method="GET")
    if not (200 <= int(st) < 300) or not isinstance(pl, dict):
        return jsonify(pl), st

    uq = _unwrap_quiz_api_success_data(pl)
    if isinstance(uq, dict) and uq.get("ok") is True and isinstance(uq.get("data"), dict):
        gdata = uq["data"]
    elif isinstance(uq, dict):
        gdata = uq
    else:
        gdata = {}

    ready = bool(gdata.get("ready"))
    if not ready:
        return jsonify(
            {
                "code": 0,
                "message": "ok（仍阅卷中）",
                "data": {"updated": False, "grading": gdata},
                "trace_id": uuid.uuid4().hex,
            }
        ), 200

    metrics = _extract_result_metrics(dict(gdata))
    summ = _exam_activity_history_result_text(str(row.mode or ""), metrics, gdata.get("grading_message"))
    row.result_summary = (summ or "")[:500]

    det = ExamCenterActivityDetail.query.filter_by(activity_id=str(row.id)).first()
    if det:
        try:
            det.score = int(round(float(metrics.get("score") or 0)))
        except Exception:
            det.score = metrics.get("score")
        ts_m = metrics.get("total_score")
        try:
            det.total_score = int(round(float(ts_m))) if ts_m is not None else det.score
        except Exception:
            det.total_score = ts_m if ts_m is not None else det.score
        det.correct_count = metrics.get("correct_count")
        det.wrong_count = metrics.get("wrong_count")
        merged_up = dict(det.upstream_payload or {})
        merged_up["grading_sync"] = gdata
        det.upstream_payload = merged_up
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": "DB_ERROR", "message": str(e), "data": {"updated": False}, "trace_id": uuid.uuid4().hex}), 500

    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {"updated": True, "grading": gdata, "result_summary": summ},
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.get("/api/exam-center/student/wrongbook")
@login_required
def api_exam_student_wrongbook():
    q = dict(request.args.to_dict())
    uid = str(session.get("user_id") or "").strip()
    if uid:
        q["user_id"] = uid
        q["userId"] = uid
    status, payload = _quiz_api_call("quiz/wrongbook", method="GET", query=q)
    return jsonify(payload), status


@bp.get("/api/exam-center/student/unpracticed-bank")
@login_required
def api_exam_student_unpracticed_bank():
    q = dict(request.args.to_dict())
    uid = str(session.get("user_id") or "").strip()
    if uid:
        q["user_id"] = uid
        q["userId"] = uid
    status, payload = _quiz_api_call("quiz/student/unpracticed-bank", method="GET", query=q)
    return jsonify(payload), status


@bp.get("/api/exam-center/student/bank/tracks")
@login_required
def api_exam_student_tracks():
    status, payload = _quiz_api_call("quiz/bank/tracks", method="GET", query=request.args.to_dict())
    return jsonify(payload), status


@bp.get("/api/exam-center/student/assignments")
@login_required
def api_exam_student_assignments_list():
    paths = [
        "quiz/student/assignments",
        "quiz/me/assignments",
        "quiz/student/exams",
    ]
    st, pl, tried = _quiz_try_paths(paths, method="GET", query=request.args.to_dict())
    upstream_http_ok = 200 <= int(st) < 300 and isinstance(pl, dict)
    raw_list: list[dict[str, Any]] = []
    if upstream_http_ok:
        root = _unwrap_quiz_api_success_data(pl)
        raw_list = _extract_assignments_from_quiz_root(root)
    normalized: list[dict[str, Any]] = []
    for x in raw_list:
        if not isinstance(x, dict):
            continue
        row = _normalize_student_assignment_row(x)
        if row["id"]:
            normalized.append(row)
    aids = [str(r.get("id") or "").strip() for r in normalized if str(r.get("id") or "").strip()]
    due_map: dict[str, Optional[datetime]] = {}
    if aids:
        try:
            for ar in ExamCenterAssignment.query.filter(ExamCenterAssignment.assignment_id.in_(aids)).all():
                aid_k = str(ar.assignment_id or "").strip()
                if aid_k:
                    due_map[aid_k] = getattr(ar, "due_at", None)
        except Exception:
            due_map = {}
    for r in normalized:
        aid_k = str(r.get("id") or "").strip()
        dt = due_map.get(aid_k)
        if dt:
            r["due_at"] = dt.isoformat(timespec="seconds")
    # 仅当上游请求未成功时使用本地镜像兜底。若上游已 200（即使列表为空），不得展示孤立的本地 assignment，
    # 否则会列出上游已不可用/或过期的 assignment_id，学生点击开考会一直等待或失败。
    if not normalized and not upstream_http_ok:
        try:
            local_rows = (
                ExamCenterAssignment.query.filter(
                    or_(
                        ExamCenterAssignment.status.is_(None),
                        ~ExamCenterAssignment.status.in_(("inactive", "cancelled", "archived", "deleted")),
                    )
                )
                .order_by(ExamCenterAssignment.created_at.desc())
                .limit(200)
                .all()
            )
            uid_cur = str(session.get("user_id") or "").strip()
            allow_ids: set[str] = set()
            any_audience_ids: set[str] = set()
            try:
                # 若任务配置了受众，则仅允许受众可见；未配置受众的历史任务默认全员可见。
                aids_all = [str(r.assignment_id or "").strip() for r in local_rows if str(r.assignment_id or "").strip()]
                if aids_all:
                    any_audience_ids = {
                        str(x.assignment_id)
                        for x in ExamCenterAssignmentAudience.query.filter(
                            ExamCenterAssignmentAudience.assignment_id.in_(aids_all)
                        ).all()
                    }
                    if uid_cur:
                        allow_ids = {
                            str(x.assignment_id)
                            for x in ExamCenterAssignmentAudience.query.filter_by(user_id=uid_cur).filter(
                                ExamCenterAssignmentAudience.assignment_id.in_(aids_all)
                            ).all()
                        }
            except Exception:
                allow_ids = set()
                any_audience_ids = set()
            for r in local_rows:
                aid = str(r.assignment_id or "").strip()
                if not aid:
                    continue
                if any_audience_ids and aid in any_audience_ids and aid not in allow_ids:
                    continue
                nm = str(r.title or aid).strip() or aid
                diff_l = (getattr(r, "difficulty", None) or "").strip().lower()
                due_loc = getattr(r, "due_at", None)
                normalized.append(
                    {
                        "id": aid,
                        "name": nm,
                        "label": nm,
                        **({"difficulty": diff_l} if diff_l in ("easy", "medium", "hard") else {}),
                        **(
                            {"due_at": due_loc.isoformat(timespec="seconds")}
                            if due_loc
                            else {}
                        ),
                    }
                )
        except Exception:
            pass
    return jsonify(
        {
            "code": 0,
            "message": "ok（含本地 assignment 兜底）" if normalized else "ok（无可用考试任务）",
            "data": {"assignments": normalized},
            "trace_id": uuid.uuid4().hex,
            "request": {"upstreamTried": tried},
        }
    ), 200


@bp.get("/api/exam-center/student/history")
@login_required
def api_exam_student_history():
    uid = str(session.get("user_id") or "").strip()
    if not uid:
        return jsonify({"code": "UNAUTHORIZED", "message": "未登录", "data": None, "trace_id": uuid.uuid4().hex}), 401
    try:
        lim = int(str(request.args.get("limit") or "100"))
    except (TypeError, ValueError):
        lim = 100
    lim = max(1, min(200, lim))
    try:
        offset = int(str(request.args.get("offset") or "0"))
    except (TypeError, ValueError):
        offset = 0
    offset = max(0, offset)
    pass_score = _exam_pass_score()
    base_q = ExamCenterActivity.query.filter_by(user_id=uid)
    total = base_q.count()
    rows = (
        base_q.order_by(ExamCenterActivity.created_at.desc())
        .offset(offset)
        .limit(lim)
        .all()
    )
    ids = [str(r.id) for r in rows if getattr(r, "id", None)]
    det_map: dict[str, ExamCenterActivityDetail] = {}
    if ids:
        ds = ExamCenterActivityDetail.query.filter(ExamCenterActivityDetail.activity_id.in_(ids)).all()
        det_map = {str(d.activity_id): d for d in ds}
    records: list[dict[str, Any]] = []
    for a in rows:
        d = det_map.get(str(a.id))
        mode_l = (a.mode or "").strip().lower()
        mode_label = "练习" if mode_l == "practice" else ("考试" if mode_l == "exam" else (a.mode or "-"))
        tgt = (a.assignment_label or a.set_id or a.attempt_id or "-") or "-"
        records.append(
            {
                "id": a.id,
                "created_at": a.created_at.isoformat() if a.created_at else "",
                "mode": a.mode,
                "mode_label": mode_label,
                "target_label": str(tgt),
                "result": (a.result_summary or "-")[:500],
                "score": d.score if d else None,
                "total_score": d.total_score if d else None,
                "correct_count": d.correct_count if d else None,
                "wrong_count": d.wrong_count if d else None,
                "pass_score": pass_score,
                "passed": (d.score is not None and float(d.score) >= pass_score) if d and d.score is not None else None,
                "weakness": d.weakness if d else None,
                "recommendation": d.recommendation if d else None,
            }
        )
    return jsonify({"code": 0, "message": "ok", "data": {"records": records}, "trace_id": uuid.uuid4().hex}), 200


@bp.post("/api/exam-center/student/exams/start")
@login_required
def api_exam_student_start_exam():
    # 兼容旧前端路径：考试链路已迁移到 aiword 本地，不再调用上游 /quiz/exams/*
    return api_exam_student_start_exam_local()


@bp.post("/api/exam-center/student/exams/submit")
@login_required
def api_exam_student_submit_exam():
    # 兼容旧前端路径：考试链路已迁移到 aiword 本地，不再调用上游 /quiz/exams/*
    return api_exam_student_submit_exam_local()


def _assignment_visible_to_user(*, assignment_id: str, user_id: str) -> bool:
    """若该任务配置了受众，则仅受众可见；未配置受众的历史任务默认可见。"""
    aid = (assignment_id or "").strip()
    uid = (user_id or "").strip()
    if not aid or not uid:
        return False
    try:
        any_rows = ExamCenterAssignmentAudience.query.filter_by(assignment_id=aid).limit(1).all()
        if not any_rows:
            return True
        ok = (
            ExamCenterAssignmentAudience.query.filter_by(assignment_id=aid, user_id=uid)
            .limit(1)
            .all()
        )
        return bool(ok)
    except Exception:
        # 安全兜底：数据库异常时不扩大可见范围
        return False


def _attempt_items_total_score_100(rows: list[ExamAttemptItem]) -> tuple[float, int, int]:
    """总分按 0~100 百分制：每题满分 1，客观题 0/1，主观题使用 0~1 score。"""
    if not rows:
        return 0.0, 0, 0
    total = len(rows)
    score_sum = 0.0
    corr = wrong = 0
    for it in rows:
        if getattr(it, "subjective_needed", False):
            sc = getattr(it, "subjective_score", None)
            if sc is None:
                continue
            try:
                score_sum += max(0.0, min(1.0, float(sc)))
            except Exception:
                pass
        else:
            ic = getattr(it, "is_correct", None)
            if ic is True:
                score_sum += 1.0
                corr += 1
            elif ic is False:
                wrong += 1
    pct = (score_sum / float(total)) * 100.0 if total > 0 else 0.0
    if pct < 0.0:
        pct = 0.0
    if pct > 100.0:
        pct = 100.0
    return pct, corr, wrong


@bp.post("/api/exam-center/student/exams/start-local")
@login_required
def api_exam_student_start_exam_local():
    body = _json_payload()
    assignment_id = (body.get("assignment_id") or body.get("assignmentId") or "").strip()
    if not assignment_id:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 assignment_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    uid = str(session.get("user_id") or "").strip()
    if not uid:
        return jsonify({"code": "UNAUTHORIZED", "message": "未登录", "data": None, "trace_id": uuid.uuid4().hex}), 401
    if not _assignment_visible_to_user(assignment_id=assignment_id, user_id=uid):
        return jsonify({"code": "FORBIDDEN", "message": "无权参加该考试任务", "data": None, "trace_id": uuid.uuid4().hex}), 403

    row = ExamCenterAssignment.query.filter_by(assignment_id=assignment_id).first()
    if not row:
        return jsonify({"code": "NOT_FOUND", "message": "考试任务不存在", "data": None, "trace_id": uuid.uuid4().hex}), 404
    due_at = getattr(row, "due_at", None)
    if due_at and now_local() > due_at:
        return jsonify(
            {
                "code": "OVERDUE",
                "message": "已超过截止完成时间",
                "data": {"due_at": due_at.isoformat(timespec="seconds")},
                "trace_id": uuid.uuid4().hex,
            }
        ), 400
    set_id = str(getattr(row, "set_id", None) or "").strip()
    if not set_id:
        return jsonify({"code": "BAD_REQUEST", "message": "任务缺少 set_id，无法开考", "data": None, "trace_id": uuid.uuid4().hex}), 400

    st_set, pl_set = _quiz_api_call(f"quiz/sets/{_urlquote(set_id, safe='')}", method="GET", query={})
    if not (200 <= int(st_set) < 300) or not isinstance(pl_set, dict):
        return jsonify(pl_set), st_set
    up = _unwrap_quiz_api_success_data(pl_set)
    items = _find_set_item_dicts(up)
    if not items:
        return jsonify({"code": "UPSTREAM_EMPTY_SET", "message": "上游套题明细为空", "data": {"set_id": set_id}, "trace_id": uuid.uuid4().hex}), 502

    attempt_id = uuid.uuid4().hex
    try:
        att = ExamAttempt(
            attempt_id=attempt_id,
            assignment_id=assignment_id,
            user_id=uid,
            exam_track=str(getattr(row, "exam_track", None) or "").strip() or None,
            state="started",
            started_at=now_local(),
        )
        db.session.add(att)
        out_items: list[dict[str, Any]] = []
        for ix, it in enumerate(items):
            if not isinstance(it, dict):
                continue
            qid = _question_id_from_set_item(it) or f"q-{ix}"
            qt = str(it.get("question_type") or it.get("type") or "").strip().lower() or None
            stem = str(it.get("stem") or it.get("title") or "").strip() or None
            opts = it.get("options") if isinstance(it.get("options"), list) else None
            ans = it.get("answer") if "answer" in it else (it.get("correct_answer") if "correct_answer" in it else None)
            # 案例分析题：不展示选项，作答为文本；标准答案不按单选处理（快照置空，避免上游误带 options/answer）
            if qt == "case_analysis":
                opts = None
                ans = None
            # 主观题：无标准答案可立即判分（按用户要求）
            subj = ans is None or (qt is not None and qt not in ("single_choice", "multiple_choice", "true_false"))
            db.session.add(
                ExamAttemptItem(
                    attempt_id=attempt_id,
                    question_id=str(qid),
                    question_type=qt,
                    stem_snapshot=stem,
                    options_snapshot=opts,
                    answer_snapshot={"answer": ans} if ans is not None else None,
                    user_answer=None,
                    is_correct=None,
                    score=None,
                    subjective_needed=bool(subj),
                )
            )
            out_items.append(
                {"question_id": str(qid), "question_type": qt, "stem": stem or "", "options": opts or []}
            )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": "DB_ERROR", "message": str(e), "data": None, "trace_id": uuid.uuid4().hex}), 500

    return jsonify({"code": 0, "message": "ok", "data": {"attempt_id": attempt_id, "assignment_id": assignment_id, "set_id": set_id, "items": out_items}, "trace_id": uuid.uuid4().hex}), 200


@bp.post("/api/exam-center/student/exams/submit-local")
@login_required
def api_exam_student_submit_exam_local():
    body = _json_payload()
    attempt_id = str(body.get("attempt_id") or body.get("attemptId") or "").strip()
    if not attempt_id:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 attempt_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    uid = str(session.get("user_id") or "").strip()
    if not uid:
        return jsonify({"code": "UNAUTHORIZED", "message": "未登录", "data": None, "trace_id": uuid.uuid4().hex}), 401

    att = ExamAttempt.query.filter_by(attempt_id=attempt_id).first()
    if not att or str(att.user_id or "").strip() != uid:
        return jsonify({"code": "NOT_FOUND", "message": "attempt 不存在", "data": None, "trace_id": uuid.uuid4().hex}), 404

    answers = body.get("answers") or body.get("items") or []
    ans_map: dict[str, Any] = {}
    if isinstance(answers, dict):
        ans_map = {str(k).strip(): v for k, v in answers.items() if str(k).strip()}
    elif isinstance(answers, list):
        for r in answers:
            if not isinstance(r, dict):
                continue
            qid = str(r.get("question_id") or r.get("questionId") or "").strip()
            if not qid:
                continue
            if "answer" in r:
                ans_map[qid] = r.get("answer")
            elif "user_answer" in r:
                ans_map[qid] = r.get("user_answer")

    rows = ExamAttemptItem.query.filter_by(attempt_id=attempt_id).all()
    if not rows:
        return jsonify({"code": "BAD_REQUEST", "message": "attempt 无题目明细", "data": None, "trace_id": uuid.uuid4().hex}), 400

    try:
        # 写入作答与客观题判分
        for it in rows:
            qid = str(it.question_id or "").strip()
            if not qid:
                continue
            ua = ans_map.get(qid)
            it.user_answer = {"value": ua} if ua is not None else None
            if not getattr(it, "subjective_needed", False):
                ca = None
                try:
                    ca = (it.answer_snapshot or {}).get("answer") if isinstance(it.answer_snapshot, dict) else None
                except Exception:
                    ca = None
                base_row = {
                    "question_type": it.question_type,
                    "type": it.question_type,
                    "options": it.options_snapshot,
                }
                ok = _objective_answers_equivalent_aiword(base_row, ua, ca)
                it.is_correct = bool(ok)
                it.score = 1.0 if ok else 0.0
            it.updated_at = now_local()

        # 状态与汇总
        att.submitted_at = now_local()
        has_subj = any(bool(getattr(x, "subjective_needed", False)) for x in rows)
        if has_subj:
            att.state = "grading"
        else:
            att.state = "graded"
            sc, corr, wrong = _attempt_items_total_score_100(rows)
            att.score = sc
            att.total_score = 100.0
            att.correct_count = corr
            att.wrong_count = wrong

        db.session.add(att)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": "DB_ERROR", "message": str(e), "data": None, "trace_id": uuid.uuid4().hex}), 500

    # 触发上游整卷主观判分 job（异步）
    if att.state == "grading":
        try:
            subj_items: list[dict[str, Any]] = []
            for it in rows:
                if not getattr(it, "subjective_needed", False):
                    continue
                subj_items.append(
                    {
                        "question_id": it.question_id,
                        "question_type": it.question_type,
                        "stem": it.stem_snapshot,
                        "options": it.options_snapshot or [],
                        "user_answer": (it.user_answer or {}).get("value") if isinstance(it.user_answer, dict) else None,
                    }
                )
            payload = {
                "attempt_id": attempt_id,
                "exam_track": att.exam_track,
                "assignment_id": att.assignment_id,
                "items": subj_items,
            }
            st_g, pl_g = _quiz_api_call("quiz/grading/paper-by-ai", method="POST", payload=payload)
            job_id = ""
            if 200 <= int(st_g) < 300 and isinstance(pl_g, dict):
                root = _unwrap_quiz_api_success_data(pl_g)
                if isinstance(root, dict):
                    inner = root.get("data") if isinstance(root.get("data"), dict) else root
                    job_id = str(inner.get("job_id") or inner.get("jobId") or inner.get("id") or "").strip()
            gj = ExamGradingJob.query.filter_by(attempt_id=attempt_id).first()
            if not gj:
                gj = ExamGradingJob(attempt_id=attempt_id)
            gj.upstream_job_id = job_id or gj.upstream_job_id
            gj.status = "running" if job_id else "failed"
            gj.last_upstream_http_status = int(st_g)
            gj.last_upstream_trace_id = str((pl_g or {}).get("trace_id") or "").strip() if isinstance(pl_g, dict) else None
            gj.last_upstream_payload = pl_g if isinstance(pl_g, dict) else {"data": pl_g}
            gj.last_message = str((pl_g or {}).get("message") or "")[:500] if isinstance(pl_g, dict) else None
            db.session.add(gj)
            db.session.commit()
        except Exception:
            db.session.rollback()

    return jsonify({"code": 0, "message": "ok", "data": {"attempt_id": attempt_id, "state": att.state}, "trace_id": uuid.uuid4().hex}), 200


@bp.get("/api/exam-center/student/attempts/<attempt_id>/grading-status")
@login_required
def api_exam_student_attempt_grading_status_local(attempt_id: str):
    aid = (attempt_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 attempt_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    uid = str(session.get("user_id") or "").strip()
    att = ExamAttempt.query.filter_by(attempt_id=aid).first()
    if not att or str(att.user_id or "").strip() != uid:
        return jsonify({"code": "NOT_FOUND", "message": "attempt 不存在", "data": None, "trace_id": uuid.uuid4().hex}), 404
    gj = ExamGradingJob.query.filter_by(attempt_id=aid).first()
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "attempt_id": aid,
                "state": att.state,
                "score": att.score,
                "total_score": att.total_score,
                "correct_count": att.correct_count,
                "wrong_count": att.wrong_count,
                "job": {
                    "upstream_job_id": gj.upstream_job_id if gj else None,
                    "status": gj.status if gj else None,
                    "last_message": gj.last_message if gj else None,
                }
                if gj
                else None,
            },
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.post("/api/exam-center/student/attempts/<attempt_id>/sync-grading")
@login_required
def api_exam_student_attempt_sync_grading_local(attempt_id: str):
    aid = (attempt_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 attempt_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    uid = str(session.get("user_id") or "").strip()
    att = ExamAttempt.query.filter_by(attempt_id=aid).first()
    if not att or str(att.user_id or "").strip() != uid:
        return jsonify({"code": "NOT_FOUND", "message": "attempt 不存在", "data": None, "trace_id": uuid.uuid4().hex}), 404
    gj = ExamGradingJob.query.filter_by(attempt_id=aid).first()
    if not gj or not str(gj.upstream_job_id or "").strip():
        return jsonify({"code": "NOT_FOUND", "message": "未找到判分任务 job_id", "data": None, "trace_id": uuid.uuid4().hex}), 404

    st, pl = _quiz_api_call(f"quiz/grading/jobs/{_urlquote(str(gj.upstream_job_id), safe='')}", method="GET")
    if isinstance(pl, dict):
        gj.last_upstream_http_status = int(st)
        gj.last_upstream_trace_id = str(pl.get("trace_id") or "").strip() or None
        gj.last_upstream_payload = pl
        gj.last_message = str(pl.get("message") or "")[:500] or None
    try:
        root = _unwrap_quiz_api_success_data(pl) if isinstance(pl, dict) else {}
        inner = root.get("data") if isinstance(root, dict) and isinstance(root.get("data"), dict) else root
        status = str((inner or {}).get("status") or (inner or {}).get("state") or "").strip().lower()
    except Exception:
        inner = {}
        status = ""
    if status in ("done", "success", "completed", "graded", "complete"):
        try:
            items = (inner or {}).get("items") if isinstance(inner, dict) else None
            if not isinstance(items, list):
                items = []
            by_q: dict[str, dict[str, Any]] = {}
            for x in items:
                if not isinstance(x, dict):
                    continue
                qid = str(x.get("question_id") or x.get("questionId") or "").strip()
                if qid:
                    by_q[qid] = x
            rows = ExamAttemptItem.query.filter_by(attempt_id=aid).all()
            for it in rows:
                if not getattr(it, "subjective_needed", False):
                    continue
                qid = str(it.question_id or "").strip()
                x = by_q.get(qid) or {}
                sc = x.get("score")
                try:
                    it.subjective_score = max(0.0, min(1.0, float(sc))) if sc is not None else None
                except Exception:
                    it.subjective_score = None
                it.subjective_reason = str(x.get("reason") or "")[:2000] or None
                it.subjective_recommendation = str(x.get("recommendation") or "")[:2000] or None
                ev = x.get("evidence_used") or x.get("evidenceUsed") or []
                it.evidence_used = ev if isinstance(ev, list) else None
                it.updated_at = now_local()
            sc2, corr2, wrong2 = _attempt_items_total_score_100(rows)
            att.state = "graded"
            att.score = sc2
            att.total_score = 100.0
            att.correct_count = corr2
            att.wrong_count = wrong2
            gj.status = "done"
            db.session.add(att)
            db.session.add(gj)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({"code": "DB_ERROR", "message": str(e), "data": None, "trace_id": uuid.uuid4().hex}), 500
    elif status in ("failed", "error"):
        gj.status = "failed"
        try:
            db.session.add(gj)
            db.session.commit()
        except Exception:
            db.session.rollback()

    return jsonify({"code": 0, "message": "ok", "data": {"attempt_id": aid, "job_status": gj.status, "state": att.state}, "trace_id": uuid.uuid4().hex}), 200


@bp.get("/api/exam-center/student/attempts/<attempt_id>")
@login_required
def api_exam_student_attempt_detail_local(attempt_id: str):
    aid = (attempt_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 attempt_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    uid = str(session.get("user_id") or "").strip()
    att = ExamAttempt.query.filter_by(attempt_id=aid).first()
    if not att or str(att.user_id or "").strip() != uid:
        return jsonify({"code": "NOT_FOUND", "message": "attempt 不存在", "data": None, "trace_id": uuid.uuid4().hex}), 404
    rows = ExamAttemptItem.query.filter_by(attempt_id=aid).all()
    items: list[dict[str, Any]] = []
    for it in rows:
        ua = (it.user_answer or {}).get("value") if isinstance(it.user_answer, dict) else None
        ans = (it.answer_snapshot or {}).get("answer") if isinstance(it.answer_snapshot, dict) else None
        items.append(
            {
                "question_id": it.question_id,
                "question_type": it.question_type,
                "stem": it.stem_snapshot,
                "options": it.options_snapshot or [],
                "user_answer": ua,
                "answer": ans,
                "is_correct": it.is_correct,
                "subjective_needed": bool(it.subjective_needed),
                "subjective_score": it.subjective_score,
                "subjective_reason": it.subjective_reason,
                "subjective_recommendation": it.subjective_recommendation,
                "evidence_used": it.evidence_used if isinstance(it.evidence_used, list) else None,
            }
        )
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "attempt": {
                    "attempt_id": aid,
                    "assignment_id": att.assignment_id,
                    "state": att.state,
                    "exam_track": att.exam_track,
                    "started_at": att.started_at.isoformat(timespec="seconds") if att.started_at else None,
                    "submitted_at": att.submitted_at.isoformat(timespec="seconds") if att.submitted_at else None,
                    "score": att.score,
                    "total_score": att.total_score,
                    "correct_count": att.correct_count,
                    "wrong_count": att.wrong_count,
                },
                "items": items,
            },
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.get("/api/exam-center/activity/<activity_id>")
@_page13_or_login_required
def api_exam_activity_detail(activity_id: str):
    aid = (activity_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 activity_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    row = ExamCenterActivity.query.filter_by(id=aid).first()
    if not row:
        return jsonify({"code": "NOT_FOUND", "message": "记录不存在", "data": None, "trace_id": uuid.uuid4().hex}), 404
    # 学生仅可看自己的记录；老师/统计（page13 通过）可看全部
    if not session.get("page13_authenticated"):
        uid = str(session.get("user_id") or "").strip()
        if not uid or uid != str(row.user_id or ""):
            return jsonify({"code": "FORBIDDEN", "message": "无权查看该记录", "data": None, "trace_id": uuid.uuid4().hex}), 403
    det = ExamCenterActivityDetail.query.filter_by(activity_id=aid).first()
    pass_score = _exam_pass_score()
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "activity": {
                    "id": row.id,
                    "created_at": row.created_at.isoformat() if row.created_at else "",
                    "user_id": row.user_id,
                    "username": row.username,
                    "display_name": row.display_name,
                    "mode": row.mode,
                    "exam_track": row.exam_track,
                    "set_id": row.set_id,
                    "assignment_id": row.assignment_id,
                    "assignment_label": row.assignment_label,
                    "attempt_id": row.attempt_id,
                    "result_summary": row.result_summary,
                },
                "detail": {
                    "score": det.score if det else None,
                    "total_score": det.total_score if det else None,
                    "correct_count": det.correct_count if det else None,
                    "wrong_count": det.wrong_count if det else None,
                    "pass_score": pass_score,
                    "passed": (det.score is not None and float(det.score) >= pass_score) if det and det.score is not None else None,
                    "weakness": det.weakness if det else None,
                    "recommendation": det.recommendation if det else None,
                    "upstream_payload": det.upstream_payload if det else None,
                },
                # attempt_items 改为异步拉取：避免详情接口阻塞导致弹窗长时间“加载中…”
                "attempt_items": None,
            },
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.get("/api/exam-center/activity/<activity_id>/attempt-items")
@_page13_or_login_required
def api_exam_activity_attempt_items(activity_id: str):
    """异步拉取答题明细：前端弹窗先展示基础信息，再调用本接口补全题目对错/答案等。"""
    aid = (activity_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 activity_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    row = ExamCenterActivity.query.filter_by(id=aid).first()
    if not row:
        return jsonify({"code": "NOT_FOUND", "message": "记录不存在", "data": None, "trace_id": uuid.uuid4().hex}), 404
    # 学生仅可看自己的记录；老师/统计可看全部
    if not session.get("page13_authenticated"):
        uid = str(session.get("user_id") or "").strip()
        if not uid or uid != str(row.user_id or ""):
            return jsonify({"code": "FORBIDDEN", "message": "无权查看该记录", "data": None, "trace_id": uuid.uuid4().hex}), 403
    att_id = str(row.attempt_id or "").strip()
    if not att_id:
        return jsonify({"code": 0, "message": "ok（无 attempt_id）", "data": {"items": []}, "trace_id": uuid.uuid4().hex}), 200

    det_snap = ExamCenterActivityDetail.query.filter_by(activity_id=aid).first()
    st, pl = _quiz_api_call(
        f"quiz/attempts/{att_id}/answers",
        method="GET",
        query=request.args.to_dict(),
        timeout_seconds=_quiz_attempt_answers_quick_timeout_seconds(),
    )
    if 200 <= int(st) < 300 and isinstance(pl, dict):
        root = pl.get("data") if isinstance(pl.get("data"), dict) else None
        if isinstance(root, dict) and isinstance(root.get("data"), dict):
            root = root.get("data")
        items = root.get("items") if isinstance(root, dict) else None
        if not isinstance(items, list):
            items = []
        return jsonify({"code": 0, "message": "ok", "data": {"items": items}, "trace_id": uuid.uuid4().hex}), 200

    fb = _items_from_activity_detail_snapshot(det_snap)
    if fb:
        return jsonify(
            {
                "code": 0,
                "message": "ok（上游明细不可用，已降级为本地提交快照）",
                "data": {"items": fb},
                "trace_id": uuid.uuid4().hex,
                "request": {"url": "", "method": "GET", "upstreamPath": f"quiz/attempts/{att_id}/answers → snapshot"},
            }
        ), 200
    return jsonify({"code": "UPSTREAM_ERROR", "message": "上游明细不可用", "data": pl, "trace_id": uuid.uuid4().hex}), 502


@bp.get("/api/exam-center/stats/mode")
@page13_access_required
def api_exam_stats_mode():
    """按考试/练习维度的统计（本地聚合），用于第三块看板。"""
    mode = str(request.args.get("mode") or "").strip().lower()
    if mode not in {"exam", "practice"}:
        return jsonify({"code": "BAD_REQUEST", "message": "mode 仅支持 exam/practice", "data": None, "trace_id": uuid.uuid4().hex}), 400
    pass_score = _exam_pass_score()
    rows = ExamCenterActivity.query.filter_by(mode=mode).order_by(ExamCenterActivity.created_at.desc()).all()
    ids = [str(r.id) for r in rows if getattr(r, "id", None)]
    det_map: dict[str, ExamCenterActivityDetail] = {}
    if ids:
        ds = ExamCenterActivityDetail.query.filter(ExamCenterActivityDetail.activity_id.in_(ids)).all()
        det_map = {str(d.activity_id): d for d in ds}
    pass_count = 0
    fail_count = 0
    graded = 0
    for r in rows:
        d = det_map.get(str(r.id))
        if not d or d.score is None:
            continue
        graded += 1
        if float(d.score) >= pass_score:
            pass_count += 1
        else:
            fail_count += 1
    pass_rate = round((pass_count * 100.0 / graded), 2) if graded > 0 else None
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "mode": mode,
                "total_count": len(rows),
                "graded_count": graded,
                "pass_score": pass_score,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "pass_rate_percent": pass_rate,
            },
            "trace_id": uuid.uuid4().hex,
        }
    ), 200


@bp.delete("/api/exam-center/activity/<activity_id>")
@page13_access_required
def api_exam_activity_delete(activity_id: str):
    """老师端删除学生练习/考试记录（同时删除明细快照）。"""
    aid = (activity_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 activity_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    row = ExamCenterActivity.query.filter_by(id=aid).first()
    if not row:
        return jsonify({"code": "NOT_FOUND", "message": "记录不存在", "data": None, "trace_id": uuid.uuid4().hex}), 404
    try:
        ExamCenterActivityDetail.query.filter_by(activity_id=aid).delete()
        ExamCenterActivity.query.filter_by(id=aid).delete()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"code": "DB_ERROR", "message": f"删除失败：{e}", "data": None, "trace_id": uuid.uuid4().hex}), 500
    return jsonify({"code": 0, "message": "ok", "data": {"deleted": 1, "activity_id": aid}, "trace_id": uuid.uuid4().hex}), 200


@bp.get("/api/exam-center/stats/overview")
@page13_access_required
def api_exam_stats_overview():
    local = _local_stats_overview_all()
    return jsonify(
        {
            "code": 0,
            "message": "ok（本地统计）",
            "data": local,
            "trace_id": uuid.uuid4().hex,
            "request": {"url": "", "method": "GET", "upstreamPath": "local aggregate"},
        }
    ), 200


@bp.get("/api/exam-center/stats/student/<student_id>")
@page13_access_required
def api_exam_stats_student(student_id: str):
    local = _local_stats_for_student(student_id)
    return jsonify(
        {
            "code": 0,
            "message": "ok（本地统计）",
            "data": local,
            "trace_id": uuid.uuid4().hex,
            "request": {"url": "", "method": "GET", "upstreamPath": "local aggregate"},
        }
    ), 200


@bp.get("/api/exam-center/stats/students")
@page13_access_required
def api_exam_stats_students():
    """按学生多维统计表格（本地聚合）。供统计看板一次展示全部学生。"""
    rows = _local_stats_all_students_rows()
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "rows": rows,
                "pass_score": _exam_pass_score(),
                "count": len(rows),
            },
            "trace_id": uuid.uuid4().hex,
            "request": {"url": "", "method": "GET", "upstreamPath": "local aggregate → exam_center_activities"},
        }
    ), 200


@bp.get("/api/exam-center/stats/students-by-mode")
@bp.get("/api/exam-center/stats/students_by_mode")
@page13_access_required
def api_exam_stats_students_by_mode():
    """按学生 × 考试/练习 分组统计（本地聚合）。"""
    rows = _local_stats_rows_student_by_mode()
    return jsonify(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "rows": rows,
                "pass_score": _exam_pass_score(),
                "count": len(rows),
            },
            "trace_id": uuid.uuid4().hex,
            "request": {"url": "", "method": "GET", "upstreamPath": "local aggregate student×mode → exam_center_activities"},
        }
    ), 200


@bp.get("/api/exam-center/stats/exam/<assignment_id>")
@page13_access_required
def api_exam_stats_exam(assignment_id: str):
    aid = str(assignment_id or "").strip()
    if not aid:
        return jsonify({"code": "BAD_REQUEST", "message": "缺少 assignment_id", "data": None, "trace_id": uuid.uuid4().hex}), 400
    rows = ExamCenterActivity.query.filter_by(assignment_id=aid).order_by(ExamCenterActivity.created_at.desc()).all()
    ids = [str(r.id) for r in rows if getattr(r, "id", None)]
    det_map: dict[str, ExamCenterActivityDetail] = {}
    if ids:
        ds = ExamCenterActivityDetail.query.filter(ExamCenterActivityDetail.activity_id.in_(ids)).all()
        det_map = {str(d.activity_id): d for d in ds}
    pass_score = _exam_pass_score()
    pass_count = 0
    fail_count = 0
    submitted = 0
    by_student: dict[str, dict[str, Any]] = {}
    for r in rows:
        uid = str(r.user_id or "").strip()
        d = det_map.get(str(r.id))
        submitted += 1
        if d and d.score is not None:
            if float(d.score) >= pass_score:
                pass_count += 1
            else:
                fail_count += 1
        if uid and uid not in by_student:
            by_student[uid] = _local_stats_for_student(uid)
    graded = pass_count + fail_count
    pass_rate = round((pass_count * 100.0 / graded), 2) if graded > 0 else None
    assign_row = ExamCenterAssignment.query.filter_by(assignment_id=aid).first()
    due_end = getattr(assign_row, "due_at", None) if assign_row else None
    deadline_completion = _deadline_completion_from_exam_rows(rows, due_end)
    return jsonify(
        {
            "code": 0,
            "message": "ok（本地统计兜底）",
            "data": {
                "assignment_id": aid,
                "submitted_count": submitted,
                "graded_count": graded,
                "pass_score": pass_score,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "pass_rate_percent": pass_rate,
                "students": list(by_student.values()),
                "deadline_completion": deadline_completion,
            },
            "trace_id": uuid.uuid4().hex,
            "request": {"url": "", "method": "GET", "upstreamPath": "local aggregate"},
        }
    ), 200


@bp.get("/api/exam-center/health")
def api_exam_center_health():
    """
    用于排查上游连通性：优先请求 /health；若上游没有该路径，会返回上游错误信息。
    """
    # 不要用 3s 硬超时：本机/Windows/反代首次握手或 API 冷启动时容易误判超时；
    # 与 QUIZ_API_TIMEOUT_SECONDS 对齐，但健康检查仍限制上限，避免按钮长时间无反馈。
    cfg = _quiz_api_timeout_seconds()
    health_timeout = min(15, max(8, cfg))
    status, payload = _quiz_api_call(
        "health",
        method="GET",
        query=request.args.to_dict(),
        timeout_seconds=health_timeout,
    )
    return jsonify(payload), status


# ---------- 用户管理 API（页面1管理账号） ----------

@bp.get("/api/users")
@page13_access_required
def api_users_list():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({
        "users": [
            {
                "id": u.id,
                "username": u.username,
                "displayName": u.display_name,
                "mobile": getattr(u, "mobile", None) or None,
                "createdAt": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ]
    })


@bp.post("/api/users")
@page13_access_required
def api_users_create():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    display_name = (data.get("displayName") or "").strip() or None
    mobile = (data.get("mobile") or "").strip() or None
    if not username or not password:
        return jsonify({"message": "用户名和密码不能为空"}), 400
    existing = User.query.filter_by(username=username).first()
    if existing:
        return jsonify({"message": "用户名已存在"}), 409
    user = User(username=username, display_name=display_name, mobile=mobile)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({
        "message": "用户创建成功",
        "user": {
            "id": user.id,
            "username": user.username,
            "displayName": user.display_name,
            "mobile": user.mobile,
        },
    })


@bp.patch("/api/users/<user_id>")
@page13_access_required
def api_users_update(user_id: str):
    """更新用户显示名称、手机号（钉钉 @ 用）"""
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "用户不存在"}), 404
    data = request.get_json(force=True) or {}
    if "displayName" in data:
        user.display_name = (data["displayName"] or "").strip() or None
    if "mobile" in data:
        user.mobile = (data["mobile"] or "").strip() or None
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "已更新", "user": {"id": user.id, "username": user.username, "displayName": user.display_name, "mobile": user.mobile}})


@bp.delete("/api/users/<user_id>")
@page13_access_required
def api_users_delete(user_id: str):
    user = User.query.get(user_id)
    if not user:
        return jsonify({"message": "用户不存在"}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify({"message": "用户已删除"})


# ---------- 配置项 API ----------

@bp.get("/api/configs/task-types")
@_page13_or_login_required
def api_task_types():
    """获取任务类型配置列表"""
    items = TaskTypeConfig.query.filter_by(is_active=True).order_by(TaskTypeConfig.sort_order).all()
    return jsonify({
        "taskTypes": [{"id": t.id, "name": t.name} for t in items]
    })


@bp.post("/api/configs/task-types")
@page13_access_required
def api_task_types_create():
    """新增任务类型"""
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "名称不能为空"}), 400
    existing = TaskTypeConfig.query.filter_by(name=name).first()
    if existing:
        return jsonify({"message": "该类型已存在"}), 409
    max_order = db.session.query(db.func.max(TaskTypeConfig.sort_order)).scalar() or 0
    item = TaskTypeConfig(name=name, sort_order=max_order + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify({"message": "创建成功", "id": item.id, "name": item.name})


@bp.delete("/api/configs/task-types/<item_id>")
@page13_access_required
def api_task_types_delete(item_id: str):
    """删除任务类型"""
    item = TaskTypeConfig.query.get(item_id)
    if not item:
        return jsonify({"message": "不存在"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "已删除"})


@bp.get("/api/configs/completion-statuses")
@_page13_or_login_required
def api_completion_statuses():
    """获取完成状态配置列表"""
    items = CompletionStatusConfig.query.filter_by(is_active=True).order_by(CompletionStatusConfig.sort_order).all()
    return jsonify({
        "completionStatuses": [{"id": s.id, "name": s.name} for s in items]
    })


@bp.post("/api/configs/completion-statuses")
@page13_access_required
def api_completion_statuses_create():
    """新增完成状态"""
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "名称不能为空"}), 400
    existing = CompletionStatusConfig.query.filter_by(name=name).first()
    if existing:
        return jsonify({"message": "该状态已存在"}), 409
    max_order = db.session.query(db.func.max(CompletionStatusConfig.sort_order)).scalar() or 0
    item = CompletionStatusConfig(name=name, sort_order=max_order + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify({"message": "创建成功", "id": item.id, "name": item.name})


@bp.delete("/api/configs/completion-statuses/<item_id>")
@page13_access_required
def api_completion_statuses_delete(item_id: str):
    """删除完成状态"""
    item = CompletionStatusConfig.query.get(item_id)
    if not item:
        return jsonify({"message": "不存在"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "已删除"})


@bp.get("/api/configs/audit-statuses")
@_page13_or_login_required
def api_audit_statuses():
    """获取审核状态配置列表（页面1使用）"""
    items = AuditStatusConfig.query.filter_by(is_active=True).order_by(AuditStatusConfig.sort_order).all()
    return jsonify({
        "auditStatuses": [{"id": s.id, "name": s.name} for s in items]
    })


@bp.post("/api/configs/audit-statuses")
@page13_access_required
def api_audit_statuses_create():
    """新增审核状态"""
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "名称不能为空"}), 400
    existing = AuditStatusConfig.query.filter_by(name=name).first()
    if existing:
        return jsonify({"message": "该状态已存在"}), 409
    max_order = db.session.query(db.func.max(AuditStatusConfig.sort_order)).scalar() or 0
    item = AuditStatusConfig(name=name, sort_order=max_order + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify({"message": "创建成功", "id": item.id, "name": item.name})


@bp.delete("/api/configs/audit-statuses/<item_id>")
@page13_access_required
def api_audit_statuses_delete(item_id: str):
    """删除审核状态"""
    item = AuditStatusConfig.query.get(item_id)
    if not item:
        return jsonify({"message": "不存在"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "已删除"})


# ---------- 上传与任务管理 API ----------

@bp.post("/api/upload")
@page13_access_required
def api_upload():
    project_id = (request.form.get("projectId") or "").strip() or None
    project_name = request.form.get("projectName", "").strip()
    project_code = request.form.get("projectCode", "").strip() or None
    file_name = request.form.get("fileName", "").strip()
    task_type = request.form.get("taskType", "").strip() or None
    author = request.form.get("author", "").strip()
    notes = request.form.get("notes", "").strip() or None
    project_notes = request.form.get("projectNotes", "").strip() or None
    replace = str(request.form.get("replace", "")).strip().lower() in ("true", "1", "yes")
    file = request.files.get("file")
    template_links_raw = request.form.get("templateLinks")
    template_links = (
        (template_links_raw or "").strip() or None
        if template_links_raw is not None
        else None
    )
    if template_links:
        template_links = _normalize_template_links(template_links) or None
    assignee_name = request.form.get("assigneeName", "").strip() or None
    due_date_str = request.form.get("dueDate", "").strip() or None
    business_side = request.form.get("businessSide", "").strip() or None
    product = request.form.get("product", "").strip() or None
    country = request.form.get("country", "").strip() or None
    registered_product_name = request.form.get("registeredProductName", "").strip() or None
    model = request.form.get("model", "").strip() or None
    registration_version = request.form.get("registrationVersion", "").strip() or None
    file_version = request.form.get("fileVersion", "").strip() or None
    document_display_date_str = request.form.get("documentDisplayDate", "").strip() or None
    reviewer = request.form.get("reviewer", "").strip() or None
    approver = request.form.get("approver", "").strip() or None
    belonging_module = request.form.get("belongingModule", "").strip() or None
    displayed_author = request.form.get("displayedAuthor", "").strip() or None

    if not project_name or not file_name or not author:
        return (
            jsonify({"message": "项目名称、文件名称、编写人员为必填项。"}),
            400,
        )
    # 链接和文件均可为空保存，后续可在页面2补充链接

    # 确保项目元数据存在（默认：中优先级/进行中）
    if project_id:
        p = Project.query.get(project_id)
        if p:
            project_name = _project_display_label(p)
        else:
            project_id = None
    _ensure_project_row(project_name)

    existing = UploadRecord.query.filter_by(
        project_name=project_name, file_name=file_name, task_type=task_type, author=author
    ).first()

    if existing and not replace:
        return (
            jsonify(
                {
                    "message": f"存在同名项目+文件+类型+编写人({task_type or '无'}/{author})，是否需要替换原有内容？",
                    "needsConfirmation": True,
                }
            ),
            409,
        )

    uploads_dir = Path(current_app.config["UPLOAD_FOLDER"])
    stored_file_name = None
    storage_path = None
    original_file_name = None
    placeholders = []
    template_file_blob = None

    if file and file.filename:
        stored_file_name, storage_path = _save_file(file, uploads_dir)
        original_file_name = file.filename
        try:
            placeholders = extract_placeholders(storage_path)
            template_file_blob = Path(storage_path).read_bytes()
        except Exception as exc:
            Path(storage_path).unlink(missing_ok=True)
            return jsonify({"message": f"解析模板失败：{exc}"}), 400
        Path(storage_path).unlink(missing_ok=True)
        storage_path = None
    elif template_links:
        links = [line.strip() for line in template_links.split("\n") if line.strip()]
        if links:
            first_link = links[0].lower()
            is_direct_docx = first_link.endswith('.docx') or first_link.endswith('.doc')
            if is_direct_docx:
                try:
                    temp_path = uploads_dir / f"temp_{now_local().strftime('%Y%m%d%H%M%S%f')}.docx"
                    download_template_from_url(links[0], str(temp_path))
                    placeholders = extract_placeholders(str(temp_path))
                    temp_path.unlink(missing_ok=True)
                except Exception as exc:
                    temp_path.unlink(missing_ok=True) if 'temp_path' in dir() else None
                    return jsonify({"message": f"下载或解析模板链接失败：{exc}"}), 400

    due_date = None
    if due_date_str:
        try:
            due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"message": "截止日期格式应为 YYYY-MM-DD"}), 400
    document_display_date = None
    if document_display_date_str:
        try:
            document_display_date = datetime.strptime(document_display_date_str, "%Y-%m-%d").date()
        except ValueError:
            document_display_date = None

    if existing and replace:
        fm = request.form
        # 批量保存第二次请求（replace=true）常为「只 append 非空字段」；未出现的键不得写成 None，否则会误清空库内已有数据。
        def _sent(k: str) -> bool:
            return k in fm

        (uploads_dir / f"_dbtpl_{existing.id}.docx").unlink(missing_ok=True)
        if existing.storage_path:
            previous_path = Path(existing.storage_path)
            if previous_path.exists():
                previous_path.unlink()

        if file and file.filename:
            existing.template_file_blob = template_file_blob
            existing.stored_file_name = stored_file_name
            existing.storage_path = None
            existing.original_file_name = original_file_name
        else:
            existing.stored_file_name = stored_file_name or existing.stored_file_name
            existing.storage_path = storage_path if storage_path else existing.storage_path
            existing.original_file_name = original_file_name or existing.original_file_name

        if _sent("templateLinks"):
            existing.template_links = template_links
        existing.author = author
        if _sent("taskType"):
            existing.task_type = task_type
        if _sent("notes"):
            existing.notes = notes
        if _sent("projectNotes"):
            existing.project_notes = project_notes
        existing.project_name = project_name
        existing.project_id = project_id
        existing.file_name = file_name
        if (file and file.filename) or placeholders:
            existing.placeholders = placeholders
        if _sent("assigneeName"):
            existing.assignee_name = assignee_name
        if _sent("dueDate"):
            existing.due_date = due_date
        existing.task_status = "pending"
        existing.completion_status = None
        existing.quick_completed = False
        if _sent("businessSide"):
            existing.business_side = business_side
        if _sent("product"):
            existing.product = product
        if _sent("country"):
            existing.country = country
        if _sent("projectCode"):
            existing.project_code = project_code
        if _sent("fileVersion"):
            existing.file_version = file_version
        if _sent("documentDisplayDate"):
            existing.document_display_date = document_display_date
        if _sent("reviewer"):
            existing.reviewer = reviewer
        if _sent("approver"):
            existing.approver = approver
        if _sent("belongingModule"):
            existing.belonging_module = belonging_module
        if _sent("displayedAuthor"):
            existing.displayed_author = displayed_author
        if _sent("registeredProductName"):
            existing.registered_product_name = registered_product_name
        if _sent("model"):
            existing.model = model
        if _sent("registrationVersion"):
            existing.registration_version = registration_version
        summary = _prepare_summary(existing)
        summary.project_name = project_name
        summary.project_id = project_id
        summary.file_name = file_name
        summary.author = author
        summary.has_generated = False
        summary.total_generate_clicks = 0
        summary.last_generated_at = None
        db.session.add(existing)
        db.session.commit()

        try:
            _send_task_notification(existing, due_date_str)
        except Exception as exc:
            current_app.logger.warning("替换任务后发送钉钉通知失败（数据已保存）: %s", exc)

        ph_out = existing.placeholders if isinstance(existing.placeholders, list) else (placeholders or [])
        return jsonify(
            {
                "message": "已替换现有记录，状态已重置为待办。",
                "record": {
                    "id": existing.id,
                    "projectName": existing.project_name,
                    "fileName": existing.file_name,
                    "taskType": existing.task_type,
                    "author": existing.author,
                    "placeholders": ph_out,
                    "assigneeName": existing.assignee_name,
                    "dueDate": due_date_str,
                    "businessSide": existing.business_side,
                    "product": existing.product,
                    "country": existing.country,
                    "registeredProductName": getattr(existing, "registered_product_name", None),
                    "model": getattr(existing, "model", None),
                    "registrationVersion": getattr(existing, "registration_version", None),
                },
            }
        )

    upload = UploadRecord(
        project_id=project_id,
        project_name=project_name,
        project_code=project_code,
        file_name=file_name,
        task_type=task_type,
        author=author,
        stored_file_name=stored_file_name,
        storage_path=storage_path,
        template_file_blob=template_file_blob,
        original_file_name=original_file_name,
        template_links=template_links,
        notes=notes,
        project_notes=project_notes,
        placeholders=placeholders,
        assignee_name=assignee_name,
        due_date=due_date,
        business_side=business_side,
        product=product,
        country=country,
        registered_product_name=registered_product_name,
        model=model,
        registration_version=registration_version,
        file_version=file_version,
        document_display_date=document_display_date,
        reviewer=reviewer,
        approver=approver,
        belonging_module=belonging_module,
        displayed_author=displayed_author,
    )
    db.session.add(upload)
    summary = _prepare_summary(upload)
    summary.project_id = project_id
    db.session.add(summary)
    db.session.commit()

    try:
        _send_task_notification(upload, due_date_str)
    except Exception as exc:
        current_app.logger.warning("新建任务后发送钉钉通知失败（数据已保存）: %s", exc)

    return jsonify(
        {
            "message": "上传信息已保存。",
            "record": {
                "id": upload.id,
                "projectName": upload.project_name,
                "fileName": upload.file_name,
                "taskType": upload.task_type,
                "author": upload.author,
                "placeholders": placeholders,
                "assigneeName": upload.assignee_name,
                "dueDate": due_date_str,
                "businessSide": upload.business_side,
                "product": upload.product,
                "country": upload.country,
                "registeredProductName": getattr(upload, "registered_product_name", None),
                "model": getattr(upload, "model", None),
                "registrationVersion": getattr(upload, "registration_version", None),
            },
        }
    )


def _send_task_notification(upload: UploadRecord, due_date_str: str):
    """如果设置了负责人，发送钉钉通知"""
    if not upload.assignee_name:
        return
    webhook = _dingtalk_webhook_str() or None
    secret = _dingtalk_secret_opt()
    template_source = (
        "已上传文件"
        if (upload.template_file_blob or upload.storage_path)
        else f"链接({len(upload.get_template_links_list())}个)"
    )
    sent = dingtalk_service.notify_task_assigned(
        upload.assignee_name,
        f"{upload.project_name} - {upload.file_name}",
        due_date_str or "未设置",
        template_source,
        webhook=webhook,
        secret=secret,
    )
    if sent:
        upload.dingtalk_notified_at = now_local()
        db.session.add(upload)
        db.session.commit()


# 待办导入：表头与任务字段映射（支持另一工具导出 CSV/Excel）
_IMPORT_HEADER_MAP = {
    "项目名称": "project_name",
    "项目编号": "project_code",
    "影响业务方": "business_side",
    "产品": "product",
    "影响产品": "product",
    "国家": "country",
    "项目备注": "project_notes",
    "注册产品名称": "registered_product_name",
    "型号": "model",
    "注册版本号": "registration_version",
    "文件名称": "fileName",
    "任务类型": "task_type",
    "类型": "task_type",
    "任务类别": "task_type",
    "task_type": "task_type",
    "文档链接": "template_links",
    "文件版本号": "file_version",
    "编写人员": "author",
    "负责人": "assignee_name",
    "截止日期": "due_date",
    "下发任务备注": "notes",
    "文档体现日期": "document_display_date",
    "审核人员": "reviewer",
    "批准人员": "approver",
    "所属模块": "belonging_module",
    "体现编写人员": "displayed_author",
    "projectName": "project_name",
    "projectCode": "project_code",
    "businessSide": "business_side",
    "product": "product",
    "country": "country",
    "projectNotes": "project_notes",
    "fileName": "fileName",
    "taskType": "task_type",
    "templateLinks": "template_links",
    "fileVersion": "file_version",
    "author": "author",
    "assigneeName": "assignee_name",
    "dueDate": "due_date",
    "notes": "notes",
    "documentDisplayDate": "document_display_date",
    "reviewer": "reviewer",
    "approver": "approver",
    "belongingModule": "belonging_module",
    "displayedAuthor": "displayed_author",
    "registeredProductName": "registered_product_name",
    "model": "model",
    "registrationVersion": "registration_version",
}


def _decode_import_csv_bytes(raw_bytes: bytes) -> str:
    """
    Excel「另存为 CSV」在中文 Windows 上常为 GBK/GB18030；仅用 UTF-8 会导致乱码或列错位，
    进而「文件名称」等列解析错误甚至整行被跳过。
    """
    if not raw_bytes:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def _parse_import_file(file_storage) -> tuple[list[dict], str]:
    """解析上传的 CSV 或 Excel，返回 (rows, error)。rows 每项为字段名->值的字典。"""
    if not file_storage or not file_storage.filename:
        return [], "请选择文件"
    fn = (file_storage.filename or "").lower()
    file_storage.stream.seek(0)
    raw_bytes = file_storage.stream.read()
    if fn.endswith(".csv"):
        if isinstance(raw_bytes, bytes):
            raw = _decode_import_csv_bytes(raw_bytes)
        else:
            raw = str(raw_bytes)
        return _parse_import_csv(raw)
    if fn.endswith(".xlsx") or fn.endswith(".xls"):
        return _parse_import_excel(raw_bytes, fn)
    return [], "仅支持 .csv 或 .xlsx 文件"


def _parse_import_csv(raw: str) -> tuple[list[dict], str]:
    reader = csv.reader(io.StringIO(raw))
    rows = list(reader)
    if not rows:
        return [], "文件为空"
    headers = [h.strip() for h in rows[0]]
    out = []
    for i, row in enumerate(rows[1:], start=2):
        if not row or all(not (c or "").strip() for c in row):
            continue
        d = {}
        for j, h in enumerate(headers):
            if j < len(row):
                val = (row[j] or "").strip()
                key = _IMPORT_HEADER_MAP.get(h) or _IMPORT_HEADER_MAP.get(h.strip())
                if key:
                    d[key] = val
        out.append(d)
    return out, ""


def _parse_import_excel(raw: bytes, filename: str) -> tuple[list[dict], str]:
    try:
        import openpyxl
    except ImportError:
        return [], "请安装 openpyxl 以支持 Excel 导入：pip install openpyxl"
    if not isinstance(raw, bytes):
        raw = raw.encode("utf-8") if isinstance(raw, str) else b""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        if not ws:
            return [], "Excel 无有效工作表"
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
    except Exception as e:
        return [], f"Excel 解析失败：{e}"
    if not rows:
        return [], "文件为空"
    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    out = []
    for row in rows[1:]:
        if not row or all(v is None or (str(v).strip() == "") for v in row):
            continue
        d = {}
        for j, h in enumerate(headers):
            if j < len(row):
                val = row[j]
                val = (str(val).strip() if val is not None else "") or ""
                key = _IMPORT_HEADER_MAP.get(h) or _IMPORT_HEADER_MAP.get(h.strip())
                if key:
                    d[key] = val
        out.append(d)
    return out, ""


def _parse_import_date(s: str) -> Optional[date]:
    if not s or not (s or "").strip():
        return None
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# 导入模板表头（与任务录入/列表一致：先项目与文档通用信息，再文件任务与签审批信息）
_IMPORT_TEMPLATE_HEADERS = [
    "项目名称", "项目编号", "影响业务方", "影响产品", "国家", "项目备注", "注册产品名称", "型号", "注册版本号",
    "文件名称", "任务类型", "所属模块", "文档链接", "文件版本号", "文档体现日期", "审核人员", "批准人员", "体现编写人员",
    "编写人员", "负责人", "截止日期", "下发任务备注",
]


def _format_date_for_import(obj) -> str:
    """安全格式化为 YYYY-MM-DD，避免非 date/datetime 导致异常。"""
    if obj is None:
        return ""
    if hasattr(obj, "strftime"):
        try:
            return obj.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return ""
    return str(obj)[:10] if obj else ""


def _record_to_import_row(r: UploadRecord) -> list:
    """与 _IMPORT_TEMPLATE_HEADERS 列顺序一致"""
    return [
        (r.project_name or ""),
        (r.project_code or ""),
        (r.business_side or ""),
        (r.product or ""),
        (r.country or ""),
        (r.project_notes or ""),
        str(getattr(r, "registered_product_name", None) or ""),
        str(getattr(r, "model", None) or ""),
        str(getattr(r, "registration_version", None) or ""),
        (r.file_name or ""),
        (r.task_type or ""),
        str(getattr(r, "belonging_module", None) or ""),
        (r.template_links or "").replace("\n", " ").strip(),
        str(getattr(r, "file_version", None) or ""),
        _format_date_for_import(getattr(r, "document_display_date", None)),
        str(getattr(r, "reviewer", None) or ""),
        str(getattr(r, "approver", None) or ""),
        str(getattr(r, "displayed_author", None) or ""),
        (r.author or ""),
        (r.assignee_name or r.author or ""),
        _format_date_for_import(r.due_date),
        (r.notes or ""),
    ]


def _build_import_template_csv(include_sample: bool, project_name: Optional[str] = None) -> str:
    """生成导入用 CSV。include_sample=True 时填充数据行；project_name 指定时填充该项目下所有任务，否则一行示例或占位。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_IMPORT_TEMPLATE_HEADERS)
    if include_sample:
        if project_name and (project_name or "").strip():
            records = (
                UploadRecord.query.filter(UploadRecord.project_name == project_name.strip())
                .order_by(UploadRecord.sort_order.asc(), UploadRecord.created_at.asc())
                .all()
            )
            for r in records:
                writer.writerow(_record_to_import_row(r))
        else:
            sample = UploadRecord.query.order_by(UploadRecord.created_at.desc()).first()
            if sample:
                writer.writerow(_record_to_import_row(sample))
            else:
                writer.writerow([
                    "示例项目", "PRJ001", "示例业务方", "示例产品", "中国", "项目备注示例", "注册产品示例", "型号示例", "V1.0",
                    "示例文件", "初稿待编写", "开发", "https://example.com/doc.docx", "V1.0",
                    datetime.now().strftime("%Y-%m-%d"), "审核人", "批准人", "体现编写人",
                    "张三", "张三", datetime.now().strftime("%Y-%m-%d"), "下发任务备注示例",
                ])
    return buf.getvalue()


@bp.get("/api/uploads/project-names")
@page13_access_required
def api_uploads_project_names():
    """返回已有项目名称列表，用于示例模板选择项目。"""
    include_history = str(request.args.get("includeHistory") or "").strip() in ("1", "true", "True", "yes", "on")
    proj_meta = _project_meta_map(auto_create_from_uploads=True)
    ended = {n for n, m in proj_meta.items() if (m.get("status") or "").strip().lower() == Project.STATUS_ENDED}

    names = (
        db.session.query(UploadRecord.project_name)
        .filter(UploadRecord.project_name.isnot(None), UploadRecord.project_name != "")
        .distinct()
        .all()
    )
    arr = [n[0] for n in names if (n[0] or "").strip()]
    if (not include_history) and ended:
        arr = [n for n in arr if n not in ended]

    def _k(n: str):
        m = proj_meta.get(n) or {}
        st = (m.get("status") or Project.STATUS_ACTIVE).strip().lower()
        pr = int(m.get("priority") or Project.PRIORITY_MEDIUM)
        return (1 if st == Project.STATUS_ENDED else 0, -pr, n or "")

    arr = sorted(set(arr), key=_k)
    return jsonify({"projectNames": arr})


@bp.get("/api/uploads/import-template")
@page13_access_required
def api_uploads_import_template():
    """下载导入模板：type=empty 仅表头；type=with_sample 可带 project_name 填充该项目下所有任务。"""
    try:
        template_type = (request.args.get("type") or "empty").strip().lower()
        include_sample = template_type in ("with_sample", "sample", "1", "true")
        project_name = (request.args.get("project_name") or "").strip() or None
        content = _build_import_template_csv(include_sample=include_sample, project_name=project_name)
        if include_sample and project_name:
            safe_name = "".join(c for c in project_name[:20] if c.isalnum() or c in " _-")
            filename = f"待办导入模板_{safe_name}.csv"
        else:
            filename = "待办导入模板_含示例.csv" if include_sample else "待办导入模板_空.csv"
        body = content.encode("utf-8-sig")
        resp = make_response(body)
        resp.headers["Content-Type"] = "text/csv; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp
    except Exception as e:
        return jsonify({"success": False, "message": f"生成模板失败：{e}"}), 500


@bp.post("/api/uploads/note-files")
@page13_access_required
def api_upload_note_file():
    """上传备注附件（PDF 等），存入数据库，返回可访问的下载 URL。"""
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"message": "请选择文件"}), 400
    fn_lower = (file.filename or "").lower()
    allowed = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".png", ".jpg", ".jpeg")
    if not any(fn_lower.endswith(ext) for ext in allowed):
        return jsonify({"message": f"仅支持以下格式：{', '.join(allowed)}"}), 400
    raw = file.read()
    if len(raw) > current_app.config.get("MAX_CONTENT_LENGTH", 25 * 1024 * 1024):
        return jsonify({"message": "文件过大"}), 400
    stored_name = f"{now_local().strftime('%Y%m%d%H%M%S%f')}_{secure_filename(file.filename)}"
    db.session.add(
        NoteAttachmentFile(
            stored_name=stored_name,
            file_blob=raw,
            original_name=file.filename,
        )
    )
    db.session.commit()
    download_url = f"/api/uploads/note-files/{stored_name}"
    return jsonify({"success": True, "url": download_url, "fileName": file.filename, "storedName": stored_name})


@bp.get("/api/uploads/note-files/<path:filename>")
def api_download_note_file(filename: str):
    """下载备注附件（优先数据库，其次遗留磁盘文件）。"""
    row = NoteAttachmentFile.query.filter_by(stored_name=filename).first()
    if row:
        return send_file(
            io.BytesIO(row.file_blob),
            as_attachment=True,
            download_name=row.original_name or filename,
        )
    notes_dir = Path(current_app.config["UPLOAD_FOLDER"]) / "notes"
    return send_from_directory(str(notes_dir), filename, as_attachment=True)


@bp.post("/api/uploads/import")
@page13_access_required
def api_uploads_import():
    """导入另一工具审核后导出的待办任务点（CSV 或 Excel，首行为表头）。"""
    file_storage = request.files.get("file")
    rows, parse_err = _parse_import_file(file_storage)
    if parse_err:
        return jsonify({"success": False, "message": parse_err}), 400
    if not rows:
        return jsonify({"success": True, "created": 0, "updated": 0, "skipped": 0, "errors": [], "message": "无有效数据行"})

    created = 0
    updated = 0
    skipped = 0
    errors = []

    for idx, d in enumerate(rows):
        row_no = idx + 2
        project_name = (d.get("project_name") or "").strip()
        file_name = (d.get("fileName") or "").strip()
        author = (d.get("author") or "").strip()
        if not project_name or not file_name or not author:
            skipped += 1
            errors.append({"row": row_no, "message": "缺少项目名称、文件名称或编写人员，已跳过"})
            continue

        task_type = (d.get("task_type") or "").strip() or None
        template_links = (d.get("template_links") or "").strip() or None
        if template_links:
            template_links = _normalize_template_links(template_links) or None
        due_date = _parse_import_date(d.get("due_date") or "")
        document_display_date = _parse_import_date(d.get("document_display_date") or "")

        existing = UploadRecord.query.filter_by(
            project_name=project_name,
            file_name=file_name,
            task_type=task_type,
            author=author,
        ).first()

        notes_raw = d.get("notes") or ""
        notes_val = "\n".join(ln.strip() for ln in notes_raw.replace(";", "\n").replace("；", "\n").split("\n") if ln.strip()) or None

        try:
            if existing:
                existing.project_code = (d.get("project_code") or "").strip() or None
                existing.business_side = (d.get("business_side") or "").strip() or None
                existing.product = (d.get("product") or "").strip() or None
                existing.country = (d.get("country") or "").strip() or None
                existing.project_notes = (d.get("project_notes") or "").strip() or None
                existing.template_links = template_links
                existing.notes = notes_val
                existing.assignee_name = (d.get("assignee_name") or "").strip() or None
                existing.due_date = due_date
                existing.file_version = (d.get("file_version") or "").strip() or None
                existing.document_display_date = document_display_date
                existing.reviewer = (d.get("reviewer") or "").strip() or None
                existing.approver = (d.get("approver") or "").strip() or None
                existing.belonging_module = (d.get("belonging_module") or "").strip() or None
                existing.displayed_author = (d.get("displayed_author") or "").strip() or None
                existing.registered_product_name = (d.get("registered_product_name") or "").strip() or None
                existing.model = (d.get("model") or "").strip() or None
                existing.registration_version = (d.get("registration_version") or "").strip() or None
                existing.task_status = "pending"
                existing.completion_status = None
                db.session.add(existing)
                updated += 1
            else:
                upload = UploadRecord(
                    project_name=project_name,
                    project_code=(d.get("project_code") or "").strip() or None,
                    file_name=file_name,
                    task_type=task_type,
                    author=author,
                    template_links=template_links,
                    notes=notes_val,
                    project_notes=(d.get("project_notes") or "").strip() or None,
                    assignee_name=(d.get("assignee_name") or "").strip() or None,
                    due_date=due_date,
                    business_side=(d.get("business_side") or "").strip() or None,
                    product=(d.get("product") or "").strip() or None,
                    country=(d.get("country") or "").strip() or None,
                    file_version=(d.get("file_version") or "").strip() or None,
                    document_display_date=document_display_date,
                    reviewer=(d.get("reviewer") or "").strip() or None,
                    approver=(d.get("approver") or "").strip() or None,
                    belonging_module=(d.get("belonging_module") or "").strip() or None,
                    displayed_author=(d.get("displayed_author") or "").strip() or None,
                    registered_product_name=(d.get("registered_product_name") or "").strip() or None,
                    model=(d.get("model") or "").strip() or None,
                    registration_version=(d.get("registration_version") or "").strip() or None,
                )
                db.session.add(upload)
                summary = _prepare_summary(upload)
                db.session.add(summary)
                created += 1
        except Exception as e:
            errors.append({"row": row_no, "message": str(e)})

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": f"保存失败：{e}"}), 500

    msg = f"导入完成：新增 {created} 条，更新 {updated} 条，跳过 {skipped} 条"
    if errors:
        msg += f"，{len(errors)} 条有误"
    return jsonify({
        "success": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:50],
        "message": msg,
    })


@bp.get("/api/template-options")
@bp.get("/api/upload-options")
@page13_access_required
def api_template_options():
    records = UploadRecord.query.order_by(
        UploadRecord.project_name, UploadRecord.file_name, UploadRecord.author
    ).all()
    return jsonify({"projects": _build_option_tree(records)})


@bp.get("/api/templates/<upload_id>")
@bp.get("/api/uploads/<upload_id>")
@page13_access_required
def api_template_detail(upload_id: str):
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到模板记录"}), 404
    placeholders = upload.placeholders or []
    if not placeholders and (
        upload.template_file_blob or upload.storage_path or upload.template_links
    ):
        try:
            if upload.template_file_blob:
                placeholders = extract_placeholders_from_bytes(upload.template_file_blob)
            else:
                template_path = _get_template_path_for_upload(upload)
                placeholders = extract_placeholders(template_path)
            upload.placeholders = placeholders
            db.session.add(upload)
            db.session.commit()
        except Exception as exc:
            return jsonify({"message": f"解析模板失败：{exc}"}), 400
    return jsonify(
        {
            "id": upload.id,
            "projectName": upload.project_name,
            "fileName": upload.file_name,
            "author": upload.author,
            "placeholders": placeholders,
            "hasLinks": bool(upload.template_links),
            "linksCount": len(upload.get_template_links_list()),
            "taskStatus": upload.task_status,
            "quickCompleted": upload.quick_completed,
            "assigneeName": upload.assignee_name,
            "dueDate": upload.due_date.strftime("%Y-%m-%d") if upload.due_date else None,
        }
    )


@bp.get("/api/uploads")
@page13_access_required
def api_uploads_list():
    """获取所有上传记录列表"""
    include_history = str(request.args.get("includeHistory") or "").strip() in ("1", "true", "True", "yes", "on")
    proj_meta = _project_meta_map(auto_create_from_uploads=True)
    ended = {n for n, m in proj_meta.items() if (m.get("status") or "").strip().lower() == Project.STATUS_ENDED}
    q = UploadRecord.query
    if (not include_history) and ended:
        q = q.filter(~UploadRecord.project_name.in_(list(ended)))
    records = _sort_upload_records_by_project_priority(
        q.order_by(UploadRecord.sort_order.asc(), UploadRecord.created_at.asc()).all(),
        proj_meta,
    )
    return jsonify({
        "records": [
            {
                "seq": idx + 1,
                "id": r.id,
                "projectName": r.project_name,
                "projectPriority": int((proj_meta.get(r.project_name) or {}).get("priority") or Project.PRIORITY_MEDIUM),
                "projectPriorityLabel": _project_priority_label((proj_meta.get(r.project_name) or {}).get("priority")),
                "projectStatus": ((proj_meta.get(r.project_name) or {}).get("status") or Project.STATUS_ACTIVE),
                "projectStatusLabel": _project_status_label((proj_meta.get(r.project_name) or {}).get("status")),
                "fileName": r.file_name,
                "taskType": r.task_type,
                "author": r.author,
                "hasFile": bool(r.template_file_blob or r.storage_path),
                "hasLinks": bool(r.template_links),
                "templateLinks": r.template_links,
                "linksCount": len(r.get_template_links_list()),
                "assigneeName": r.assignee_name,
                "dueDate": r.due_date.strftime("%Y-%m-%d") if r.due_date else None,
                "taskStatus": r.task_status,
                "completionStatus": r.completion_status,
                "auditStatus": r.audit_status,
                "quickCompleted": r.quick_completed,
                "sortOrder": r.sort_order,
                "businessSide": r.business_side,
                "product": r.product,
                "country": r.country,
                "projectCode": getattr(r, "project_code", None),
                "fileVersion": getattr(r, "file_version", None),
                "documentDisplayDate": (lambda d: d.strftime("%Y-%m-%d") if d else None)(getattr(r, "document_display_date", None)),
                "reviewer": getattr(r, "reviewer", None),
                "approver": getattr(r, "approver", None),
                "belongingModule": getattr(r, "belonging_module", None),
                "displayedAuthor": getattr(r, "displayed_author", None),
                "createdAt": r.created_at.isoformat() if r.created_at else None,
                "notes": r.notes,
                "projectNotes": getattr(r, "project_notes", None),
                "executionNotes": getattr(r, "execution_notes", None),
                "registeredProductName": getattr(r, "registered_product_name", None),
                "model": getattr(r, "model", None),
                "registrationVersion": getattr(r, "registration_version", None),
            }
            for idx, r in enumerate(records)
        ]
    })


@bp.delete("/api/uploads/<upload_id>")
@page13_access_required
def api_upload_delete(upload_id: str):
    """删除任务记录"""
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录"}), 404
    
    uploads_dir = Path(current_app.config["UPLOAD_FOLDER"])
    (uploads_dir / f"_dbtpl_{upload_id}.docx").unlink(missing_ok=True)
    if upload.storage_path:
        try:
            Path(upload.storage_path).unlink(missing_ok=True)
        except Exception:
            pass

    db.session.delete(upload)
    db.session.commit()
    return jsonify({"message": "已删除"})


@bp.patch("/api/uploads/<upload_id>")
@page13_access_required
def api_upload_update(upload_id: str):
    """更新任务记录（页面1编辑），仅更新可编辑字段，不涉及文件替换。"""
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录"}), 404
    
    data = request.get_json(force=True) or {}
    
    project_name = (data.get("projectName") or "").strip() or None
    if project_name:
        _ensure_project_row(project_name)
    file_name = (data.get("fileName") or "").strip() or None
    task_type = (data.get("taskType") or "").strip() or None
    author = (data.get("author") or "").strip() or None
    due_date_str = (data.get("dueDate") or "").strip() or None
    business_side = (data.get("businessSide") or "").strip() or None
    product = (data.get("product") or "").strip() or None
    country = (data.get("country") or "").strip() or None
    assignee_name = (data.get("assigneeName") or "").strip() or None
    completion_status = (data.get("completionStatus") or "").strip() or None
    audit_status = (data.get("auditStatus") or "").strip() or None
    project_code = (data.get("projectCode") or "").strip() or None
    file_version = (data.get("fileVersion") or "").strip() or None
    document_display_date_str = (data.get("documentDisplayDate") or "").strip() or None
    reviewer = (data.get("reviewer") or "").strip() or None
    approver = (data.get("approver") or "").strip() or None
    project_notes = (data.get("projectNotes") or "").strip() or None
    has_project_notes = "projectNotes" in data
    belonging_module = (data.get("belongingModule") or "").strip() or None
    has_belonging_module = "belongingModule" in data
    displayed_author = (data.get("displayedAuthor") or "").strip() or None
    has_displayed_author = "displayedAuthor" in data
    registered_product_name = (data.get("registeredProductName") or "").strip() or None
    has_registered_product_name = "registeredProductName" in data
    model = (data.get("model") or "").strip() or None
    has_model = "model" in data
    registration_version = (data.get("registrationVersion") or "").strip() or None
    has_registration_version = "registrationVersion" in data

    if project_name is not None:
        upload.project_name = project_name
    if file_name is not None:
        upload.file_name = file_name
    if "taskType" in data:
        raw_tt = data.get("taskType")
        upload.task_type = (str(raw_tt).strip() if raw_tt is not None else "") or None
    if author is not None:
        if not author:
            return jsonify({"message": "编写人员不能为空"}), 400
        upload.author = author
    if business_side is not None:
        upload.business_side = business_side or None
    if product is not None:
        upload.product = product or None
    if country is not None:
        upload.country = country or None
    if "templateLinks" in data:
        val = data.get("templateLinks")
        s = (val if isinstance(val, str) else "").strip()
        upload.template_links = _normalize_template_links(s) or None
    if assignee_name is not None:
        upload.assignee_name = assignee_name or None
    if "notes" in data:
        val = data.get("notes")
        s = (val if isinstance(val, str) else "").strip()
        upload.notes = s or None
    if has_project_notes:
        upload.project_notes = project_notes
    if project_code is not None:
        upload.project_code = project_code
    if file_version is not None:
        upload.file_version = file_version
    if document_display_date_str is not None:
        if not document_display_date_str:
            upload.document_display_date = None
        else:
            try:
                upload.document_display_date = datetime.strptime(document_display_date_str, "%Y-%m-%d").date()
            except ValueError:
                pass
    if reviewer is not None:
        upload.reviewer = reviewer
    if approver is not None:
        upload.approver = approver
    if has_belonging_module:
        upload.belonging_module = belonging_module
    if has_displayed_author:
        upload.displayed_author = displayed_author
    if has_registered_product_name:
        upload.registered_product_name = registered_product_name
    if has_model:
        upload.model = model
    if has_registration_version:
        upload.registration_version = registration_version
    if audit_status is not None:
        upload.audit_status = audit_status or None
        if audit_status == "审核不通过待修改":
            upload.audit_reject_count = (getattr(upload, "audit_reject_count", 0) or 0) + 1
            upload.completion_status = None
            upload.task_status = "pending"
            upload.quick_completed = False
    if completion_status is not None:
        upload.completion_status = completion_status or None
        if upload.completion_status:
            upload.task_status = "completed"
        else:
            upload.task_status = "pending"
    
    if due_date_str is not None:
        if not due_date_str:
            upload.due_date = None
        else:
            try:
                upload.due_date = datetime.strptime(due_date_str, "%Y-%m-%d").date()
            except ValueError:
                return jsonify({"message": "截止日期格式应为 YYYY-MM-DD"}), 400
    
    if upload.project_name and upload.file_name and upload.author:
        other = UploadRecord.query.filter(
            UploadRecord.project_name == upload.project_name,
            UploadRecord.file_name == upload.file_name,
            UploadRecord.author == upload.author,
            UploadRecord.id != upload.id,
        ).first()
        if other and (upload.task_type or None) == (other.task_type or None):
            return jsonify({"message": "项目名称+文件名称+任务类型+编写人与已有记录重复"}), 409
    
    db.session.add(upload)
    if upload.summary:
        upload.summary.project_name = upload.project_name
        upload.summary.file_name = upload.file_name
        upload.summary.author = upload.author
        db.session.add(upload.summary)
    db.session.commit()
    # 页面1编辑不触发模块级联催办，仅在页面2标记完成时触发（见 api_update_completion_status）

    return jsonify({
        "message": "已更新",
        "record": {
            "id": upload.id,
            "projectName": upload.project_name,
            "fileName": upload.file_name,
            "taskType": upload.task_type,
            "author": upload.author,
            "dueDate": upload.due_date.strftime("%Y-%m-%d") if upload.due_date else None,
            "businessSide": upload.business_side,
            "product": upload.product,
            "country": upload.country,
            "assigneeName": upload.assignee_name,
        },
    })


@bp.get("/api/my-tasks")
@login_required
def api_my_tasks():
    """获取当前登录用户的任务列表（页面2使用）"""
    username = session.get("username")
    display_name = session.get("display_name")

    include_history = str(request.args.get("includeHistory") or "").strip() in ("1", "true", "True", "yes", "on")
    proj_meta = _project_meta_map(auto_create_from_uploads=True)
    ended = {n for n, m in proj_meta.items() if (m.get("status") or "").strip().lower() == Project.STATUS_ENDED}

    q = UploadRecord.query.filter(
        db.or_(
            UploadRecord.assignee_name == username,
            UploadRecord.assignee_name == display_name,
            UploadRecord.author == username,
            UploadRecord.author == display_name,
        )
    )
    if (not include_history) and ended:
        q = q.filter(~UploadRecord.project_name.in_(list(ended)))
    records = _sort_upload_records_by_project_priority(
        q.order_by(UploadRecord.sort_order.asc(), UploadRecord.created_at.asc()).all(),
        proj_meta,
    )
    
    return jsonify({
        "records": [
            {
                "seq": idx + 1,
                "id": r.id,
                "projectName": r.project_name,
                "projectPriority": int((proj_meta.get(r.project_name) or {}).get("priority") or Project.PRIORITY_MEDIUM),
                "projectPriorityLabel": _project_priority_label((proj_meta.get(r.project_name) or {}).get("priority")),
                "projectStatus": ((proj_meta.get(r.project_name) or {}).get("status") or Project.STATUS_ACTIVE),
                "projectStatusLabel": _project_status_label((proj_meta.get(r.project_name) or {}).get("status")),
                "fileName": r.file_name,
                "taskType": r.task_type,
                "author": r.author,
                "hasFile": bool(r.template_file_blob or r.storage_path),
                "hasLinks": bool(r.template_links),
                "templateLinks": r.template_links,
                "linksCount": len(r.get_template_links_list()),
                "assigneeName": r.assignee_name,
                "dueDate": r.due_date.strftime("%Y-%m-%d") if r.due_date else None,
                "taskStatus": r.task_status,
                "completionStatus": r.completion_status,
                "quickCompleted": r.quick_completed,
                "placeholders": r.placeholders or [],
                "sortOrder": r.sort_order,
                "businessSide": r.business_side,
                "product": r.product,
                "country": r.country,
                "projectCode": getattr(r, "project_code", None),
                "fileVersion": getattr(r, "file_version", None),
                "documentDisplayDate": (lambda d: d.strftime("%Y-%m-%d") if d else None)(getattr(r, "document_display_date", None)),
                "reviewer": getattr(r, "reviewer", None),
                "approver": getattr(r, "approver", None),
                "belongingModule": getattr(r, "belonging_module", None),
                "displayedAuthor": getattr(r, "displayed_author", None),
                "createdAt": r.created_at.isoformat() if r.created_at else None,
                "notes": r.notes,
                "projectNotes": getattr(r, "project_notes", None),
                "executionNotes": getattr(r, "execution_notes", None),
                "registeredProductName": getattr(r, "registered_product_name", None),
                "model": getattr(r, "model", None),
                "registrationVersion": getattr(r, "registration_version", None),
            }
            for idx, r in enumerate(records)
        ]
    })


@bp.patch("/api/uploads/<upload_id>/execution-notes")
@login_required
def api_update_execution_notes(upload_id: str):
    """更新执行任务备注（仅页面2可编辑）。"""
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录"}), 404
    data = request.get_json(force=True) or {}
    val = data.get("executionNotes")
    s = (val if isinstance(val, str) else "").strip() or None
    upload.execution_notes = s
    db.session.add(upload)
    db.session.commit()
    return jsonify({"message": "已更新", "executionNotes": upload.execution_notes})


@bp.patch("/api/uploads/<upload_id>/completion-status")
@login_required
def api_update_completion_status(upload_id: str):
    """更新任务的完成状态（页面2使用）。可仅更新文档链接；标记完成时需已填写文档链接。"""
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录"}), 404
    
    data = request.get_json(force=True) or {}
    completion_status = data.get("completionStatus")
    template_links = (data.get("templateLinks") or "").strip() or None
    
    if template_links is not None:
        if template_links and not _is_valid_doc_link(template_links):
            return jsonify({"message": "请填写有效的文档链接（需以 http:// 或 https:// 开头）"}), 400
        upload.template_links = _normalize_template_links(template_links) or None
    
    if completion_status is not None:
        if completion_status:
            if not upload.has_template():
                return jsonify({"message": "请先填写文档链接后再标记完成状态"}), 400
            upload.completion_status = completion_status
            upload.task_status = "completed"
        else:
            upload.completion_status = None
            upload.task_status = "pending"
    
    db.session.add(upload)
    db.session.commit()
    if upload.completion_status and (upload.belonging_module or "").strip() in ("产品", "开发"):
        _maybe_enqueue_module_cascade(upload.project_name or "", (upload.belonging_module or "").strip())

    return jsonify({
        "message": "已更新完成状态",
        "uploadId": upload_id,
        "completionStatus": upload.completion_status,
        "taskStatus": upload.task_status,
    })


# ---------- 文档生成 API ----------

@bp.post("/api/generate")
@login_required
def api_generate():
    data = request.get_json(force=True) or {}
    upload_id = data.get("uploadId")
    triggered_by = data.get("triggeredBy") or session.get("username", "web")
    placeholder_values = data.get("values") or {}
    output_name = data.get("outputName")
    replace = str(data.get("replace")).lower() == "true"
    link_index = int(data.get("linkIndex", 0))

    if not upload_id:
        return jsonify({"message": "请提供 uploadId。"}), 400

    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到对应的模板记录"}), 404

    template_bytes = None
    template_path = None
    try:
        if upload.template_file_blob:
            template_bytes = upload.template_file_blob
        else:
            template_path = _get_template_path_for_upload(upload, link_index)
    except Exception as e:
        return jsonify({"message": str(e)}), 400

    required_placeholders = upload.placeholders or []
    if not required_placeholders:
        try:
            if template_bytes is not None:
                required_placeholders = extract_placeholders_from_bytes(template_bytes)
            else:
                required_placeholders = extract_placeholders(template_path or "")
            upload.placeholders = required_placeholders
            db.session.add(upload)
            db.session.commit()
        except Exception as exc:
            return jsonify({"message": f"解析模板失败：{exc}"}), 400

    missing = [
        key for key in required_placeholders if not placeholder_values.get(key, "").strip()
    ]
    if missing:
        return jsonify({"message": f"以下占位符尚未填写：{', '.join(missing)}"}), 400

    existing_record = GenerateRecord.query.filter_by(upload_id=upload_id).first()
    if existing_record and not replace:
        return (
            jsonify(
                {
                    "message": "该项目与文件的生成记录已存在，是否替换原内容？",
                    "needsConfirmation": True,
                }
            ),
            409,
        )

    outputs_dir = Path(current_app.config["OUTPUT_FOLDER"])
    stem = Path(upload.file_name).stem if upload.file_name else "document"
    try:
        output_path = generate_document(
            output_dir=str(outputs_dir),
            data=placeholder_values,
            output_name=output_name,
            template_path=template_path,
            template_bytes=template_bytes,
            template_stem=stem,
        )
    except Exception as exc:
        return jsonify({"message": f"生成文档失败：{exc}"}), 500

    out_p = Path(output_path)
    try:
        output_blob = out_p.read_bytes()
    except Exception as exc:
        return jsonify({"message": f"读取生成文件失败：{exc}"}), 500
    out_p.unlink(missing_ok=True)

    if existing_record and replace:
        previous_path = existing_record.output_path
        if previous_path:
            Path(previous_path).unlink(missing_ok=True)
        record = existing_record
        record.placeholder_payload = placeholder_values
        record.status = "completed"
        record.success = True
        record.completed_at = now_local()
        record.output_file_name = out_p.name
        record.output_path = None
        record.output_file_blob = output_blob
        record.triggered_by = triggered_by
    else:
        record = GenerateRecord(
            upload=upload,
            triggered_by=triggered_by,
            status="completed",
            success=True,
            completed_at=now_local(),
            placeholder_payload=placeholder_values,
            output_file_name=out_p.name,
            output_path=None,
            output_file_blob=output_blob,
        )
    db.session.add(record)

    summary = _prepare_summary(upload)
    summary.total_generate_clicks += 1
    summary.has_generated = True
    summary.last_generated_at = now_local()
    db.session.add(summary)

    upload.task_status = "completed"
    db.session.add(upload)

    db.session.commit()

    return jsonify(
        {
            "message": "文档生成成功。",
            "recordId": record.id,
            "uploadId": upload_id,
            "downloadUrl": url_for("pages.api_download_generated", record_id=record.id),
        }
    )


@bp.get("/api/generate-records/<record_id>/download")
@login_required
def api_download_generated(record_id: str):
    """下载已生成 Word（内容存于数据库）。"""
    record = GenerateRecord.query.get(record_id)
    if not record or not record.upload:
        return jsonify({"message": "记录不存在"}), 404
    username = session.get("username")
    if record.upload.author != username:
        return jsonify({"message": "无权下载"}), 403
    blob = record.output_file_blob
    if not blob and record.output_path and Path(record.output_path).is_file():
        blob = Path(record.output_path).read_bytes()
    if not blob:
        return jsonify({"message": "生成文件不可用"}), 404
    name = record.output_file_name or "generated.docx"
    return send_file(
        io.BytesIO(blob),
        as_attachment=True,
        download_name=name,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ---------- 快速完成 API ----------

@bp.post("/api/quick-complete")
@login_required
def api_quick_complete():
    """
    快速完成文档：无需填写占位符，直接在链接中填写完文档后标记完成。
    适用于页面1填写了文档链接的情况。
    """
    data = request.get_json(force=True) or {}
    upload_id = data.get("uploadId")

    if not upload_id:
        return jsonify({"message": "请提供 uploadId。"}), 400

    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到对应的记录"}), 404

    if not upload.template_links:
        return jsonify({"message": "该记录没有文档链接，无法使用快速完成功能。"}), 400

    upload.quick_completed = True
    upload.task_status = "completed"
    db.session.add(upload)

    summary = _prepare_summary(upload)
    summary.has_generated = True
    summary.total_generate_clicks += 1
    summary.last_generated_at = now_local()
    db.session.add(summary)

    db.session.commit()

    return jsonify({
        "message": "已快速完成。",
        "uploadId": upload_id,
        "taskStatus": upload.task_status,
    })


# ---------- 任务状态更新 API ----------

@bp.patch("/api/uploads/<upload_id>/status")
@page13_access_required
def api_upload_status_update(upload_id: str):
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该记录。"}), 404
    data = request.get_json(force=True) or {}
    if data.get("status") == "completed":
        upload.task_status = "completed"
        db.session.add(upload)
        db.session.commit()
    return jsonify({
        "message": "已更新。",
        "uploadId": upload_id,
        "taskStatus": upload.task_status,
    })


@bp.get("/api/summary")
@page13_access_required
def api_summary():
    return jsonify(_summary_payload())


# ---------- 项目管理 API ----------

@bp.get("/api/projects")
@page13_access_required
def api_projects_list():
    """列出项目（从 upload_records 自动补齐缺失项）。"""
    _project_meta_map(auto_create_from_uploads=True)
    _backfill_project_ids()
    rows = Project.query.order_by(Project.priority.desc(), Project.name.asc()).all()
    return jsonify(
        [
            {
                "id": p.id,
                "name": p.name,
                "registeredCountry": getattr(p, "registered_country", None),
                "registeredCategory": getattr(p, "registered_category", None),
                "projectKey": _project_display_label(p),
                "priority": int(p.priority or Project.PRIORITY_MEDIUM),
                "priorityLabel": _project_priority_label(p.priority),
                "status": p.status or Project.STATUS_ACTIVE,
                "statusLabel": _project_status_label(p.status),
                "updatedAt": p.updated_at.isoformat() if p.updated_at else None,
            }
            for p in rows
        ]
    )


@bp.post("/api/projects")
@page13_access_required
def api_projects_create_or_update():
    """按（三字段）创建/更新项目优先级与状态。"""
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"message": "项目名称不能为空"}), 400
    registered_country = (data.get("registeredCountry") or "").strip() or None
    registered_category = (data.get("registeredCategory") or "").strip() or None
    priority = data.get("priority")
    status = (data.get("status") or "").strip().lower() or Project.STATUS_ACTIVE
    if priority is None:
        priority = Project.PRIORITY_MEDIUM
    try:
        priority = int(priority)
    except Exception:
        priority = Project.PRIORITY_MEDIUM
    priority = max(Project.PRIORITY_LOW, min(Project.PRIORITY_HIGH, priority))
    if status not in (Project.STATUS_ACTIVE, Project.STATUS_ENDED):
        status = Project.STATUS_ACTIVE

    q = Project.query.filter(Project.name == name)
    q = _filter_nullable_eq(q, Project.registered_country, registered_country)
    q = _filter_nullable_eq(q, Project.registered_category, registered_category)
    row = q.first()
    if not row:
        row = Project(
            name=name,
            registered_country=registered_country,
            registered_category=registered_category,
            priority=priority,
            status=status,
        )
    row.priority = priority
    row.status = status
    db.session.add(row)
    db.session.commit()
    return jsonify(
        {
            "message": "已保存",
            "project": {
                "id": row.id,
                "name": row.name,
                "registeredCountry": getattr(row, "registered_country", None),
                "registeredCategory": getattr(row, "registered_category", None),
                "projectKey": _project_display_label(row),
                "priority": int(row.priority or Project.PRIORITY_MEDIUM),
                "priorityLabel": _project_priority_label(row.priority),
                "status": row.status,
                "statusLabel": _project_status_label(row.status),
                "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
            },
        }
    )


@bp.patch("/api/projects/<project_id>")
@page13_access_required
def api_projects_patch(project_id: str):
    row = Project.query.get(project_id)
    if not row:
        return jsonify({"message": "未找到该项目"}), 404
    data = request.get_json(force=True) or {}

    old_key = _project_display_label(row)
    new_name = row.name
    new_country = getattr(row, "registered_country", None)
    new_category = getattr(row, "registered_category", None)

    if "name" in data:
        n = (data.get("name") or "").strip()
        if n:
            new_name = n
    if "registeredCountry" in data:
        new_country = (data.get("registeredCountry") or "").strip() or None
    if "registeredCategory" in data:
        new_category = (data.get("registeredCategory") or "").strip() or None

    # 更新基础三字段时，检查是否与其它项目重复
    q = Project.query.filter(Project.id != row.id).filter(Project.name == new_name)
    q = _filter_nullable_eq(q, Project.registered_country, new_country)
    q = _filter_nullable_eq(q, Project.registered_category, new_category)
    other = q.first()
    if other:
        return (
            jsonify(
                {
                    "message": "该项目（三字段）与已有项目重复，请先调整后再保存",
                    "conflictProjectId": other.id,
                }
            ),
            409,
        )

    if "priority" in data:
        try:
            p = int(data.get("priority"))
            row.priority = max(Project.PRIORITY_LOW, min(Project.PRIORITY_HIGH, p))
        except Exception:
            pass
    if "status" in data:
        s = (data.get("status") or "").strip().lower()
        if s in (Project.STATUS_ACTIVE, Project.STATUS_ENDED):
            row.status = s

    # 真正应用三字段
    row.name = new_name
    row.registered_country = new_country
    row.registered_category = new_category

    new_key = _project_display_label(row)
    db.session.add(row)
    db.session.commit()

    # 若三字段变化导致展示键变化，要同步更新已存在的任务/模块级联/生成摘要
    if old_key != new_key:
        UploadRecord.query.filter_by(project_name=old_key).update(
            {"project_name": new_key}
        )
        ModuleCascadeReminder.query.filter_by(project_name=old_key).update(
            {"project_name": new_key}
        )
        # 生成摘要也用于展示/下载列表时的统计口径（尽量保持一致）
        try:
            GenerationSummary.query.filter_by(project_name=old_key).update(
                {"project_name": new_key}
            )
        except Exception:
            pass
        db.session.commit()
    return jsonify({"message": "已更新"})


@bp.route("/api/projects/batch", methods=["PUT", "POST"])
@page13_access_required
def api_projects_batch_update():
    """批量更新项目优先级/状态（用于页面1一键保存/批量编辑）。"""
    data = request.get_json(force=True) or {}
    items = data.get("projects") or []
    if not isinstance(items, list) or not items:
        return jsonify({"message": "projects 不能为空"}), 400

    from .models import UploadRecord, ModuleCascadeReminder, GenerationSummary

    # 防止“一键保存”把两个项目更新成同一（三字段）重复项目
    request_ids = []
    triples_to_ids: dict[tuple[str, Any, Any], list[str]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        pid = (it.get("id") or "").strip()
        if not pid:
            continue
        request_ids.append(pid)

    request_id_set = set(request_ids)
    for it in items:
        if not isinstance(it, dict):
            continue
        pid = (it.get("id") or "").strip()
        if not pid:
            continue
        row = Project.query.get(pid)
        if not row:
            continue
        target_country = (it.get("registeredCountry") or "").strip() or None
        target_category = (it.get("registeredCategory") or "").strip() or None
        triple = (row.name, target_country, target_category)
        triples_to_ids.setdefault(triple, []).append(pid)
    for triple, ids in triples_to_ids.items():
        if len(set(ids)) > 1:
            return (
                jsonify(
                    {
                        "message": "批量保存失败：检测到（三字段）重复项目（已被请求批量设置为同一三字段组合）。请先避免重复或删除多余项目。",
                        "dupProjectIds": list(set(ids)),
                    }
                ),
                409,
            )

    # 若与数据库中非本次请求的其它项目重复，也拒绝
    for triple, ids in triples_to_ids.items():
        base_name, target_country, target_category = triple
        q = Project.query.filter(Project.name == base_name)
        q = _filter_nullable_eq(q, Project.registered_country, target_country)
        q = _filter_nullable_eq(q, Project.registered_category, target_category)
        q = q.filter(~Project.id.in_(list(request_id_set) or [""]))
        other = q.first()
        if other:
            return (
                jsonify(
                    {
                        "message": "批量保存失败：目标（三字段）与已有项目重复，请先调整后再保存",
                        "conflictProjectId": other.id,
                    }
                ),
                409,
            )

    updated = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        pid = (it.get("id") or "").strip()
        if not pid:
            continue
        row = Project.query.get(pid)
        if not row:
            continue

        old_key = _project_display_label(row)

        if "priority" in it:
            try:
                p = int(it.get("priority"))
                row.priority = max(Project.PRIORITY_LOW, min(Project.PRIORITY_HIGH, p))
            except Exception:
                pass
        if "status" in it:
            s = (it.get("status") or "").strip().lower()
            if s in (Project.STATUS_ACTIVE, Project.STATUS_ENDED):
                row.status = s

        if "registeredCountry" in it:
            row.registered_country = (it.get("registeredCountry") or "").strip() or None
        if "registeredCategory" in it:
            row.registered_category = (it.get("registeredCategory") or "").strip() or None

        new_key = _project_display_label(row)
        if old_key != new_key:
            UploadRecord.query.filter_by(project_name=old_key).update(
                {"project_name": new_key}
            )
            ModuleCascadeReminder.query.filter_by(project_name=old_key).update(
                {"project_name": new_key}
            )
            try:
                GenerationSummary.query.filter_by(project_name=old_key).update(
                    {"project_name": new_key}
                )
            except Exception:
                pass

        db.session.add(row)
        updated += 1

    db.session.commit()
    return jsonify({"message": f"已保存 {updated} 项", "updated": updated})


@bp.delete("/api/projects/<project_id>")
@page13_access_required
def api_projects_delete(project_id: str):
    """删除项目：仅当项目未绑定任务/级联记录时允许。"""
    from .models import UploadRecord, ModuleCascadeReminder, GenerationSummary

    row = Project.query.get(project_id)
    if not row:
        return jsonify({"message": "未找到该项目"}), 404

    key = _project_display_label(row)

    upload_count = UploadRecord.query.filter(UploadRecord.project_id == row.id).count()
    cascade_count = ModuleCascadeReminder.query.filter(ModuleCascadeReminder.project_id == row.id).count()
    generation_count = GenerationSummary.query.filter(GenerationSummary.project_id == row.id).count()

    total = upload_count + cascade_count + generation_count
    if total > 0:
        return (
            jsonify(
                {
                    "message": "无法删除：该项目已绑定任务/级联/生成记录，请先清理后再删除",
                    "bound": {
                        "uploadCount": upload_count,
                        "cascadeCount": cascade_count,
                        "generationCount": generation_count,
                        "totalCount": total,
                    },
                }
            ),
            409,
        )

    db.session.delete(row)
    db.session.commit()
    return jsonify({"message": "项目已删除"})


@bp.get("/api/projects/<project_id>/bindings")
@page13_access_required
def api_projects_bindings_count(project_id: str):
    """获取项目绑定数量：用于删除前提示。"""
    from .models import UploadRecord, ModuleCascadeReminder, GenerationSummary

    row = Project.query.get(project_id)
    if not row:
        return jsonify({"message": "未找到该项目"}), 404

    key = _project_display_label(row)
    upload_count = UploadRecord.query.filter(UploadRecord.project_id == row.id).count()
    cascade_count = ModuleCascadeReminder.query.filter(ModuleCascadeReminder.project_id == row.id).count()
    generation_count = GenerationSummary.query.filter(GenerationSummary.project_id == row.id).count()
    total = upload_count + cascade_count + generation_count

    return jsonify(
        {
            "message": "ok",
            "projectKey": key,
            "bound": {
                "uploadCount": upload_count,
                "cascadeCount": cascade_count,
                "generationCount": generation_count,
                "totalCount": total,
            },
        }
    )


# ---------- 通知文案配置 API ----------

@bp.get("/api/configs/notify-templates")
@page13_access_required
def api_get_notify_templates():
    templates = NotifyTemplateConfig.query.order_by(NotifyTemplateConfig.template_key).all()
    return jsonify([
        {
            "id": t.id,
            "key": t.template_key,
            "name": t.template_name,
            "content": t.template_content,
            "isActive": t.is_active,
        }
        for t in templates
    ])


@bp.put("/api/configs/notify-templates/<template_id>")
@page13_access_required
def api_update_notify_template(template_id: str):
    template = NotifyTemplateConfig.query.get(template_id)
    if not template:
        return jsonify({"message": "未找到该通知模板"}), 404
    
    data = request.get_json(force=True) or {}
    if "content" in data:
        template.template_content = data["content"]
    if "name" in data:
        template.template_name = data["name"]
    if "isActive" in data:
        template.is_active = data["isActive"]
    
    db.session.add(template)
    db.session.commit()
    
    return jsonify({
        "message": "更新成功",
        "id": template.id,
    })


# ---------- 排序更新 API ----------

@bp.post("/api/uploads/reorder")
@login_required
def api_reorder_uploads():
    """更新任务排序"""
    data = request.get_json(force=True) or {}
    orders = data.get("orders", [])
    
    if not orders:
        return jsonify({"message": "排序数据为空"}), 400
    
    for item in orders:
        upload_id = item.get("id")
        sort_order = item.get("sortOrder", 0)
        if upload_id:
            upload = UploadRecord.query.get(upload_id)
            if upload:
                upload.sort_order = sort_order
                db.session.add(upload)
    
    db.session.commit()
    return jsonify({"message": "排序更新成功"})


# ---------- 钉钉通知推送 API ----------

def _get_notify_template(key: str) -> str:
    """获取通知文案模板"""
    template = NotifyTemplateConfig.query.filter_by(template_key=key, is_active=True).first()
    if template:
        return template.template_content
    return ""


def _resolve_mobiles_for_authors(author_names: list) -> list:
    """根据编写人员姓名解析钉钉 @ 用的手机号（从 User 表）"""
    if not author_names:
        return []
    from .models import User
    mobiles = []
    for name in author_names:
        if not name:
            continue
        user = User.query.filter(
            db.or_(
                User.username == name,
                User.display_name == name,
            )
        ).first()
        if user and getattr(user, "mobile", None) and str(user.mobile).strip():
            mobiles.append(str(user.mobile).strip())
    return mobiles


def _get_base_url() -> str:
    """获取对外访问的基础 URL（域名），用于催办等通知中的链接。优先使用配置的 BASE_URL，否则用当前请求的 host。"""
    from .app_settings import get_setting
    base = (get_setting("BASE_URL") or "").strip()
    if base:
        return base.rstrip("/")
    if request and request.host_url:
        return request.host_url.rstrip("/")
    return ""


def _maybe_enqueue_module_cascade(project_name: str, trigger_module: str) -> None:
    """
    当某项目下所属模块为 trigger_module（产品或开发）的最后一份文档被标记为完成后，入队一条延迟发送的模块级联催办。
    产品→开发；开发→测试。同一项目同一触发模块只保留一条待执行，新入队会覆盖旧待执行。
    """
    if not project_name or (trigger_module or "").strip() not in ("产品", "开发"):
        return
    pname = (project_name or "").strip()
    tmod = (trigger_module or "").strip()
    target_module = "开发" if tmod == "产品" else "测试"
    all_in_module = UploadRecord.query.filter(
        UploadRecord.project_name == pname,
        UploadRecord.belonging_module == tmod,
    ).all()
    if not all_in_module:
        return
    if any(getattr(u, "completion_status", None) is None for u in all_in_module):
        return
    row = AppConfig.query.filter_by(config_key="MODULE_CASCADE_DELAY_MINUTES").first()
    delay_minutes = 5
    if row and row.config_value:
        try:
            delay_minutes = max(1, min(1440, int(str(row.config_value).strip())))
        except ValueError:
            pass
    from datetime import timedelta
    run_at = now_local() + timedelta(minutes=delay_minutes)
    ModuleCascadeReminder.query.filter(
        ModuleCascadeReminder.project_name == pname,
        ModuleCascadeReminder.trigger_module == tmod,
        ModuleCascadeReminder.status == "pending",
    ).delete()
    db.session.add(ModuleCascadeReminder(
        project_name=pname,
        trigger_module=tmod,
        target_module=target_module,
        run_at=run_at,
        status="pending",
    ))
    db.session.commit()


def _send_notify_to_individuals(
    title: str,
    message_markdown: str,
    at_mobiles: Optional[list] = None,
    at_names: Optional[list] = None,
):
    """群消息发送成功后，再向被@人员的个人工作通知发一份（需配置 DINGTALK_APP_KEY/APP_SECRET/AGENT_ID）。"""
    mobiles = list(at_mobiles) if at_mobiles else []
    if not mobiles and at_names:
        mobiles = _resolve_mobiles_for_authors(list(at_names))
    if not mobiles:
        return
    dingtalk_service.send_work_notification_to_mobiles(title, message_markdown, mobiles)


@bp.post("/api/notify/by-project")
@page13_access_required
def api_notify_by_project():
    """按项目推送钉钉通知"""
    data = request.get_json(force=True) or {}
    project_name = data.get("projectName")
    
    if not project_name:
        return jsonify({"message": "请提供项目名称"}), 400
    
    webhook = _dingtalk_webhook_str()
    secret = _dingtalk_secret_opt()
    
    if not webhook:
        return jsonify({"message": "未配置钉钉 Webhook，请在页面3「系统配置」中填写"}), 400
    
    pending_uploads = UploadRecord.query.filter(
        UploadRecord.project_name == project_name,
        UploadRecord.completion_status.is_(None)
    ).all()
    
    if not pending_uploads:
        return jsonify({"message": f"项目 {project_name} 没有未完成的任务"})
    
    assignees = list(set(u.author for u in pending_uploads if u.author))
    
    def _group_key(u):
        return (u.project_name or "", u.business_side or "", u.product or "")
    
    groups = {}
    for u in pending_uploads:
        k = _group_key(u)
        groups.setdefault(k, []).append(u)
    
    def _task_block_md(key, uploads_in_group):
        proj, bs, pr = key
        lines = []
        proj_code = getattr(uploads_in_group[0], "project_code", None) if uploads_in_group else None
        header = f"**项目：{proj or '-'}  项目编号：{proj_code or '-'}  影响业务方：{bs or '-'}  产品：{pr or '-'}**"
        lines.append(header)
        for u in uploads_in_group:
            links = u.get_template_links_list() or []
            link = links[0] if links else None
            due = u.due_date.strftime("%Y-%m-%d") if u.due_date else "-"
            due_red = f'<font color="red">{due}</font>' if due != "-" else "-"
            file_label = u.file_name or "-"
            if u.task_type:
                file_label += f" ({u.task_type})"
            fv = getattr(u, "file_version", None) or "-"
            ddd = (u.document_display_date.strftime("%Y-%m-%d") if u.document_display_date else "-") if getattr(u, "document_display_date", None) else "-"
            rev = getattr(u, "reviewer", None) or "-"
            appr = getattr(u, "approver", None) or "-"
            line = f" - 文件名称：{file_label}  文件版本号：{fv}  截止日期：{due_red}  文档体现日期：{ddd}  审核：{rev}  批准：{appr}"
            if link:
                line += f"  文档地址：[点击打开]({link})"
            lines.append(line)
        return "\n".join(lines)
    
    task_list_with_links_md = "\n\n".join(
        _task_block_md(k, grp) for k, grp in groups.items()
    )
    
    base_url = _get_base_url()
    page2_path = url_for("pages.generate_page", _external=False)
    page2_url = f"{base_url}{page2_path}" if base_url else url_for("pages.generate_page", _external=True)
    message_plain = (
        "【项目任务催办】\n\n"
        f"项目：{project_name}\n\n"
        f"未完成任务数：{len(pending_uploads)}\n\n"
        f"请以下人员尽快完成：{'、'.join(assignees)}\n\n\n"
        "未完成列表：\n\n"
        f"{task_list_with_links_md}\n\n"
        f"页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）\n\n"
        "### **编写完成后请在页面2中标记完成状态。**\n\n"
        "请抓紧处理！"
    )
    at_mobiles = _resolve_mobiles_for_authors(assignees)
    result = dingtalk_service.send_markdown_message(
        "项目任务催办",
        message_plain,
        at_all=False,
        at_mobiles=at_mobiles,
        at_names=assignees,
        webhook=webhook,
        secret=secret,
    )
    ok = result is not None and result.get("success") is True
    if ok:
        return jsonify({"success": True, "message": "通知发送成功", "atNames": list(assignees)}), 200
    err = result.get("error", "未知错误") if result else "未知错误"
    if isinstance(err, dict):
        err = "未知错误"
    return jsonify({"success": False, "message": f"通知发送失败: {err}"}), 200


@bp.post("/api/notify/by-author")
@page13_access_required
def api_notify_by_author():
    """按编写人员推送钉钉通知"""
    data = request.get_json(force=True) or {}
    author = data.get("author")
    
    if not author:
        return jsonify({"message": "请提供编写人员"}), 400
    
    webhook = _dingtalk_webhook_str()
    secret = _dingtalk_secret_opt()
    
    if not webhook:
        return jsonify({"message": "未配置钉钉 Webhook，请在页面3「系统配置」中填写"}), 400
    
    pending_uploads = UploadRecord.query.filter(
        UploadRecord.author == author,
        UploadRecord.completion_status.is_(None)
    ).all()
    
    if not pending_uploads:
        return jsonify({"message": f"{author} 没有未完成的任务"})
    
    def _group_key(u):
        return (u.project_name or "", u.business_side or "", u.product or "")
    
    groups = {}
    for u in pending_uploads:
        k = _group_key(u)
        groups.setdefault(k, []).append(u)
    
    def _task_block_md(key, uploads_in_group):
        proj, bs, pr = key
        lines = []
        proj_code = getattr(uploads_in_group[0], "project_code", None) if uploads_in_group else None
        header = f"**项目：{proj or '-'}  项目编号：{proj_code or '-'}  影响业务方：{bs or '-'}  产品：{pr or '-'}**"
        lines.append(header)
        for u in uploads_in_group:
            links = u.get_template_links_list() or []
            link = links[0] if links else None
            due = u.due_date.strftime("%Y-%m-%d") if u.due_date else "-"
            due_red = f'<font color="red">{due}</font>' if due != "-" else "-"
            file_label = u.file_name or "-"
            if u.task_type:
                file_label += f" ({u.task_type})"
            fv = getattr(u, "file_version", None) or "-"
            ddd = (u.document_display_date.strftime("%Y-%m-%d") if u.document_display_date else "-") if getattr(u, "document_display_date", None) else "-"
            rev = getattr(u, "reviewer", None) or "-"
            appr = getattr(u, "approver", None) or "-"
            line = f" - 文件名称：{file_label}  文件版本号：{fv}  截止日期：{due_red}  文档体现日期：{ddd}  审核：{rev}  批准：{appr}"
            if link:
                line += f"  文档地址：[点击打开]({link})"
            lines.append(line)
        return "\n".join(lines)
    
    task_list = "\n\n".join(
        _task_block_md(k, grp) for k, grp in groups.items()
    )
    
    base_url = _get_base_url()
    page2_path = url_for("pages.generate_page", _external=False)
    page2_url = f"{base_url}{page2_path}" if base_url else url_for("pages.generate_page", _external=True)
    
    template = _get_notify_template("author_reminder")
    if not template:
        template = "【个人任务催办】\n致：{author}\n您有 {pending_count} 个任务待完成：\n{task_list}\n\n请抓紧处理！"
    
    message = template.format(
        author=author,
        pending_count=len(pending_uploads),
        task_list=task_list,
        page2_url=page2_url,
    )
    message = message.rstrip()
    if not message.endswith("请抓紧处理！"):
        message += "\n\n请抓紧处理！"
    message += f"\n\n页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）\n\n### **编写完成后请在页面2中标记完成状态。**"
    
    at_mobiles = _resolve_mobiles_for_authors([author])
    result = dingtalk_service.send_markdown_message(
        "个人任务催办",
        message,
        at_all=False,
        at_mobiles=at_mobiles,
        at_names=[author],
        webhook=webhook,
        secret=secret,
    )
    ok = result is not None and result.get("success") is True
    if ok:
        return jsonify({"success": True, "message": "通知发送成功", "atNames": [str(author)]}), 200
    err = result.get("error", "未知错误") if result else "未知错误"
    if isinstance(err, dict):
        err = "未知错误"
    return jsonify({"success": False, "message": f"通知发送失败: {err}"}), 200


@bp.post("/api/notify/single-task")
@page13_access_required
def api_notify_single_task():
    """单条任务推送钉钉通知"""
    data = request.get_json(force=True) or {}
    upload_id = data.get("uploadId")
    
    if not upload_id:
        return jsonify({"message": "请提供任务ID"}), 400
    
    webhook = _dingtalk_webhook_str()
    secret = _dingtalk_secret_opt()
    
    if not webhook:
        return jsonify({"message": "未配置钉钉 Webhook，请在页面3「系统配置」中填写"}), 400
    
    upload = UploadRecord.query.get(upload_id)
    if not upload:
        return jsonify({"message": "未找到该任务"}), 404
    
    if upload.completion_status:
        return jsonify({"message": "该任务已完成，无需催办"})
    
    doc_link = ""
    if upload.template_links:
        links = upload.get_template_links_list()
        if links:
            doc_link = links[0]
    due_date_str = upload.due_date.strftime("%Y-%m-%d") if upload.due_date else "-"
    due_red = f'<font color="red">{due_date_str}</font>' if due_date_str != "-" else "-"
    business_side = upload.business_side or "-"
    product = upload.product or "-"
    country = upload.country or "-"
    project_code = getattr(upload, "project_code", None) or "-"
    file_version = getattr(upload, "file_version", None) or "-"
    doc_display_date = (upload.document_display_date.strftime("%Y-%m-%d") if upload.document_display_date else "-") if getattr(upload, "document_display_date", None) else "-"
    reviewer = getattr(upload, "reviewer", None) or "-"
    approver = getattr(upload, "approver", None) or "-"
    project_notes = getattr(upload, "project_notes", None) or "-"
    title = f"{upload.project_name}/{upload.file_name}" + (f" ({upload.task_type})" if upload.task_type else "")
    doc_link_md = f"[点击打开]({doc_link})" if doc_link else "（无链接）"

    template = _get_notify_template("single_task_reminder")
    if not template:
        template = (
            "【任务催办】\n致：{author}\n\n"
            "- **{title}**\n"
            " - 截止日期：{due_date}\n"
            " - 影响业务方：{business_side}\n"
            " - 产品：{product}\n"
            " - 国家：{country}\n"
            " - 文档地址：{doc_link_md}\n\n"
            "请抓紧处理！"
        )

    base_url = _get_base_url()
    page2_path = url_for("pages.generate_page", _external=False)
    page2_url = f"{base_url}{page2_path}" if base_url else url_for("pages.generate_page", _external=True)

    message_plain = template.format(
        author=upload.author,
        project_name=upload.project_name,
        file_name=upload.file_name,
        task_type=upload.task_type or "-",
        title=title,
        due_date=due_red,
        business_side=business_side,
        product=product,
        country=country,
        project_code=project_code,
        project_notes=project_notes,
        file_version=file_version,
        document_display_date=doc_display_date,
        reviewer=reviewer,
        approver=approver,
        doc_link_md=doc_link_md,
        doc_link=doc_link_md,
        page2_url=page2_url,
    )
    message_plain = message_plain.rstrip()
    if not message_plain.endswith("请抓紧处理！"):
        message_plain += "\n\n请抓紧处理！"
    message_plain += f"\n\n页面2（我的任务）：[点击打开]({page2_url})（账号为中文姓名，密码默认为姓名拼音首字母123456。如毛应森，mys123456）\n\n### **编写完成后请在页面2中标记完成状态。**"
    
    at_mobiles = _resolve_mobiles_for_authors([upload.author])
    result = dingtalk_service.send_markdown_message(
        "任务催办",
        message_plain,
        at_all=False,
        at_mobiles=at_mobiles,
        at_names=[upload.author],
        webhook=webhook,
        secret=secret,
    )
    ok = result is not None and result.get("success") is True
    if ok:
        return jsonify({"success": True, "message": "通知发送成功", "atNames": [str(upload.author)]}), 200
    err = result.get("error", "未知错误") if result else "未知错误"
    if isinstance(err, dict):
        err = "未知错误"
    return jsonify({"success": False, "message": f"通知发送失败: {err}"}), 200


@bp.get("/api/notify/next-schedule")
@page13_access_required
def api_notify_next_schedule():
    """获取下一次自动通知时间（使用统计页配置的定时）"""
    from . import scheduler_service
    from .scheduler import _get_schedule_config_from_db
    cfg = _get_schedule_config_from_db()
    next_times = scheduler_service.get_next_run_times(cfg)
    
    webhook = _dingtalk_webhook_str()
    next_times["dingtalkConfigured"] = bool(webhook)
    
    return jsonify(next_times)


@bp.get("/api/notify/schedule-config")
@page13_access_required
def api_get_schedule_config():
    """获取自动通知时间配置（统计页用）"""
    from .scheduler import _get_schedule_config_from_db
    cfg = _get_schedule_config_from_db()
    row = AppConfig.query.filter_by(config_key="MODULE_CASCADE_DELAY_MINUTES").first()
    delay_minutes = 5
    if row and row.config_value:
        try:
            delay_minutes = max(1, min(1440, int(str(row.config_value).strip())))
        except ValueError:
            pass
    return jsonify({
        "weekly": cfg["weekly"],
        "overdue": cfg["overdue"],
        "project": cfg["project"],
        "moduleCascadeDelayMinutes": delay_minutes,
    })


@bp.put("/api/notify/schedule-config")
@page13_access_required
def api_put_schedule_config():
    """保存自动通知时间配置并立即生效"""
    data = request.get_json() or {}
    weekly = (data.get("weekly") or "").strip() or "thu 16:00"
    overdue = (data.get("overdue") or "").strip() or "15:00"
    project = (data.get("project") or "").strip() or "mon,wed,fri 9:30"
    delay_minutes = 5
    if "moduleCascadeDelayMinutes" in data:
        try:
            delay_minutes = max(1, min(1440, int(data.get("moduleCascadeDelayMinutes", 5))))
        except (TypeError, ValueError):
            pass
    for key, value in [
        ("SCHEDULE_WEEKLY_REMINDER", weekly),
        ("SCHEDULE_OVERDUE_REMINDER", overdue),
        ("SCHEDULE_PROJECT_STATS", project),
        ("MODULE_CASCADE_DELAY_MINUTES", str(delay_minutes)),
    ]:
        row = AppConfig.query.filter_by(config_key=key).first()
        if row:
            row.config_value = value
        else:
            db.session.add(AppConfig(config_key=key, config_value=value))
    db.session.commit()
    try:
        from .scheduler import reschedule_jobs
        reschedule_jobs(current_app._get_current_object())
    except Exception:
        pass
    return jsonify({"success": True, "message": "已保存并已更新定时任务"})


@bp.get("/api/system-settings")
@page13_access_required
def api_get_system_settings():
    """系统配置：默认带出当前生效值（已通过页面1/3 校验；数据库 URI 脱敏）。"""
    from .app_settings import (
        SYSTEM_CONFIG_KEYS,
        persist_config_json_into_empty_db_keys,
        sync_authoritative_sources_into_db,
        system_settings_for_api_get,
    )

    app = current_app._get_current_object()
    project_root = Path(app.root_path).resolve().parent
    sync_authoritative_sources_into_db(project_root, app)
    persist_config_json_into_empty_db_keys(project_root, app)
    keys_meta = [{"key": k, "label": lbl, "sensitive": sens} for k, lbl, sens in SYSTEM_CONFIG_KEYS]
    return jsonify(
        {"settings": system_settings_for_api_get(app, project_root), "keys": keys_meta}
    )


@bp.put("/api/system-settings")
@page13_access_required
def api_put_system_settings():
    """保存系统配置并刷新当前进程 app.config（数据库连接 URI 需重启后生效）。"""
    body = request.get_json(force=True) or {}
    project_root = Path(current_app.root_path).resolve().parent
    from .app_settings import apply_system_settings_to_flask, save_system_settings

    save_system_settings({str(k): ("" if v is None else str(v)) for k, v in body.items()}, project_root)
    apply_system_settings_to_flask(current_app._get_current_object(), project_root)
    return jsonify({"success": True, "message": "已保存。若修改了数据库连接 URI，请重启服务后生效。"})


@bp.get("/api/notify/module-cascade-status")
@page13_access_required
def api_module_cascade_status():
    """模块级联催办状态：可配置延迟分钟数、待执行列表、最近已执行列表。"""
    row = AppConfig.query.filter_by(config_key="MODULE_CASCADE_DELAY_MINUTES").first()
    delay_minutes = 5
    if row and row.config_value:
        try:
            delay_minutes = max(1, min(1440, int(str(row.config_value).strip())))
        except ValueError:
            pass
    pending = ModuleCascadeReminder.query.filter_by(status="pending").order_by(ModuleCascadeReminder.run_at).all()
    recent_sent = (
        ModuleCascadeReminder.query.filter_by(status="sent")
        .order_by(ModuleCascadeReminder.sent_at.desc())
        .limit(20)
        .all()
    )
    return jsonify({
        "delayMinutes": delay_minutes,
        "pending": [
            {
                "projectName": r.project_name,
                "triggerModule": r.trigger_module,
                "targetModule": r.target_module,
                "runAt": r.run_at.strftime("%Y-%m-%d %H:%M") if r.run_at else None,
            }
            for r in pending
        ],
        "recentSent": [
            {
                "projectName": r.project_name,
                "triggerModule": r.trigger_module,
                "targetModule": r.target_module,
                "sentAt": r.sent_at.strftime("%Y-%m-%d %H:%M") if r.sent_at else None,
            }
            for r in recent_sent
        ],
    })


@bp.post("/api/notify/module-cascade-manual")
@page13_access_required
def api_notify_module_cascade_manual():
    """手动模块级联催办：按项目检查，产品全部完成→催办开发；开发全部完成→催办测试。body 可传 projectName 仅处理该项目。"""
    webhook = _dingtalk_webhook_str()
    if not webhook:
        return jsonify({"success": False, "message": "未配置钉钉 Webhook，请在页面3「系统配置」填写"}), 400
    data = request.get_json(silent=True) or {}
    project_name = (data.get("projectName") or "").strip() or None
    try:
        from .scheduler import _run_module_cascade_manual
        _run_module_cascade_manual(project_name=project_name)
        if project_name:
            return jsonify({"success": True, "message": f"已执行「{project_name}」的模块级联催办"})
        return jsonify({"success": True, "message": "已执行模块级联催办（按项目：产品→开发、开发→测试）"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@bp.post("/api/notify/test-auto")
@page13_access_required
def api_notify_test_auto():
    """测试自动催办：按类型执行与定时任务完全相同的逻辑，仅时间提前到点击时。"""
    webhook = _dingtalk_webhook_str()
    if not webhook:
        return jsonify({
            "success": False,
            "webhook_configured": False,
            "message": "未配置钉钉 Webhook，请在页面3「系统配置」填写",
        }), 400

    payload = request.get_json(silent=True) or {}
    test_type = (payload.get("type") or "").strip().lower()

    if test_type == "thursday":
        from .scheduler import _run_thursday_reminder
        _run_thursday_reminder(skip_dedupe=True)
        return jsonify({
            "success": True,
            "webhook_configured": True,
            "message": "已按定时任务逻辑发送（每周任务完成提醒）",
            "type": test_type,
        })
    if test_type == "overdue":
        from .scheduler import _run_overdue_reminder
        res = _run_overdue_reminder(skip_dedupe=True)
        if res is None:
            return jsonify({
                "success": False,
                "webhook_configured": True,
                "message": "执行异常",
                "type": test_type,
            })
        if res.get("no_tasks"):
            return jsonify({
                "success": True,
                "webhook_configured": True,
                "message": "无明日截止任务，未发送",
                "type": test_type,
            })
        sent, failed = res.get("sent") or 0, res.get("failed") or 0
        if failed > 0 or sent == 0:
            err = res.get("last_error") or "钉钉未返回成功"
            return jsonify({
                "success": False,
                "webhook_configured": True,
                "message": f"发送失败：{err}" + (f"（成功 {sent} 条，失败 {failed} 条）" if sent else ""),
                "type": test_type,
            })
        return jsonify({
            "success": True,
            "webhook_configured": True,
            "message": f"已发送 {sent} 条逾期提醒",
            "type": test_type,
        })
    if test_type == "project_stats":
        from .scheduler import _run_project_stats
        _run_project_stats(skip_dedupe=True)
        return jsonify({
            "success": True,
            "webhook_configured": True,
            "message": "已按定时任务逻辑发送（每两天项目完成情况统计）",
            "type": test_type,
        })
    if test_type == "module_cascade":
        from .scheduler import _run_process_module_cascade_pending
        _run_process_module_cascade_pending()
        return jsonify({
            "success": True,
            "webhook_configured": True,
            "message": "已处理到期的模块级联催办（按项目：产品完成→催办开发；开发完成→催办测试）",
            "type": test_type,
        })

    from . import dingtalk_service
    secret = _dingtalk_secret_opt()
    content = "【自动催办测试】通道正常。定时任务将按配置时间发送每周任务完成提醒、逾期前一日催告、每两天项目完成情况统计。"
    result = dingtalk_service.send_text_message(content, webhook=webhook, secret=secret)
    ok = result.get("success") is True
    errmsg = result.get("error") or ""
    return jsonify({
        "success": ok,
        "webhook_configured": True,
        "message": "测试消息已发送" if ok else (errmsg or "钉钉返回失败，请检查 Webhook/Secret 及网络"),
        "type": test_type or "default",
    })


def register_blueprint(app):
    app.register_blueprint(bp)
