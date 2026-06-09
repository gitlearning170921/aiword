#!/bin/bash
# 本机构建 Linux 镜像（macOS/Linux 开发机）
# 用法：./build-images.sh 1.0.0
set -euo pipefail

VERSION="${1:-1.0.0}"
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AIWORD_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
AICHECKWORD_ROOT="$(cd "${AIWORD_ROOT}/../aicheckword" && pwd)"

if [[ ! -d "${AICHECKWORD_ROOT}" ]]; then
  echo "错误: 未找到 aicheckword: ${AICHECKWORD_ROOT}" >&2
  exit 1
fi

command -v docker >/dev/null || { echo "请先安装 Docker"; exit 1; }

export DOCKER_BUILDKIT=1

AIWORD_IMAGE="aiword:${VERSION}"
AICHECKWORD_IMAGE="aicheckword:${VERSION}"

echo "==> platform=${PLATFORM} (parallel, BuildKit=1)"

docker build --platform "${PLATFORM}" -t "${AIWORD_IMAGE}" -f "${AIWORD_ROOT}/Dockerfile" "${AIWORD_ROOT}" &
pid_aiword=$!
docker build --platform "${PLATFORM}" -t "${AICHECKWORD_IMAGE}" -f "${AICHECKWORD_ROOT}/Dockerfile" "${AICHECKWORD_ROOT}" &
pid_aicheckword=$!

wait "${pid_aiword}"
wait "${pid_aicheckword}"

docker tag "${AIWORD_IMAGE}" aiword:local
docker tag "${AICHECKWORD_IMAGE}" aicheckword:local

mkdir -p "${SCRIPT_DIR}/dist"
cat > "${SCRIPT_DIR}/dist/manifest-${VERSION}.txt" <<EOF
version=${VERSION}
platform=${PLATFORM}
buildkit=1
built_at=$(date '+%Y-%m-%d %H:%M:%S')
aiword_image=${AIWORD_IMAGE}
aicheckword_image=${AICHECKWORD_IMAGE}
EOF

echo "构建完成。下一步: ./export-images.sh ${VERSION}"
