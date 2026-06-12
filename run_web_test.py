"""兼容入口：已合并到 run_web.py，请改 .env 中 AIWORD_ENV=test。"""
from __future__ import annotations

print(
    "[aiword] 提示：环境切换请编辑 .env 中的 AIWORD_ENV（test/prod），无需本脚本。",
    flush=True,
)

from run_web import main

if __name__ == "__main__":
    main()
