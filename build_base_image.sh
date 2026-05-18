#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="${SCRIPT_DIR}/hermes-agent"
IMAGE_NAME="hermes-base"
IMAGE_TAG="${1:-latest}"
DOCKERFILE="${BUILD_DIR}/Dockerfile"

echo "正在构建镜像 ${IMAGE_NAME}:${IMAGE_TAG} ..."
echo "Dockerfile 路径: ${DOCKERFILE}"
echo "构建上下文: ${BUILD_DIR}"

docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" -f "${DOCKERFILE}" "${BUILD_DIR}"

echo "构建完成: ${IMAGE_NAME}:${IMAGE_TAG}"
