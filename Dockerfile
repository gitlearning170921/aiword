# aiword Web 服务（生产：gunicorn 单 worker，配合 APScheduler）
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

WORKDIR /w

COPY requirements-docker.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --prefix=/install -r requirements-docker.txt "gunicorn>=22.0.0"

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AIWORD_PROJECT_ROOT=/app

WORKDIR /app

RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 -s /bin/bash app

COPY --from=builder /install /usr/local

COPY . .

RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /app/instance /app/uploads /app/outputs \
    && chown -R app:app /app

USER app

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://127.0.0.1:5000/api/integration/health || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# -w 1 --threads 16 -k gthread：
#   保持 APScheduler 单进程（避免多 worker 重复触发），同时让静态文件/API 在 I/O wait 时
#   并发释放 GIL，单页面多个 JS/CSS 不再串行；解决 gunicorn -w 1 单线程的最大瓶颈。
CMD ["gunicorn", \
     "-k", "gthread", \
     "-w", "1", \
     "--threads", "16", \
     "-b", "0.0.0.0:5000", \
     "--timeout", "600", \
     "--graceful-timeout", "30", \
     "--keep-alive", "30", \
     "--access-logfile", "-", \
     "webapp:app"]
