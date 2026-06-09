#!/bin/bash
# 导出镜像 tar.gz（优先）或 tar
# 用法：./export-images.sh 1.0.0
set -euo pipefail

VERSION="${1:?用法: ./export-images.sh <version>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="${SCRIPT_DIR}/dist"
mkdir -p "${DIST}"

AIWORD_IMAGE="aiword:${VERSION}"
AICHECKWORD_IMAGE="aicheckword:${VERSION}"

for img in "${AIWORD_IMAGE}" "${AICHECKWORD_IMAGE}"; do
  docker image inspect "${img}" >/dev/null 2>&1 || {
    echo "镜像不存在: ${img}，请先 ./build-images.sh ${VERSION}" >&2
    exit 1
  }
done

if command -v gzip >/dev/null 2>&1; then
  docker save "${AIWORD_IMAGE}" | gzip -1 > "${DIST}/aiword-${VERSION}.tar.gz"
  docker save "${AICHECKWORD_IMAGE}" | gzip -1 > "${DIST}/aicheckword-${VERSION}.tar.gz"
  echo "已导出到 ${DIST}/ (*.tar.gz)"
else
  docker save -o "${DIST}/aiword-${VERSION}.tar" "${AIWORD_IMAGE}"
  docker save -o "${DIST}/aicheckword-${VERSION}.tar" "${AICHECKWORD_IMAGE}"
  echo "已导出到 ${DIST}/ (*.tar，未找到 gzip)"
fi
