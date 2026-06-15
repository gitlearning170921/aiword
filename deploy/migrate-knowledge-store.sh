#!/bin/bash
# 将本机打包的 knowledge_store.tar.gz 导入生产（不重训、不重新 embedding）
#
# 用法（在 Linux deploy 目录）：
#   1. 开发机: tar -czf knowledge_store.tar.gz knowledge_store  （在 aicheckword 仓库根）
#   2. scp knowledge_store.tar.gz user@server:/opt/aiword-stack/sync/
#   3. ./migrate-knowledge-store.sh /opt/aiword-stack/sync/knowledge_store.tar.gz
#
# 目标二选一（环境变量 TARGET）：
#   chroma   — 写入 chroma 卷（远程 Chroma HTTP，开发/生产共用，默认）
#   aicheck  — 写入 aicheckword 本地卷 /app/knowledge_store（不启远程 Chroma 时用）
set -euo pipefail

ARCHIVE="${1:?用法: ./migrate-knowledge-store.sh <knowledge_store.tar.gz>}"
TARGET="${TARGET:-chroma}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

COMPOSE=(docker compose -f docker-compose.prod.yml)
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-aiword-stack}"

if [[ ! -f "${ARCHIVE}" ]]; then
  echo "错误: 找不到 ${ARCHIVE}" >&2
  exit 1
fi

case "${TARGET}" in
  chroma)
    VOL="${PROJECT_NAME}_chroma_data"
    MOUNT="/chroma/chroma"
    STOP_SVC=(chroma aicheckword)
    ;;
  aicheck)
    VOL="${PROJECT_NAME}_aicheck_knowledge"
    MOUNT="/app/knowledge_store"
    STOP_SVC=(aicheckword)
    ;;
  *)
    echo "错误: TARGET 只能是 chroma 或 aicheck" >&2
    exit 1
    ;;
esac

echo "[migrate] 归档: ${ARCHIVE}"
echo "[migrate] 目标卷: ${VOL} -> ${MOUNT}"
echo "[migrate] 停止服务: ${STOP_SVC[*]}"
"${COMPOSE[@]}" stop "${STOP_SVC[@]}" 2>/dev/null || true

echo "[migrate] 解压到卷（保留 chroma.sqlite3 与 UUID 子目录）..."
docker run --rm \
  -v "${VOL}:/dest" \
  -v "$(dirname "$(realpath "${ARCHIVE}")"):/backup:ro" \
  alpine sh -c "
    set -e
    rm -rf /dest/*
    tar xzf /backup/$(basename "${ARCHIVE}") -C /dest --strip-components=1
    chown -R 1000:1000 /dest
    ls -la /dest | head -20
    test -f /dest/chroma.sqlite3 || (echo 'ERROR: chroma.sqlite3 不在卷根目录' >&2; exit 1)
  "

echo "[migrate] 启动服务..."
if [[ "${TARGET}" == "chroma" ]]; then
  "${COMPOSE[@]}" up -d chroma
  sleep 3
  if curl -sf "http://127.0.0.1:${CHROMA_PUBLISH_PORT:-8100}/api/v1/heartbeat" >/dev/null; then
    echo "[migrate] Chroma heartbeat OK"
  else
    echo "[migrate] 警告: Chroma heartbeat 未响应，请检查 docker compose logs chroma" >&2
  fi
fi
"${COMPOSE[@]}" up -d aicheckword

echo "[migrate] 完成。请在 aiword 里试一次审核/检索验证。"
echo "[migrate] 若 Chroma 报版本/格式错误：开发机 pip show chromadb 版本需与 deploy/chroma-image.tag 接近。"
