#!/bin/bash
# Linux 服务器：导入镜像并启动（无需源码、无需 build）
# 用法：
#   cp .env.example .env   # 编辑 MySQL、密钥等
#   ./server-deploy.sh 1.0.0
set -euo pipefail

VERSION="${1:?用法: ./server-deploy.sh <version>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ ! -f .env ]]; then
  echo "错误: 请先 cp .env.example .env 并填写配置" >&2
  exit 1
fi

bash "${SCRIPT_DIR}/server-load-images.sh" "${VERSION}"

# 确保 .env 中镜像 tag 与版本一致（若未设置则追加提示）
if ! grep -q "^AIWORD_IMAGE=" .env; then
  echo "AIWORD_IMAGE=aiword:${VERSION}" >> .env
fi
if ! grep -q "^AICHECKWORD_IMAGE=" .env; then
  echo "AICHECKWORD_IMAGE=aicheckword:${VERSION}" >> .env
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

export AIWORD_IMAGE="${AIWORD_IMAGE:-aiword:${VERSION}}"
export AICHECKWORD_IMAGE="${AICHECKWORD_IMAGE:-aicheckword:${VERSION}}"

echo "[deploy] AIWORD_IMAGE=${AIWORD_IMAGE}"
echo "[deploy] AICHECKWORD_IMAGE=${AICHECKWORD_IMAGE}"

COMPOSE=(docker compose -f docker-compose.prod.yml)
"${COMPOSE[@]}" up -d

sleep 5
"${COMPOSE[@]}" ps
echo "[deploy] 日志: ${COMPOSE[*]} logs -f aiword aicheckword"
