#!/bin/sh
# docker-ops 第 1 段：镜像填 node:20，脚本填本文件
#   sh docker/ci/compile-frontend.sh
# 产出 frontend/dist；不要用 npm run build（会跑 vue-tsc，又慢又容易挂）
# 第二次：lockfile 未变则跳过 npm ci，只跑 vite（依赖走 /cache/npm）
set -eu

ROOT="${WORKSPACE:-$(pwd)}"
cd "$ROOT"

APP_VERSION="${VITE_APP_VERSION:-${RELEASE_TAG:-${APP_VERSION:-${VERSION:-dev}}}}"
NPM_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"

cd frontend

lock_hash() {
  cksum package.json package-lock.json 2>/dev/null | cksum | awk '{print $1"-"$2}'
}

DEPS_HASH="$(lock_hash)"
DEPS_MARK="node_modules/.deps.hash"

if [ "${FORCE_REBUILD:-0}" != "1" ] \
    && [ -d node_modules ] \
    && [ -f "$DEPS_MARK" ] \
    && [ "$(cat "$DEPS_MARK")" = "$DEPS_HASH" ]; then
  echo "skip npm ci (package-lock unchanged)"
else
  if [ -f package-lock.json ]; then
    npm ci --no-audit --no-fund --registry="$NPM_REGISTRY"
  else
    npm install --no-audit --no-fund --registry="$NPM_REGISTRY"
  fi
  mkdir -p node_modules
  printf '%s\n' "$DEPS_HASH" > "$DEPS_MARK"
fi

NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=4096}" \
  VITE_APP_VERSION="$APP_VERSION" \
  npx vite build

test -f dist/index.html
echo "frontend dist ready: $ROOT/frontend/dist"
