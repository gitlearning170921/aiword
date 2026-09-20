#!/usr/bin/env python3
"""实拍当前 AI Word 前台界面，供项目介绍 PPT 使用。

需要本机已启动 Web：python run_web.py（默认 http://127.0.0.1:5000）
签发会话时从 instance/database_url.txt 读取与运行中服务相同的密钥，不打印密钥。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from urllib.request import urlopen


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


PREPARE_JS = """() => {
  const hide = (el) => { if (el) el.style.setProperty('display', 'none', 'important'); };
  hide(document.getElementById('appPageLoading'));
  document.body.classList.remove('app-page-booting', 'app-page-loading-active');
  [
    'feedbackFabBtn', 'globalScopeBarMount', 'userInfo', 'logoutBtn',
    'dg_interop_info', 'dg_bootstrap_loading', 'dg_msg', 'aud_msg', 'amod_msg', 'tr_msg',
    'examChromeProxyHint'
  ].forEach((id) => hide(document.getElementById(id)));
  const coll = document.getElementById('exam_collection_display');
  if (coll) hide(coll.parentElement);
  document.querySelectorAll('.global-session-cluster').forEach(hide);
  document.querySelectorAll('button, a').forEach((el) => {
    const t = (el.textContent || '').replace(/\\s+/g, '');
    if (t.includes('作用域诊断') || t.includes('退出超级') || t.includes('健康检查')) hide(el);
  });
  document.querySelectorAll('p.text-muted, p.small, .form-text').forEach((el) => {
    const t = el.textContent || '';
    if (/\\/api\\/integration|访问密码|AICHECKWORD_|collection[:：]|interop-config/.test(t) && t.length > 24) {
      hide(el);
    }
  });
  const llm = document.getElementById('dg_provider');
  if (llm) hide(llm.closest('.card'));
  document.querySelectorAll('input[type=password], input[id*="key" i], input[id*="secret" i], input[id*="token" i]').forEach((el) => {
    el.value = '';
    if (el.tagName === 'INPUT') el.type = 'password';
  });
  document.querySelectorAll('[placeholder]').forEach((el) => {
    el.placeholder = String(el.placeholder || '').replace(/aicheckword/gi, '系统');
  });
  const nav = document.querySelector('nav.navbar');
  if (nav) {
    nav.style.position = 'sticky';
    nav.style.top = '0';
    nav.style.zIndex = '4000';
  }
  const rewrite = (node) => {
    if (node.nodeType === 3) {
      node.nodeValue = node.nodeValue
        .replace(/页面\\d+(?:\\/\\d+)*/g, '')
        .replace(/aicheckword/gi, '文档服务')
        .replace(/AICHECKWORD_[A-Z0-9_]+/g, '系统配置')
        .replace(/interop-config/g, '对接配置');
      return;
    }
    if (node.nodeType !== 1) return;
    if (['SCRIPT', 'STYLE', 'NOSCRIPT'].includes(node.tagName)) return;
    [...node.childNodes].forEach(rewrite);
  };
  rewrite(document.body);
  document.querySelectorAll('.navbar-nav .nav-link, h1, h2').forEach((el) => {
    if (el.querySelector("button, input, select, a, .btn")) return;
    el.textContent = el.textContent
      .replace(/页面\\d+\\s*/g, '')
      .replace(/（文档服务）/g, '')
      .replace(/^[·\\-\\s]+/, '')
      .replace(/\\s+/g, ' ')
      .trim();
  });
}"""


REDACT_JS = r"""() => {
  const KEEP = /^(—|-|空|可选|不指定|未指定|全部|请选择|加载中|进行中|已结束|已下发|已完成|未完成|高|中|低|是|否|文件型|事项型|相关性|默认|英文|中文|deepseek|qwen-plus|pubmed|scholar|embase|cochrane|ce|fda|nmpa|ii|iia|iib|iii|single|未引用|已引用|刷新|编辑|删除|添加)$/i;
  const HEADER_RE = /项目名称|^项目$|所属公司|公司名称|注册负责人|^负责人$|编写人|编写人员|文件名称|影响产品|影响业务方|项目组|产品名称|产品类型|进度描述|地址|姓名|用户名|所属项目/;
  const FIELD_RE = /所属公司|关联项目|模板项目案例|产品名称|所属项目组|注册负责人|公司名称|地址|文档服务.?项目|选择已有项目/;
  const phrases = new Set();
  const add = (raw) => {
    const t = String(raw || '').replace(/\s+/g, ' ').trim();
    if (!t || t.length < 2 || KEEP.test(t)) return;
    if (/^\d+([./]\d+)*$/.test(t)) return;
    phrases.add(t);
    t.split(/[\n|;]/).forEach((p) => {
      const s = p.replace(/\s+/g, ' ').trim();
      if (s && s.length >= 2 && !KEEP.test(s)) phrases.add(s);
    });
  };

  const style = document.getElementById('pptx-redact-style') || document.createElement('style');
  style.id = 'pptx-redact-style';
  style.textContent = `
    .pptx-redact, .pptx-redact-box {
      background: repeating-linear-gradient(-45deg, #4b5563 0 6px, #6b7280 6px 12px) !important;
      color: transparent !important;
      text-shadow: none !important;
      filter: blur(7px);
      user-select: none !important;
      border-radius: 4px;
    }
    .pptx-redact-box { display: inline-block; min-width: 4rem; min-height: 1.1em; vertical-align: middle; }
    select.pptx-redact-box, input.pptx-redact-box, textarea.pptx-redact-box { min-height: 2rem; width: 100%; }
  `;
  document.head.appendChild(style);

  const fieldLabel = (el) => {
    if (el.id) {
      const lab = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (lab) return (lab.textContent || '').trim();
    }
    const wrap = el.closest('[class*="col-"], .mb-3, .mb-2, .form-group');
    if (wrap) {
      const lab = wrap.querySelector('label');
      if (lab) return (lab.textContent || '').trim();
    }
    const prev = el.previousElementSibling;
    if (prev && prev.tagName === 'LABEL') return (prev.textContent || '').trim();
    return '';
  };

  const redactTextIn = (el) => {
    el.querySelectorAll('input, select, textarea').forEach((ctl) => {
      add(ctl.value || (ctl.options && ctl.options[ctl.selectedIndex] && ctl.options[ctl.selectedIndex].text) || '');
      ctl.classList.add('pptx-redact-box');
    });
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) {
      const p = walker.currentNode.parentElement;
      if (!p || p.closest('button, a, .btn, .pptx-redact, .pptx-redact-box')) continue;
      nodes.push(walker.currentNode);
    }
    nodes.forEach((node) => {
      const t = (node.nodeValue || '').replace(/\s+/g, ' ').trim();
      if (!t || t === '—' || KEEP.test(t) || /^\d+$/.test(t)) return;
      add(t);
      const span = document.createElement('span');
      span.className = 'pptx-redact';
      span.textContent = node.nodeValue;
      node.parentNode.replaceChild(span, node);
    });
  };

  document.querySelectorAll('table').forEach((table) => {
    const headers = [...table.querySelectorAll('thead th, thead td')].map((h) =>
      (h.textContent || '').replace(/\s+/g, ' ').trim()
    );
    const idx = [];
    headers.forEach((h, i) => { if (HEADER_RE.test(h)) idx.push(i); });
    table.querySelectorAll('tbody tr').forEach((tr) => {
      const cells = [...tr.children];
      idx.forEach((i) => { if (cells[i]) redactTextIn(cells[i]); });
    });
  });

  document.querySelectorAll('select').forEach((sel) => {
    const opt = sel.options[sel.selectedIndex];
    const text = opt ? (opt.textContent || '').trim() : '';
    const lab = fieldLabel(sel);
    if (FIELD_RE.test(lab) && text && !/^请选择|^全部|^不指定|^加载/.test(text)) {
      add(text);
      sel.classList.add('pptx-redact-box');
    }
  });

  document.querySelectorAll('input:not([type=password]):not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=file]):not([type=number]), textarea').forEach((el) => {
    const v = (el.value || '').trim();
    const lab = fieldLabel(el) + ' ' + (el.placeholder || '');
    if (!v) return;
    if (FIELD_RE.test(lab) || /有限公司|Ltd\.?|Inc\.?|Street|Road|District|地址/.test(lab + v)) {
      add(v);
      el.classList.add('pptx-redact-box');
    }
  });

  document.querySelectorAll('.badge').forEach((el) => {
    const t = (el.textContent || '').replace(/\s+/g, ' ').trim();
    if (/有限公司|股份|Ltd|Inc|Company|LLC|Limited/i.test(t)) {
      add(t);
      el.classList.add('pptx-redact-box');
    }
  });
  document.querySelectorAll('#teamsDictList li').forEach((el) => {
    redactTextIn(el);
  });
  document.querySelectorAll('p, .hero-bar, .small').forEach((el) => {
    const t = el.textContent || '';
    const m = t.match(/[「"]([^」"]{2,40})[」"]/g) || [];
    m.forEach((q) => {
      const inner = q.replace(/[「」"]/g, '');
      if (/部|公司|有限|Ltd|Team/i.test(inner)) add(inner);
    });
  });

  const list = [...phrases].filter((p) => {
    if (/[\u4e00-\u9fff]/.test(p)) return p.length >= 2;
    return p.length >= 4;
  }).sort((a, b) => b.length - a.length);
  if (!list.length) return;
  const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(list.map(escapeRe).join('|'), 'g');
  const skipTag = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA']);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const p = node.parentElement;
      if (!p || skipTag.has(p.tagName) || p.closest('.pptx-redact, .pptx-redact-box, nav.navbar')) {
        return NodeFilter.FILTER_REJECT;
      }
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  nodes.forEach((node) => {
    const text = node.nodeValue || '';
    if (!re.test(text)) return;
    re.lastIndex = 0;
    const wrap = document.createElement('span');
    wrap.innerHTML = text.replace(re, (m) => '<span class="pptx-redact">' + m.replace(/[<>]/g, '') + '</span>');
    node.parentNode.replaceChild(wrap, node);
  });
}"""


PAGES: list[dict[str, Any]] = [
    {"file": "fe-login.png", "path": "/login", "auth": False, "wait_ms": 1600},
    {"file": "fe-company.png", "path": "/company", "auth": True, "wait_ms": 2800},
    {
        "file": "fe-company-projects.png",
        "path": "/company",
        "auth": True,
        "wait_ms": 2800,
        "hide": ["#companyKnowledgeTrainCard"],
        "scroll": "#companyProjectsBody",
    },
    {"file": "fe-upload.png", "path": "/upload", "auth": True, "wait_ms": 2800},
    {
        "file": "fe-upload-tasks.png",
        "path": "/upload",
        "auth": True,
        "wait_ms": 2800,
        "scroll": "#recordsTable",
    },
    {"file": "fe-generate.png", "path": "/generate", "auth": True, "wait_ms": 2800},
    {"file": "fe-dashboard.png", "path": "/dashboard", "auth": True, "wait_ms": 2800},
    {
        "file": "fe-draft.png",
        "path": "/draft-gen/?manual=1",
        "auth": True,
        "wait_ms": 3500,
        "scroll": "#dg_organization",
    },
    {"file": "fe-audit.png", "path": "/audit/?manual=1", "auth": True, "wait_ms": 3200},
    {"file": "fe-audit-modify.png", "path": "/audit-modify/?manual=1", "auth": True, "wait_ms": 2800},
    {"file": "fe-translate.png", "path": "/translate/?manual=1", "auth": True, "wait_ms": 2800},
    {"file": "fe-document-control.png", "path": "/document-control", "auth": True, "wait_ms": 3200},
    {
        "file": "fe-version-task.png",
        "path": "/document-control/version-task-generator",
        "auth": True,
        "wait_ms": 2800,
    },
    {"file": "fe-project-kb.png", "path": "/document-control/project-kb", "auth": True, "wait_ms": 2800},
    {"file": "fe-literature.png", "path": "/literature/", "auth": True, "wait_ms": 2500},
    {"file": "fe-exam-center.png", "path": "/exam-center?role=teacher", "auth": True, "wait_ms": 3200},
    {"file": "fe-admin.png", "path": "/admin", "auth": True, "wait_ms": 2800},
]


def _wait_http(base: str, timeout_s: float = 30.0) -> None:
    deadline = time.time() + timeout_s
    last_err = ""
    while time.time() < deadline:
        try:
            with urlopen(base.rstrip("/") + "/login", timeout=15) as resp:
                if resp.status < 500:
                    return
                last_err = f"HTTP {resp.status}"
        except Exception as exc:
            last_err = str(exc)
        time.sleep(0.8)
    raise RuntimeError(f"无法访问 {base}（{last_err}）。请先启动：python run_web.py")


def _mint_session_cookie(root: Path) -> str:
    from flask import Flask
    from flask.sessions import SecureCookieSessionInterface
    from sqlalchemy import create_engine, text

    boot = root / "instance" / "database_url.txt"
    if not boot.exists():
        raise RuntimeError("未找到 instance/database_url.txt，无法签发登录态")
    uri = boot.read_text(encoding="utf-8").strip().split("\n")[0].strip()
    if not uri:
        raise RuntimeError("instance/database_url.txt 为空，无法签发登录态")
    engine = create_engine(uri)
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT config_value FROM app_configs WHERE config_key = :k LIMIT 1"),
                {"k": "SECRET_KEY"},
            ).fetchone()
    finally:
        engine.dispose()
    secret = (str(row[0]).strip() if row and row[0] else "") or "aiword-dev-secret-key-change-in-production"
    fake = Flask("pptx-capture")
    fake.secret_key = secret
    serializer = SecureCookieSessionInterface().get_signing_serializer(fake)
    if serializer is None:
        raise RuntimeError("无法签发登录态：应用未配置会话密钥")
    return serializer.dumps({"page13_authenticated": True})


def _new_context(browser: Any, base: str, cookie: str | None) -> Any:
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        device_scale_factor=2,
        locale="zh-CN",
    )
    if cookie:
        context.add_cookies(
            [
                {
                    "name": "session",
                    "value": cookie,
                    "url": base.rstrip("/") + "/",
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
    return context


def _capture_one(page: Any, spec: dict[str, Any], base: str, out_dir: Path) -> None:
    url = urljoin(base.rstrip("/") + "/", spec["path"].lstrip("/"))
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(int(spec.get("wait_ms") or 2000))
    page.evaluate(PREPARE_JS)
    for sel in spec.get("hide") or []:
        page.evaluate(
            """(sel) => {
              document.querySelectorAll(sel).forEach((el) => {
                el.style.setProperty('display', 'none', 'important');
              });
            }""",
            sel,
        )
    scroll = spec.get("scroll")
    if scroll:
        try:
            page.wait_for_selector(scroll, timeout=8000)
            page.locator(scroll).first.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            page.evaluate(PREPARE_JS)
        except Exception:
            pass
    page.evaluate(REDACT_JS)
    dest = out_dir / spec["file"]
    page.screenshot(path=str(dest), full_page=False)
    print(f"OK  {spec['file']}  <- {spec['path']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="实拍 AI Word 前台截图")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="默认 docs/presentations/screenshots/frontend",
    )
    args = parser.parse_args()
    root = _repo_root()
    out_dir = args.out_dir or (root / "docs" / "presentations" / "screenshots" / "frontend")
    out_dir.mkdir(parents=True, exist_ok=True)
    base = args.base_url.rstrip("/")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少 playwright。请执行：pip install playwright && playwright install chromium", file=sys.stderr)
        return 1

    _wait_http(base)
    cookie = _mint_session_cookie(root)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            guest = _new_context(browser, base, None)
            authed = _new_context(browser, base, cookie)
            guest_page = guest.new_page()
            authed_page = authed.new_page()
            for spec in PAGES:
                page = authed_page if spec.get("auth") else guest_page
                try:
                    _capture_one(page, spec, base, out_dir)
                except Exception as exc:
                    print(f"FAIL {spec['file']}  {spec['path']}: {exc}", file=sys.stderr)
            guest.close()
            authed.close()
        finally:
            browser.close()
    print(f"截图目录: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
