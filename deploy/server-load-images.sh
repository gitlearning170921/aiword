#!/bin/bash
# Linux 服务器：从 tar.gz 或 tar 导入镜像（不启动服务）
# 用法：./server-load-images.sh 1.0.0
set -euo pipefail

VERSION="${1:?用法: ./server-load-images.sh <version>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

load_one() {
  local name="$1"
  local gz_candidates=(
    "${SCRIPT_DIR}/images/${name}-${VERSION}.tar.gz"
    "${SCRIPT_DIR}/dist/${name}-${VERSION}.tar.gz"
    "${SCRIPT_DIR}/${name}-${VERSION}.tar.gz"
  )
  local tar_candidates=(
    "${SCRIPT_DIR}/images/${name}-${VERSION}.tar"
    "${SCRIPT_DIR}/dist/${name}-${VERSION}.tar"
    "${SCRIPT_DIR}/${name}-${VERSION}.tar"
  )

  for f in "${gz_candidates[@]}"; do
    if [[ -f "${f}" ]]; then
      echo "[load] gunzip -c ${f} | docker load"
      gunzip -c "${f}" | docker load
      return 0
    fi
  done

  for f in "${tar_candidates[@]}"; do
    if [[ -f "${f}" ]]; then
      echo "[load] docker load -i ${f}"
      docker load -i "${f}"
      return 0
    fi
  done

  echo "错误: 找不到 ${name}-${VERSION}.tar.gz 或 ${name}-${VERSION}.tar" >&2
  exit 1
}

load_one aiword
load_one aicheckword
load_one chroma

echo "[load] 完成。镜像 tag: aiword:${VERSION} / aicheckword:${VERSION} / chroma:${VERSION}"
