from __future__ import annotations

"""历史本地出站客户端（已弃用）。

PubMed/Scholar 自动检索已改走 aicheckword ``/api/integration/literature/search``，
复用初稿/Cursor 的 ``llm_http_proxy``，本模块仅保留给本地导入/单元场景兼容。
"""

from typing import Any, Optional

import requests


def literature_get(
    url: str,
    *,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: int = 25,
) -> requests.Response:
    with requests.Session() as sess:
        sess.trust_env = False
        resp = sess.get(
            url,
            params=params,
            headers=headers or {},
            timeout=timeout,
            proxies={},
        )
    resp.raise_for_status()
    return resp
