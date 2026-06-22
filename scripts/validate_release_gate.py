#!/usr/bin/env python3
"""
发版前门禁：在 docker build 之前拦截常见前端/模板/后端语法问题。

用法（aiword 仓库根目录）：
  python scripts/validate_release_gate.py

退出码：0 通过；1 存在 ERROR。
"""
from __future__ import annotations

import hashlib
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_DIR = ROOT / "web" / "static" / "js"
WEB_TPL = ROOT / "web" / "templates"
PKG_TPL = ROOT / "webapp" / "templates"

# web 与 webapp 须保持一致的集成页模板（避免 Docker 只带 webapp 时行为不一致）
PAIRED_TEMPLATES = (
    "draft_gen.html",
    "audit.html",
    "translate.html",
    "audit_modify.html",
)

CLOSE_FN = re.compile(r"^  \}\s*$")
ORPHAN_DECL = re.compile(r"^    (const|let|var)\s+\w+")


def _fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)


def scan_orphan_const_blocks(js_path: Path) -> list[str]:
    """检测 IIFE 内函数体裸露（曾导致 Unexpected token 'const'）。"""
    lines = js_path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        if not CLOSE_FN.match(line):
            continue
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j >= len(lines) or not ORPHAN_DECL.match(lines[j]):
            continue
        window = "\n".join(lines[i + 1 : j + 1])
        if "function " in window or "=>" in window:
            continue
        out.append(f"{js_path.name}:{j + 1}: 疑似函数头缺失后的裸露声明: {lines[j].strip()[:72]}")
    return out


def check_js_orphans() -> bool:
    ok = True
    if not JS_DIR.is_dir():
        _fail(f"缺少目录 {JS_DIR}")
        return False
    for fp in sorted(JS_DIR.glob("*.js")):
        for err in scan_orphan_const_blocks(fp):
            _fail(err)
            ok = False
    if ok:
        print(f"OK  JS orphan-scan ({len(list(JS_DIR.glob('*.js')))} files)")
    return ok


def _file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_template_parity() -> bool:
    ok = True
    for name in PAIRED_TEMPLATES:
        a, b = WEB_TPL / name, PKG_TPL / name
        if a.is_file() and b.is_file():
            if _file_hash(a) != _file_hash(b):
                _fail(f"模板不一致: web/templates/{name} vs webapp/templates/{name}")
                ok = False
        elif a.is_file() != b.is_file():
            _fail(f"模板仅一侧存在: {name}")
            ok = False
    if ok:
        print(f"OK  template parity ({len(PAIRED_TEMPLATES)} files)")
    return ok


def check_python_syntax() -> bool:
    ok = True
    targets = sorted(ROOT.glob("webapp/**/*.py"))
    if not targets:
        _fail("未找到 webapp/**/*.py")
        return False
    for fp in targets:
        if fp.name == "__pycache__":
            continue
        try:
            py_compile.compile(str(fp), doraise=True)
        except py_compile.PyCompileError as e:
            _fail(f"Python 语法错误 {fp.relative_to(ROOT)}: {e}")
            ok = False
    if ok:
        print(f"OK  py_compile webapp ({len(targets)} files)")
    return ok


def main() -> int:
    print("== validate_release_gate ==")
    results = [
        check_js_orphans(),
        check_template_parity(),
        check_python_syntax(),
    ]
    if all(results):
        print("PASS  release gate")
        return 0
    print("FAIL  release gate — 请修复后再 build-apps-all.bat", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
