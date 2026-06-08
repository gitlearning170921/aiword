#!/bin/bash
# Linux 服务器：从 tar 导入镜像（不启动服务）
# 用法：./server-load-images.sh 1.0.0
set -euo pipefail

VERSION="${1:?用法: ./server-load-images.sh <version>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

load_tar() {
  local name="$1"
  local candidates=(
    "${SCRIPT_DIR}/images/${name}-${VERSION}.tar"
    "${SCRIPT_DIR}/dist/${name}-${VERSION}.tar"
    "${SCRIPT_DIR}/${name}-${VERSION}.tar"
  )
  for f in "${candidates[@]}"; do
    if [[ -f "${f}" ]]; then
      echo "[load] docker load -i ${f}"
      docker load -i "${f}"
      return 0
    fi
  done
  echo "错误: 找不到 ${name}-${VERSION}.tar" >&2
  exit 1
}

load_tar aiword
load_tar aicheckword

echo "[load] 完成。镜像 tag: aiword:${VERSION} / aicheckword:${VERSION}"
