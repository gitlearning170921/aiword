# -*- coding: utf-8 -*-
"""
FTP 文件存储（主动模式）。

约定：
- 只负责「上传/下载/删除」字节与文件，业务端决定远端路径组织规则。
- 默认使用主动模式（PASV=False）。
- 连接信息：优先 ``app_settings``/``config.json``/环境变量（``_merged_ftp_str``），再与 ``runtime_settings`` 合并；避免仅后者空值导致误判「未配置 FTP」。
- aiword 默认应用目录名为 ``aiword``（与 aiprintword 的 ``aiprintword`` 区分，同 FTP 父目录下分路径）。
"""

from __future__ import annotations

import io
import logging
import os
import posixpath
from contextlib import contextmanager
from typing import Iterator, Optional, Tuple

_log = logging.getLogger(__name__)


def _ftp_setting_raw(key: str) -> str:
    """
    读取单条 FTP 配置：有 Flask 应用上下文时走 app_settings（含项目根 config.json 与 os.environ 合并），否则仅环境变量。
    与页面1/3 系统配置同源；使用 has_app_context（非仅 request），避免仅有 app 上下文时读不到库/config。
    """
    try:
        from flask import has_app_context

        if has_app_context():
            from .app_settings import get_setting

            v = (get_setting(key, default="") or "").strip()
            if v:
                return v
    except Exception:
        pass
    return (os.environ.get(key) or "").strip()


def _merged_ftp_str(key: str, default: str = "") -> str:
    """config.json / 库内系统设置 优先于 runtime_settings，避免后者空值盖住项目 FTP 配置。"""
    v = (_ftp_setting_raw(key) or "").strip()
    if v:
        return v
    try:
        from runtime_settings.resolve import get_setting

        rv = get_setting(key)
        if rv is not None and str(rv).strip():
            return str(rv).strip()
    except Exception:
        pass
    return (default or "").strip()


def _cfg_pasv() -> Optional[bool]:
    pr = (_ftp_setting_raw("FTP_PASV") or os.environ.get("FTP_PASSIVE") or "").strip().lower()
    if pr in ("1", "true", "yes", "y", "on"):
        return True
    if pr in ("0", "false", "no", "n", "off"):
        return False
    if pr:
        return None
    try:
        from runtime_settings.resolve import get_setting

        pv = get_setting("FTP_PASV")
        if pv is None:
            return None
        return bool(pv)
    except Exception:
        return None


def ftp_upload_configured() -> bool:
    """是否配置了 FTP 主机（有配置才尝试上传）。"""
    return bool((_merged_ftp_str("FTP_HOST", "") or "").strip())


def _short_ftp_err(e: BaseException) -> str:
    s = str(e or "").strip() or type(e).__name__
    if len(s) > 480:
        return s[:477] + "…"
    return s


def try_upload_bytes(data: bytes, remote_rel_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    优先上传 bytes 到 FTP。
    返回 (远端绝对路径, 错误说明)：
    - 成功：(path, None)
    - 未配置 FTP：(None, None) — 调用方直接走 MySQL/本地，不记为失败
    - 失败：(None, 简短错误信息)
    """
    if data is None:
        return None, "data 为空"
    if not ftp_upload_configured():
        _log.info(
            "FTP 上传已跳过：未检测到有效 FTP_HOST（相对路径=%r，约 %s 字节）。"
            "请在 config.json、环境变量或页面 3 系统配置中填写 FTP_HOST/FTP_PORT/FTP_USER/FTP_PASSWORD 等。",
            remote_rel_path,
            len(data),
        )
        return None, None
    try:
        remote_abs = upload_bytes(data, remote_rel_path)
        return remote_abs, None
    except Exception as e:
        try:
            host, port, user, _pwd, base_dir, _pasv = _cfg()
            ctx = "host=%r port=%s user=%r base_dir=%r" % (host, port, user, base_dir)
        except Exception:
            ctx = "cfg_unavailable"
        _log.warning(
            "FTP 上传失败 remote_rel_path=%r %s: %s",
            remote_rel_path,
            ctx,
            _short_ftp_err(e),
            exc_info=_log.isEnabledFor(logging.DEBUG),
        )
        return None, _short_ftp_err(e)


def try_upload_file(local_path: str, remote_rel_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    上传本地文件到 FTP；返回值语义同 try_upload_bytes。
    """
    if not ftp_upload_configured():
        _log.info(
            "FTP 上传已跳过（本地文件）：FTP_HOST 未配置 remote_rel_path=%r local_path=%r",
            remote_rel_path,
            local_path,
        )
        return None, None
    try:
        remote_abs = upload_file(local_path, remote_rel_path)
        return remote_abs, None
    except Exception as e:
        try:
            host, port, user, _pwd, base_dir, _pasv = _cfg()
            ctx = "host=%r port=%s user=%r base_dir=%r" % (host, port, user, base_dir)
        except Exception:
            ctx = "cfg_unavailable"
        _log.warning(
            "FTP 上传失败（本地文件）remote_rel_path=%r local_path=%r %s: %s",
            remote_rel_path,
            local_path,
            ctx,
            _short_ftp_err(e),
            exc_info=_log.isEnabledFor(logging.DEBUG),
        )
        return None, _short_ftp_err(e)


def remote_file_exists(remote_rel_path: str) -> bool:
    """
    远端是否已存在该相对路径文件（相对 FTP_APP_DIR）。
    使用 SIZE；部分服务器不支持时返回 False。
    """
    if not ftp_upload_configured():
        return False
    remote_abs = _join_base(remote_rel_path)
    remote_dir = posixpath.dirname(remote_abs)
    base = posixpath.basename(remote_abs)
    if not base:
        return False
    try:
        with _ftp() as ftp:
            try:
                ftp.voidcmd("TYPE I")
            except Exception:
                pass
            try:
                ftp.cwd(remote_dir)
            except Exception:
                return False
            try:
                if ftp.size(base) is None:
                    return False
                return True
            except Exception:
                return False
    except Exception:
        return False


def _cfg() -> Tuple[str, int, str, str, str, Optional[bool]]:
    host = (_merged_ftp_str("FTP_HOST", "10.26.1.221") or "10.26.1.221").strip()
    port_s = (_merged_ftp_str("FTP_PORT", "2121") or "2121").strip()
    user = (_merged_ftp_str("FTP_USER", "aiwordftpuser") or "aiwordftpuser").strip()
    pwd = (_merged_ftp_str("FTP_PASSWORD", "") or os.environ.get("FTP_PASS") or "").strip()
    parent_dir = (_merged_ftp_str("FTP_BASE_DIR", "/upload") or "/upload").strip() or "/upload"
    app_dir = (_merged_ftp_str("FTP_APP_DIR", "aiword") or "aiword").strip().strip("/") or "aiword"
    pasv = _cfg_pasv()
    try:
        port = int(str(port_s).strip() or "2121")
    except Exception:
        port = 2121
    if not parent_dir.startswith("/"):
        parent_dir = "/" + parent_dir
    app_dir = (app_dir or "aiword").strip().strip("/") or "aiword"
    base_dir = posixpath.join(parent_dir, app_dir)
    return host, port, user, pwd, base_dir, pasv


@contextmanager
def _ftp(*, pasv: Optional[bool] = None) -> Iterator["FTP"]:
    from ftplib import FTP

    host, port, user, pwd, _, cfg_pasv = _cfg()
    if pasv is None:
        pasv = cfg_pasv
    try:
        ftp = FTP(encoding="utf-8")
    except TypeError:
        ftp = FTP()
    ftp.connect(host=host, port=port, timeout=20)
    if pasv is not None:
        try:
            ftp.set_pasv(bool(pasv))
        except Exception:
            pass
    else:
        try:
            ftp.set_pasv(False)
        except Exception:
            pass
    ftp.login(user=user, passwd=pwd)
    try:
        yield ftp
    finally:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass


def _ensure_remote_dirs(ftp, remote_dir: str) -> None:
    parts = [p for p in remote_dir.strip("/").split("/") if p]
    cur = ""
    for p in parts:
        cur = cur + "/" + p
        try:
            ftp.mkd(cur)
        except Exception:
            pass


def _join_base(rel_path: str) -> str:
    _, _, _, _, base_dir, _ = _cfg()
    rp = rel_path.replace("\\", "/").lstrip("/")
    return posixpath.join(base_dir, rp)


def _should_retry_with_passive(e: Exception) -> bool:
    msg = str(e or "")
    if not msg:
        return False
    return any(
        x in msg
        for x in (
            "425",
            "Can't open data connection",
            "Data connection",
            "timed out",
            "timeout",
            "Connection refused",
        )
    )


def _should_retry_active_after_passive_server_error(e: Exception) -> bool:
    msg = (str(e or "") or "").lower()
    if not msg:
        return False
    return "vsf_sysutil_bind" in msg or "500 oops" in msg


def upload_bytes(data: bytes, remote_rel_path: str) -> str:
    if data is None:
        raise ValueError("data is None")
    remote_abs = _join_base(remote_rel_path)
    remote_dir = posixpath.dirname(remote_abs)

    def _stor(pasv_override: Optional[bool]) -> None:
        with _ftp(pasv=pasv_override) as ftp:
            _ensure_remote_dirs(ftp, remote_dir)
            bio = io.BytesIO(data)
            ftp.storbinary("STOR " + remote_abs, bio)

    try:
        _stor(None)
    except Exception as e:
        _, _, _, _, _, cfg_pasv = _cfg()
        if cfg_pasv is None and _should_retry_with_passive(e):
            try:
                _stor(True)
            except Exception as e2:
                if _should_retry_active_after_passive_server_error(e2):
                    _stor(False)
                else:
                    raise
        elif cfg_pasv is True and _should_retry_active_after_passive_server_error(e):
            _stor(False)
        else:
            raise
    return remote_abs


def upload_file(local_path: str, remote_rel_path: str) -> str:
    lp = os.path.abspath(local_path)
    if not os.path.isfile(lp):
        raise FileNotFoundError(lp)
    remote_abs = _join_base(remote_rel_path)
    remote_dir = posixpath.dirname(remote_abs)

    def _stor_file(pasv_override: Optional[bool]) -> None:
        with _ftp(pasv=pasv_override) as ftp:
            _ensure_remote_dirs(ftp, remote_dir)
            with open(lp, "rb") as f:
                ftp.storbinary("STOR " + remote_abs, f)

    try:
        _stor_file(None)
    except Exception as e:
        _, _, _, _, _, cfg_pasv = _cfg()
        if cfg_pasv is None and _should_retry_with_passive(e):
            try:
                _stor_file(True)
            except Exception as e2:
                if _should_retry_active_after_passive_server_error(e2):
                    _stor_file(False)
                else:
                    raise
        elif cfg_pasv is True and _should_retry_active_after_passive_server_error(e):
            _stor_file(False)
        else:
            raise
    return remote_abs


def download_bytes(remote_abs_or_rel: str) -> bytes:
    p = (remote_abs_or_rel or "").strip()
    if not p:
        raise ValueError("remote path empty")
    if not p.startswith("/"):
        p = _join_base(p)
    buf = io.BytesIO()

    def _retr(pasv_override: Optional[bool]) -> None:
        with _ftp(pasv=pasv_override) as ftp:
            ftp.retrbinary("RETR " + p, buf.write)

    try:
        _retr(None)
    except Exception as e:
        _, _, _, _, _, cfg_pasv = _cfg()
        if cfg_pasv is None and _should_retry_with_passive(e):
            try:
                buf.seek(0)
                buf.truncate(0)
                _retr(True)
            except Exception as e2:
                if _should_retry_active_after_passive_server_error(e2):
                    buf.seek(0)
                    buf.truncate(0)
                    _retr(False)
                else:
                    raise
        elif cfg_pasv is True and _should_retry_active_after_passive_server_error(e):
            buf.seek(0)
            buf.truncate(0)
            _retr(False)
        else:
            raise
    return buf.getvalue()


def delete_path(remote_abs_or_rel: str) -> bool:
    p = (remote_abs_or_rel or "").strip()
    if not p:
        return False
    if not p.startswith("/"):
        p = _join_base(p)

    def _del(pasv_override: Optional[bool]) -> bool:
        with _ftp(pasv=pasv_override) as ftp:
            try:
                ftp.delete(p)
                return True
            except Exception:
                return False

    try:
        return _del(None)
    except Exception as e:
        _, _, _, _, _, cfg_pasv = _cfg()
        if cfg_pasv is None and _should_retry_with_passive(e):
            try:
                return _del(True)
            except Exception as e2:
                if _should_retry_active_after_passive_server_error(e2):
                    return _del(False)
                return False
        if cfg_pasv is True and _should_retry_active_after_passive_server_error(e):
            try:
                return _del(False)
            except Exception:
                return False
        return False
