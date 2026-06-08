#!/bin/bash
set -euo pipefail

INSTANCE_DIR="/app/instance"
UPLOADS_DIR="/app/uploads"
OUTPUTS_DIR="/app/outputs"
LOCKS_DIR="${INSTANCE_DIR}/scheduler_locks"
DB_BOOTSTRAP_FILE="${INSTANCE_DIR}/database_url.txt"

mkdir -p "${INSTANCE_DIR}" "${UPLOADS_DIR}" "${OUTPUTS_DIR}" "${LOCKS_DIR}"

# 幂等：仅首次写入冷启动数据库 URI（升级不覆盖已有配置）
if [[ ! -f "${DB_BOOTSTRAP_FILE}" ]]; then
  if [[ -n "${AIWORD_BOOTSTRAP_DATABASE_URL:-}" ]]; then
    printf '%s\n' "${AIWORD_BOOTSTRAP_DATABASE_URL}" > "${DB_BOOTSTRAP_FILE}"
    echo "[entrypoint] 已写入 instance/database_url.txt（首次部署）"
  else
    echo "[entrypoint] 警告: 未设置 AIWORD_BOOTSTRAP_DATABASE_URL，且 instance/database_url.txt 不存在。"
    echo "[entrypoint] 请挂载已有 instance 卷，或在 .env 中配置 AIWORD_BOOTSTRAP_DATABASE_URL。"
  fi
fi

# 与 webapp 启动逻辑一致：清理 scheduler 锁，避免旧锁导致定时任务被跳过
if compgen -G "${LOCKS_DIR}/*.lock" > /dev/null; then
  rm -f "${LOCKS_DIR}"/*.lock
  echo "[entrypoint] 已清理 scheduler_locks/*.lock"
fi

# 清理模板磁盘缓存（迁机/升级后从库重建）
rm -f "${UPLOADS_DIR}"/_dbtpl_*.docx 2>/dev/null || true

exec "$@"
