#!/bin/sh
# docker-ops 第 2 段：镜像填 python:3.11-slim-bookworm，脚本填本文件
#   sh docker/ci/compile-python.sh
# 不要用界面默认的 pip install -r requirements.txt（装进编译容器，镜像 COPY 不到）
# 产出 vendor/venv、vendor/ms-playwright。运行时路径固定为 /app/vendor/venv。
# 第二次：requirements.txt 未变则复用 venv；Playwright 浏览器缓存在 PIP_CACHE_DIR。
set -eu

ROOT="${WORKSPACE:-$(pwd)}"
cd "$ROOT"

VENV="$ROOT/vendor/venv"
RUNTIME_VENV="/app/vendor/venv"
BROWSERS="$ROOT/vendor/ms-playwright"
PIP_INDEX="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
CACHE_ROOT="${PIP_CACHE_DIR:-/tmp/pip-cache}"
mkdir -p "$CACHE_ROOT" "$ROOT/vendor"

REQ_HASH=$(cksum requirements.txt | awk '{print $1"-"$2}')
VENV_MARK="$VENV/.requirements.hash"
CACHED_VENV="$CACHE_ROOT/agent-platform-venv-$REQ_HASH"
PW_CACHE="$CACHE_ROOT/ms-playwright"

rewrite_shebangs() {
  if [ -d "$VENV/bin" ]; then
    for f in "$VENV/bin"/*; do
      [ -f "$f" ] || continue
      sed -i "s|^#!${VENV}/bin/python[^ ]*|#!${RUNTIME_VENV}/bin/python|" "$f" || true
    done
  fi
}

install_build_deps() {
  command -v apt-get >/dev/null 2>&1 || return 0
  command -v gcc >/dev/null 2>&1 && return 0
  export DEBIAN_FRONTEND=noninteractive
  if [ -f /etc/apt/sources.list.d/debian.sources ]; then
    sed -i \
      -e 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
      -e 's|https://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
      -e 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
      -e 's|https://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
      /etc/apt/sources.list.d/debian.sources || true
  fi
  apt-get update
  apt-get install -y --no-install-recommends gcc g++ unixodbc-dev
}

pip_install_reqs() {
  "$VENV/bin/python" -m pip install -U pip
  "$VENV/bin/python" -m pip install \
    -i "$PIP_INDEX" \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt
}

restore_or_build_venv() {
  if [ "${FORCE_REBUILD:-0}" != "1" ] \
      && [ -x "$VENV/bin/uvicorn" ] \
      && [ -f "$VENV_MARK" ] \
      && [ "$(cat "$VENV_MARK")" = "$REQ_HASH" ]; then
    echo "skip pip (vendor/venv matches requirements.txt)"
    return
  fi

  if [ "${FORCE_REBUILD:-0}" != "1" ] \
      && [ -x "$CACHED_VENV/bin/uvicorn" ]; then
    echo "restore venv from pip cache: $CACHED_VENV"
    rm -rf "$VENV"
    cp -a "$CACHED_VENV" "$VENV"
    rewrite_shebangs
    printf '%s\n' "$REQ_HASH" > "$VENV_MARK"
    return
  fi

  echo "build venv (requirements.txt=$REQ_HASH)"
  rm -rf "$VENV"
  python3 -m venv --copies "$VENV"
  if ! pip_install_reqs; then
    echo "pip failed, install gcc/unixodbc-dev and retry"
    install_build_deps
    pip_install_reqs
  fi
  rewrite_shebangs
  printf '%s\n' "$REQ_HASH" > "$VENV_MARK"
  rm -rf "$CACHED_VENV"
  cp -a "$VENV" "$CACHED_VENV"
}

restore_or_build_venv

export PATH="$VENV/bin:$PATH"
export VIRTUAL_ENV="$VENV"
export PLAYWRIGHT_BROWSERS_PATH="$PW_CACHE"
export PLAYWRIGHT_DOWNLOAD_HOST="${PLAYWRIGHT_DOWNLOAD_HOST:-https://npmmirror.com/mirrors/playwright}"

mkdir -p "$PW_CACHE"
"$VENV/bin/python" -m playwright install chromium
rm -rf "$BROWSERS"
cp -a "$PW_CACHE" "$BROWSERS"

test -d "$BROWSERS"
test -x "$VENV/bin/uvicorn"

echo "python venv ready: $VENV"
echo "playwright browsers ready: $BROWSERS"
