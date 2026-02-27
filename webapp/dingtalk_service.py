# -*- coding: utf-8 -*-
"""
钉钉群机器人 Webhook 通知服务。
用于：任务分配通知、周四完成情况提醒、逾期前一日催告、每两日项目完成统计。
"""
from __future__ import annotations

import logging
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from urllib.parse import quote

logger = logging.getLogger(__name__)


def _sign(secret: str) -> tuple[str, str]:
    """钉钉加签：timestamp + \\n + secret 做 HMAC-SHA256 后 Base64 再 URL 编码。"""
    timestamp = str(round(time.time() * 1000))
    secret_enc = secret.encode("utf-8")
    string_to_sign = f"{timestamp}\n{secret}"
    string_to_sign_enc = string_to_sign.encode("utf-8")
    hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
    sign_b64 = base64.b64encode(hmac_code).decode("utf-8")
    sign = quote(sign_b64, safe="")
    return timestamp, sign


def _get_webhook_url(webhook: str, secret: Optional[str]) -> str:
    if not secret or not secret.strip():
        return webhook
    ts, sign = _sign(secret.strip())
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={ts}&sign={sign}"


def send_text(
    content: str,
    at_mobiles: Optional[List[str]] = None,
    at_all: bool = False,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
) -> bool:
    """
    发送文本消息到钉钉群。
    :param content: 文本内容
    :param at_mobiles: 被 @ 的手机号列表
    :param at_all: 是否 @ 所有人
    :param webhook: 机器人 webhook URL，不传则从环境变量 DINGTALK_WEBHOOK 读取
    :param secret: 机器人加签密钥，不传则从环境变量 DINGTALK_SECRET 读取
    :return: 是否发送成功
    """
    url = webhook or os.environ.get("DINGTALK_WEBHOOK")
    if not url or not url.strip():
        return False
    secret = secret or os.environ.get("DINGTALK_SECRET")
    url = _get_webhook_url(url.strip(), secret)
    body: dict[str, Any] = {
        "msgtype": "text",
        "text": {"content": content},
        "at": {"atMobiles": at_mobiles or [], "isAtAll": at_all},
    }
    try:
        req = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("errcode") == 0
    except (URLError, HTTPError, Exception) as e:
        logger.warning("钉钉 send_text 发送失败: %s", e)
        return False


def send_text_message(
    content: str,
    at_mobiles: Optional[List[str]] = None,
    at_names: Optional[List[str]] = None,
    at_all: bool = False,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
) -> dict:
    """
    发送文本消息（返回详细结果）。
    :param at_names: 被 @ 的用户名列表（直接用姓名@）
    """
    url = webhook or os.environ.get("DINGTALK_WEBHOOK")
    if not url or not str(url).strip():
        return {"success": False, "error": "未配置钉钉 Webhook"}
    url = str(url).strip()
    secret = secret or os.environ.get("DINGTALK_SECRET")
    secret = secret.strip() if secret else None
    url = _get_webhook_url(url, secret)
    
    final_content = content
    if at_names:
        at_mentions = " ".join([f"@{name}" for name in at_names])
        if at_mentions not in content:
            final_content = f"{content}\n{at_mentions}"
    
    body: dict[str, Any] = {
        "msgtype": "text",
        "text": {"content": final_content},
        "at": {"atMobiles": at_mobiles or [], "isAtAll": at_all},
    }
    try:
        req = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            result = json.loads(raw) if raw else {}
            errcode = result.get("errcode")
            if errcode == 0 or errcode == "0":
                return {"success": True}
            if result.get("success") is True:
                return {"success": True}
            errmsg = result.get("errmsg") or result.get("error") or str(result) or "未知错误"
            if isinstance(errmsg, dict):
                errmsg = "未知错误"
            return {"success": False, "error": errmsg}
    except HTTPError as e:
        errmsg = "未知错误"
        try:
            raw = e.read().decode("utf-8")
            result = json.loads(raw) if raw else {}
            errmsg = result.get("errmsg") or result.get("error") or raw or str(e)
        except Exception:
            errmsg = str(e)
        return {"success": False, "error": errmsg}
    except URLError as e:
        return {"success": False, "error": f"网络请求失败: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_markdown_message(
    title: str,
    text: str,
    at_mobiles: Optional[List[str]] = None,
    at_names: Optional[List[str]] = None,
    at_all: bool = False,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
) -> dict:
    """发送 Markdown 消息，返回与 send_text_message 相同结构。支持 @ 和 atMobiles。"""
    url = webhook or os.environ.get("DINGTALK_WEBHOOK")
    if not url or not str(url).strip():
        return {"success": False, "error": "未配置钉钉 Webhook"}
    url = str(url).strip()
    secret = secret or os.environ.get("DINGTALK_SECRET")
    secret = secret.strip() if secret else None
    url = _get_webhook_url(url, secret)
    if at_mobiles:
        at_mobile_mentions = " ".join([f"@{m}" for m in at_mobiles])
        if at_mobile_mentions not in text and not any(f"@{m}" in text for m in at_mobiles):
            text = text + "\n\n" + at_mobile_mentions
    elif at_names:
        at_mentions = " ".join([f"@{name}" for name in at_names])
        if at_mentions not in text and not any(f"@{name}" in text for name in at_names):
            text = text + "\n\n" + at_mentions
    body: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"atMobiles": at_mobiles or [], "isAtAll": at_all},
    }
    try:
        req = Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            result = json.loads(raw) if raw else {}
            errcode = result.get("errcode")
            if errcode == 0 or errcode == "0":
                return {"success": True}
            if result.get("success") is True:
                return {"success": True}
            errmsg = result.get("errmsg") or result.get("error") or str(result) or "未知错误"
            if isinstance(errmsg, dict):
                errmsg = "未知错误"
            return {"success": False, "error": errmsg}
    except HTTPError as e:
        errmsg = "未知错误"
        try:
            raw = e.read().decode("utf-8")
            result = json.loads(raw) if raw else {}
            errmsg = result.get("errmsg") or result.get("error") or raw or str(e)
        except Exception:
            errmsg = str(e)
        return {"success": False, "error": errmsg}
    except URLError as e:
        return {"success": False, "error": f"网络请求失败: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def send_markdown(
    title: str,
    text: str,
    at_mobiles: Optional[List[str]] = None,
    at_all: bool = False,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
) -> bool:
    """发送 Markdown 消息。"""
    url = webhook or os.environ.get("DINGTALK_WEBHOOK")
    if not url or not url.strip():
        return False
    secret = secret or os.environ.get("DINGTALK_SECRET")
    url = _get_webhook_url(url.strip(), secret)
    body = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
        "at": {"atMobiles": at_mobiles or [], "isAtAll": at_all},
    }
    try:
        req = Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode())
            return result.get("errcode") == 0
    except (URLError, HTTPError, Exception):
        return False


def notify_task_assigned(
    assignee_name: str,
    task_title: str,
    due_date_str: str,
    template_source: str,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
) -> bool:
    """任务分配通知：提醒被分配人（使用姓名@）。"""
    content = (
        f"【任务分配】\n"
        f"@{assignee_name} 您有新的任务：{task_title}\n"
        f"截止日期：{due_date_str}\n"
        f"模板来源：{template_source}\n"
        f"请及时完成并更新状态。"
    )
    return send_text(content, webhook=webhook, secret=secret)


def notify_thursday_reminder(
    lines: List[str],
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
) -> bool:
    """每周 16:00 任务完成情况提醒。"""
    if not lines:
        return True
    content = "【每周任务完成提醒】\n\n" + "\n".join(lines)
    return send_text(content, webhook=webhook, secret=secret)


def notify_overdue_reminder(
    assignee_name: str,
    task_title: str,
    due_date_str: str,
    business_side: Optional[str] = None,
    product: Optional[str] = None,
    country: Optional[str] = None,
    doc_link: Optional[str] = None,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
) -> bool:
    """逾期前一日 15:00 催告（使用姓名@）。参考单个任务催办，含影响业务方、产品、国家、文档地址。"""
    parts = [
        "【任务即将到期】",
        f"@{assignee_name} 任务：{task_title}",
        f"截止日期：{due_date_str}",
    ]
    if business_side or product or country:
        extras = []
        if business_side:
            extras.append(f"影响业务方：{business_side}")
        if product:
            extras.append(f"产品：{product}")
        if country:
            extras.append(f"国家：{country}")
        if extras:
            parts.append(" ".join(extras))
    if doc_link:
        parts.append(f"文档地址：{doc_link}")
    parts.append("请尽快完成。")
    content = "\n".join(parts)
    return send_text(content, webhook=webhook, secret=secret)


def notify_project_stats_every_two_days(
    stats_text: str,
    webhook: Optional[str] = None,
    secret: Optional[str] = None,
) -> bool:
    """每两天在钉钉群统计所有项目完成情况。"""
    content = "【每两天项目完成情况统计】\n\n" + stats_text
    return send_text(content, webhook=webhook, secret=secret)


def send_work_notification_to_mobiles(
    title: str,
    text: str,
    mobiles: List[str],
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> dict:
    """通过钉钉工作通知 API 发到个人。需配置 DINGTALK_APP_KEY、DINGTALK_APP_SECRET、DINGTALK_AGENT_ID。"""
    app_key = (app_key or os.environ.get("DINGTALK_APP_KEY") or "").strip()
    app_secret = (app_secret or os.environ.get("DINGTALK_APP_SECRET") or "").strip()
    agent_id = (agent_id or os.environ.get("DINGTALK_AGENT_ID") or "").strip()
    if not app_key or not app_secret or not agent_id or not mobiles:
        return {"success": False, "error": "未配置工作通知或无手机号"}
    try:
        token_url = f"https://oapi.dingtalk.com/gettoken?appkey={quote(app_key)}&appsecret={quote(app_secret)}"
        with urlopen(Request(token_url, method="GET"), timeout=10) as resp:
            token_res = json.loads(resp.read().decode())
        if token_res.get("errcode") != 0:
            return {"success": False, "error": token_res.get("errmsg", "获取token失败")}
        access_token = token_res.get("access_token", "")
        userids: List[str] = []
        for mobile in mobiles:
            m = (mobile or "").strip()
            if not m:
                continue
            get_user_url = f"https://oapi.dingtalk.com/topapi/v2/user/getbymobile?access_token={access_token}"
            req = Request(get_user_url, data=json.dumps({"mobile": m}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=10) as resp:
                user_res = json.loads(resp.read().decode())
            if user_res.get("errcode") == 0 and user_res.get("result", {}).get("userid"):
                userids.append(user_res["result"]["userid"])
        if not userids:
            return {"success": False, "error": "未根据手机号查到对应用户"}
        send_url = f"https://oapi.dingtalk.com/topapi/message/corpconversation/asyncsend_v2?access_token={access_token}"
        payload = {"agent_id": agent_id, "userid_list": ",".join(userids), "msg": {"msgtype": "markdown", "markdown": {"title": title, "text": text}}}
        req = Request(send_url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
        with urlopen(req, timeout=10) as resp:
            send_res = json.loads(resp.read().decode())
        if send_res.get("errcode") == 0 or send_res.get("task_id"):
            return {"success": True}
        return {"success": False, "error": send_res.get("errmsg", "发送失败")}
    except Exception as e:
        return {"success": False, "error": str(e)}
