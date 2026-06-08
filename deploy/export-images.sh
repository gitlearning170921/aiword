#!/bin/bash
# 导出镜像 tar
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

docker save -o "${DIST}/aiword-${VERSION}.tar" "${AIWORD_IMAGE}"
docker save -o "${DIST}/aicheckword-${VERSION}.tar" "${AICHECKWORD_IMAGE}"

echo "已导出到 ${DIST}/"
