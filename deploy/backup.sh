#!/bin/bash
# 升级前备份：MySQL dump + Docker 命名卷 + .env
# 用法：在 aiword 仓库根目录或 deploy 目录执行 ./deploy/backup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a
  source .env
  set +a
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${SCRIPT_DIR}/backup/${STAMP}"
mkdir -p "${BACKUP_DIR}"

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-aiword-stack}"
COMPOSE=(docker compose -f docker-compose.yml)

echo "[backup] 备份目录: ${BACKUP_DIR}"

if [[ -f .env ]]; then
  cp .env "${BACKUP_DIR}/.env"
  echo "[backup] 已复制 deploy/.env"
fi

# MySQL（需宿主机有 mysqldump 且能连库；变量可在 .env 中配置 BACKUP_MYSQL_*）
MYSQL_HOST="${BACKUP_MYSQL_HOST:-${MYSQL_HOST:-}}"
MYSQL_PORT="${BACKUP_MYSQL_PORT:-${MYSQL_PORT:-3306}}"
MYSQL_USER="${BACKUP_MYSQL_USER:-${MYSQL_USER:-}}"
MYSQL_PASSWORD="${BACKUP_MYSQL_PASSWORD:-${MYSQL_PASSWORD:-}}"
AIWORD_DB="${BACKUP_AIWORD_DATABASE:-aiword}"
AICHECK_DB="${BACKUP_AICHECKWORD_DATABASE:-aicheckword}"

if [[ -n "${MYSQL_HOST}" && -n "${MYSQL_USER}" ]] && command -v mysqldump >/dev/null 2>&1; then
  export MYSQL_PWD="${MYSQL_PASSWORD}"
  if mysqldump -h "${MYSQL_HOST}" -P "${MYSQL_PORT}" -u "${MYSQL_USER}" \
      --single-transaction --routines --triggers \
      "${AIWORD_DB}" > "${BACKUP_DIR}/${AIWORD_DB}.sql" 2>/dev/null; then
    echo "[backup] MySQL dump: ${AIWORD_DB}.sql"
  else
    echo "[backup] 跳过 ${AIWORD_DB} dump（连接失败或无权限）"
  fi
  if mysqldump -h "${MYSQL_HOST}" -P "${MYSQL_PORT}" -u "${MYSQL_USER}" \
      --single-transaction --routines --triggers \
      "${AICHECK_DB}" > "${BACKUP_DIR}/${AICHECK_DB}.sql" 2>/dev/null; then
    echo "[backup] MySQL dump: ${AICHECK_DB}.sql"
  else
    echo "[backup] 跳过 ${AICHECK_DB} dump（连接失败或无权限）"
  fi
  unset MYSQL_PWD
else
  echo "[backup] 跳过 MySQL dump（未配置 BACKUP_MYSQL_* / MYSQL_* 或无 mysqldump）"
fi

backup_volume() {
  local vol_suffix="$1"
  local vol_name="${PROJECT_NAME}_${vol_suffix}"
  if docker volume inspect "${vol_name}" >/dev/null 2>&1; then
    docker run --rm \
      -v "${vol_name}:/data:ro" \
      -v "${BACKUP_DIR}:/backup" \
      alpine:3.20 \
      tar czf "/backup/${vol_suffix}_${STAMP}.tgz" -C /data .
    echo "[backup] 卷 ${vol_name} -> ${vol_suffix}_${STAMP}.tgz"
  else
    echo "[backup] 卷不存在，跳过: ${vol_name}"
  fi
}

for vol in aiword_instance aiword_uploads aiword_outputs aicheck_knowledge aicheck_uploads aicheck_training chroma_data; do
  backup_volume "${vol}"
done

echo "[backup] 完成: ${BACKUP_DIR}"
echo "[backup] 切勿使用 docker compose down -v，否则会删除上述命名卷。"
