"""本机全栈健康检查（5000 / 8000 / 5050）。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


def _probe(name: str, url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            try:
                data = json.loads(body)
                return True, json.dumps(data, ensure_ascii=False)[:200]
            except json.JSONDecodeError:
                return True, body[:200]
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)


def _resolve_url(env_key: str, default: str) -> str:
    raw = (os.environ.get(env_key) or "").strip().rstrip("/")
    return raw or default


def main() -> int:
    quiz_base = _resolve_url("QUIZ_API_BASE_URL", "http://127.0.0.1:8000")
    aprint_base = _resolve_url("AIPRINTWORD_BASE_URL", "http://127.0.0.1:5050")

    checks: list[tuple[str, str]] = [
        ("aicheckword", f"{quiz_base}/health"),
        ("aiword", "http://127.0.0.1:5000/api/integration/health"),
        ("aiprintword", f"{aprint_base}/api/aiprintword-build"),
    ]

    print("=" * 50)
    print("本机全栈 Smoke")
    print("=" * 50)
    failed = 0
    for name, url in checks:
        ok, detail = _probe(name, url)
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}: {url}")
        print(f"       {detail}")
        if not ok:
            failed += 1
    print("=" * 50)
    if failed:
        print(f"失败 {failed} 项。请先运行 scripts\\start_stack.bat")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
