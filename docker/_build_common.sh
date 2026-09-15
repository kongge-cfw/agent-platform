#!/bin/bash
# 内部脚本：由 build_linux_*.sh / build_native.sh 调用，请勿直接执行
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
RELEASE_DIR="$SCRIPT_DIR/release"
if [ -z "$VERSION" ]; then
  echo "错误: 未指定版本号。请使用相应的入口构建脚本并传入版本号 (例如: ./build_linux_x86.sh 1.2.0)"
  exit 1
fi
IMAGE_NAME="nanzi-ai-agent:$VERSION"

# PLATFORM: linux/amd64 | linux/arm64；留空则本机原生架构
# EXPORT_TAR: 1 导出 tar 到 docker/release/（默认）；0 不导出
EXPORT_TAR="${EXPORT_TAR:-1}"

platform_label() {
  case "${1:-}" in
    linux/amd64) echo "linux-amd64" ;;
    linux/arm64) echo "linux-arm64" ;;
    *) echo "native" ;;
  esac
}

# 判断是否需要跨架构构建（Mac M 系打 x86 包等）
needs_cross_build() {
  [[ -n "${PLATFORM:-}" ]] || return 1
  local machine
  machine="$(uname -m)"
  case "$PLATFORM" in
    linux/amd64)
      [[ "$machine" == "x86_64" ]] && return 1
      return 0
      ;;
    linux/arm64)
      [[ "$machine" == "arm64" || "$machine" == "aarch64" ]] && return 1
      return 0
      ;;
    *)
      return 0
      ;;
  esac
}

# 解析可用的 buildx 命令（兼容 Homebrew / Docker Desktop）
resolve_buildx() {
  if docker buildx version >/dev/null 2>&1; then
    BUILDX=(docker buildx)
    return 0
  fi
  if command -v docker-buildx >/dev/null 2>&1; then
    BUILDX=(docker-buildx)
    return 0
  fi
  local candidates=(
    "$(brew --prefix docker-buildx 2>/dev/null)/bin/docker-buildx"
    "/opt/homebrew/lib/docker/cli-plugins/docker-buildx"
    "/usr/local/lib/docker/cli-plugins/docker-buildx"
  )
  local p
  for p in "${candidates[@]}"; do
    if [[ -n "$p" && -x "$p" ]]; then
      BUILDX=("$p")
      return 0
    fi
  done
  return 1
}

print_buildx_help() {
  cat <<EOF
错误: 跨平台构建需要 docker buildx，但当前环境不可用。

常见原因: 使用 Homebrew 安装的 docker，但 ~/.docker/cli-plugins/docker-buildx
         仍指向已卸载的 Docker Desktop（失效软链）。

修复（任选其一）:

  1) 一键修复（推荐，在 docker 目录执行）:
     ./install-buildx.sh

  2) 手动安装:
     brew install docker-buildx
     mkdir -p ~/.docker/cli-plugins
     ln -sf "\$(brew --prefix docker-buildx)/bin/docker-buildx" ~/.docker/cli-plugins/docker-buildx
     docker buildx version

  3) 安装并启动 Docker Desktop，使用其自带的 docker 命令。

修复后重新执行: ./build_linux_x86.sh
EOF
}

ensure_buildx() {
  if ! resolve_buildx; then
    print_buildx_help
    exit 1
  fi
  if ! "${BUILDX[@]}" inspect nanzi-builder >/dev/null 2>&1; then
    # 智能代理检测：由于 buildx 容器（docker-container 驱动）独立运行且默认不继承宿主机代理，
    # 当检测到当前终端配置了 http_proxy 时，自动将其转换为虚拟机可访问的宿主机地址（Colima/Docker Desktop 自动适配）并注入构建器中，
    # 如果没有代理配置则保持原默认创建行为，保证团队协作兼容性。
    create_args=(create --name nanzi-builder)
    local proxy_url=""
    if [ -n "${http_proxy:-}" ]; then
      proxy_url="$http_proxy"
    elif [ -n "${HTTP_PROXY:-}" ]; then
      proxy_url="$HTTP_PROXY"
    fi

    if [ -n "$proxy_url" ]; then
      local host_domain="host.docker.internal"
      if docker context show 2>/dev/null | grep -q "colima"; then
        host_domain="host.lima.internal"
      fi
      local resolved_proxy
      resolved_proxy=$(echo "$proxy_url" | sed -E "s/127\.0\.0\.1|localhost/$host_domain/g")
      create_args=("${create_args[@]}" --driver-opt "env.http_proxy=$resolved_proxy" --driver-opt "env.https_proxy=$resolved_proxy")
      echo "=== 检测到终端配置了代理，已自动为 buildx 注入代理: $resolved_proxy ==="
    fi

    "${BUILDX[@]}" "${create_args[@]}" --use
  else
    "${BUILDX[@]}" use nanzi-builder >/dev/null
  fi
}

native_linux_platform() {
  case "$(uname -m)" in
    x86_64|amd64) echo linux/amd64 ;;
    arm64|aarch64) echo linux/arm64 ;;
    *) echo linux/amd64 ;;
  esac
}

# 主机打包前端 + Linux 容器打包 Python/Playwright，镜像内不再 npm/pip
prepare_build_artifacts() {
  local compile_platform node_image python_image
  compile_platform="${PLATFORM:-$(native_linux_platform)}"
  node_image="${NODE_IMAGE:-docker.1ms.run/library/node:20}"
  python_image="${PYTHON_IMAGE:-${BASE_IMAGE:-docker.1ms.run/library/python:3.11-slim-bookworm}}"

  echo "=== [1/2] 打包前端 ==="
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    (
      cd "$PROJECT_ROOT"
      WORKSPACE="$PROJECT_ROOT" VITE_APP_VERSION="$VERSION" sh docker/ci/compile-frontend.sh
    )
  else
    docker run --rm --platform "$compile_platform" \
      -v "$PROJECT_ROOT:/workspace" -w /workspace \
      -e WORKSPACE=/workspace \
      -e VITE_APP_VERSION="$VERSION" \
      "$node_image" \
      sh docker/ci/compile-frontend.sh
  fi
  test -f "$PROJECT_ROOT/frontend/dist/index.html"

  echo "=== [2/2] 打包 Python 依赖与 Playwright（$compile_platform）==="
  docker run --rm --platform "$compile_platform" \
    -v "$PROJECT_ROOT:/workspace" -w /workspace \
    -e WORKSPACE=/workspace \
    -e PIP_CACHE_DIR=/tmp/pip-cache \
    "$python_image" \
    sh docker/ci/compile-python.sh
  test -x "$PROJECT_ROOT/vendor/venv/bin/uvicorn"
}

docker_build_args() {
  DOCKER_BUILD_ARGS=(-f "$SCRIPT_DIR/Dockerfile" -t "$IMAGE_NAME")
  if [[ -n "${BASE_IMAGE:-}" ]]; then
    DOCKER_BUILD_ARGS+=(--build-arg "BASE_IMAGE=$BASE_IMAGE")
  fi
}

run_build() {
  docker_build_args

  if [[ -z "${PLATFORM:-}" ]]; then
    docker build "${DOCKER_BUILD_ARGS[@]}" .
    return
  fi

  if needs_cross_build; then
    ensure_buildx
    "${BUILDX[@]}" build \
      --platform "$PLATFORM" \
      --progress=plain \
      "${DOCKER_BUILD_ARGS[@]}" \
      --load \
      .
    return
  fi

  # 本机已是目标架构（如 Intel Mac 打 amd64），可直接 docker build
  echo "本机架构与目标平台一致，使用 docker build（无需 buildx）"
  DOCKER_BUILDKIT=1 docker build \
    --platform "$PLATFORM" \
    --progress=plain \
    "${DOCKER_BUILD_ARGS[@]}" \
    .
}

LABEL="$(platform_label "${PLATFORM:-}")"
DATE_TAG="$(date +%Y%m%d)"
OUTPUT_FILE="$RELEASE_DIR/nanzi-ai-agent_${VERSION}_${LABEL}_${DATE_TAG}.tar"

echo "=== 开始构建 Docker 镜像 ==="
echo "项目根目录: $PROJECT_ROOT"
echo "Dockerfile:   $SCRIPT_DIR/Dockerfile"
echo "镜像标签:     $IMAGE_NAME"
echo "tar 输出目录: $RELEASE_DIR"
if [[ -n "${PLATFORM:-}" ]]; then
  if needs_cross_build; then
    echo "目标平台:     $PLATFORM (docker buildx 跨平台)"
  else
    echo "目标平台:     $PLATFORM (docker build)"
  fi
else
  echo "目标平台:     本机原生架构 (docker build)"
fi

mkdir -p "$RELEASE_DIR"
cd "$PROJECT_ROOT"

prepare_build_artifacts
run_build

echo "=== 镜像构建成功: $IMAGE_NAME ==="

if docker image inspect "$IMAGE_NAME" --format '{{.Os}}/{{.Architecture}}' 2>/dev/null; then
  echo "镜像架构:     $(docker image inspect "$IMAGE_NAME" --format '{{.Os}}/{{.Architecture}}')"
fi

if [[ "$EXPORT_TAR" == "1" ]]; then
  echo "=== 正在导出镜像到 $OUTPUT_FILE ==="
  docker save -o "$OUTPUT_FILE" "$IMAGE_NAME"
  echo "=== 导出完成 ==="
  ls -lh "$OUTPUT_FILE"
else
  echo "=== 跳过导出 tar (EXPORT_TAR=0) ==="
fi
