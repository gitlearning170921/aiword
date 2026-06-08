#!/bin/bash
# 拉取新镜像并重建容器（保留命名卷与 MySQL 数据）
# 用法：
#   1. 修改 deploy/.env 中 AIWORD_IMAGE / AICHECKWORD_IMAGE
#   2. ./deploy/upgrade.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE=(docker compose -f "${COMPOSE_FILE}")

echo "[upgrade] 开始升级（先备份）..."
bash "${SCRIPT_DIR}/backup.sh"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
  echo "[upgrade] aiword 镜像: ${AIWORD_IMAGE:-aiword:local}"
  echo "[upgrade] aicheckword 镜像: ${AICHECKWORD_IMAGE:-aicheckword:local}"
fi

echo "[upgrade] 拉取镜像（离线 tar 部署可忽略 pull 失败）..."
"${COMPOSE[@]}" pull aiword aicheckword 2>/dev/null || true

# 若 images/ 或 dist/ 下有新版本 tar，可选加载（环境变量 NEW_IMAGE_VERSION）
if [[ -n "${NEW_IMAGE_VERSION:-}" && -x "${SCRIPT_DIR}/server-load-images.sh" ]]; then
  echo "[upgrade] 从 tar 加载镜像版本 ${NEW_IMAGE_VERSION}..."
  bash "${SCRIPT_DIR}/server-load-images.sh" "${NEW_IMAGE_VERSION}"
fi

echo "[upgrade] 重建容器（不删除卷）..."
"${COMPOSE[@]}" up -d --no-deps --force-recreate aiword aicheckword

echo "[upgrade] 等待健康检查..."
sleep 5
"${COMPOSE[@]}" ps

echo "[upgrade] 最近日志："
"${COMPOSE[@]}" logs --tail=40 aiword aicheckword

echo "[upgrade] 完成。若需回滚：将 .env 中镜像 tag 改回上一版本后再次执行本脚本。"
echo "[upgrade] 禁止: docker compose down -v"
