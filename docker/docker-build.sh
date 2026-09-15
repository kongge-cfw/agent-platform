#!/usr/bin/env bash
# 参照 xinjiaoshoujia：主机（或编译容器）先打包产物，Dockerfile 只 COPY。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-$(date +%Y%m%d-%H%M%S)}"

DOCKER_PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-registry.cn-hangzhou.aliyuncs.com/chenfengwei/agent-platform}"
FULL_IMAGE="${IMAGE:-${IMAGE_REPOSITORY}:${TAG}}"
BASE_IMAGE="${BASE_IMAGE:-docker.1ms.run/library/python:3.11-slim-bookworm}"
NODE_IMAGE="${NODE_IMAGE:-docker.1ms.run/library/node:20}"
PYTHON_IMAGE="${PYTHON_IMAGE:-${BASE_IMAGE}}"

DOCKER_ARGS=(--platform "$DOCKER_PLATFORM" --tag "$FULL_IMAGE" --build-arg "BASE_IMAGE=${BASE_IMAGE}")
if [[ "${2:-}" == "--no-cache" ]]; then
  DOCKER_ARGS+=(--no-cache)
fi

echo "Building agent-platform image"
echo "Image: ${FULL_IMAGE}"
echo "Platform: ${DOCKER_PLATFORM}"

echo "[1/3] Building frontend"
if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  (
    cd "$ROOT_DIR"
    WORKSPACE="$ROOT_DIR" VITE_APP_VERSION="${VITE_APP_VERSION:-$TAG}" \
      sh docker/ci/compile-frontend.sh
  )
else
  docker run --rm --platform "$DOCKER_PLATFORM" \
    -v "$ROOT_DIR:/workspace" -w /workspace \
    -e WORKSPACE=/workspace \
    -e VITE_APP_VERSION="${VITE_APP_VERSION:-$TAG}" \
    "$NODE_IMAGE" \
    sh docker/ci/compile-frontend.sh
fi

test -f "$ROOT_DIR/frontend/dist/index.html" || {
  echo "Frontend build output not found: frontend/dist/index.html" >&2
  exit 1
}

echo "[2/3] Building python vendor (linux container)"
docker run --rm --platform "$DOCKER_PLATFORM" \
  -v "$ROOT_DIR:/workspace" -w /workspace \
  -e WORKSPACE=/workspace \
  -e PIP_CACHE_DIR=/tmp/pip-cache \
  "$PYTHON_IMAGE" \
  sh docker/ci/compile-python.sh

test -x "$ROOT_DIR/vendor/venv/bin/uvicorn" || {
  echo "Python vendor not found: vendor/venv" >&2
  exit 1
}

echo "[3/3] Building Docker image"
docker build "${DOCKER_ARGS[@]}" "$ROOT_DIR"

echo "Image built: ${FULL_IMAGE}"

if [[ "${PUSH:-0}" == "1" ]]; then
  echo "Pushing ${FULL_IMAGE}"
  docker push "$FULL_IMAGE"
  echo "Image pushed: ${FULL_IMAGE}"
fi
