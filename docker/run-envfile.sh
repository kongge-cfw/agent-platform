#!/bin/bash
# 方案 B：一份宿主机 .env（含密钥）+ 镜像内 APP_ENV 选择 dev/prod。
# 用法（在 docker/ 目录）：
#   APP_ENV=prod ./run-envfile.sh registry.example.com/ns/nanzi-ai-agent:tag
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

APP_ENV="${APP_ENV:-prod}"
IMAGE="${1:-${NANZI_IMAGE:-nanzi-ai-agent:latest}}"
CONTAINER_NAME="${CONTAINER_NAME:-nanzi-ai-agent}"
ENV_FILE="${NANZI_ENV_FILE:-$SCRIPT_DIR/.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "错误: 找不到 $ENV_FILE"
  echo "请复制 ../env.example 为 docker/.env，填入 ENCRYPTION_KEY 和数据库/Redis 密码后重试。"
  exit 1
fi

case "$APP_ENV" in
  dev|prod) ;;
  *)
    echo "错误: APP_ENV 只能是 dev 或 prod，当前为 '$APP_ENV'"
    exit 1
    ;;
esac

# 仅取出数据目录，用于 -v；密钥仍只通过 --env-file 进容器
HOST_DATA_DIR_VALUE=""
if [ -n "${HOST_DATA_DIR:-}" ]; then
  HOST_DATA_DIR_VALUE="$HOST_DATA_DIR"
else
  HOST_DATA_DIR_VALUE="$(grep -E '^HOST_DATA_DIR=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
fi
if [ -z "$HOST_DATA_DIR_VALUE" ]; then
  HOST_DATA_DIR_VALUE="$SCRIPT_DIR/data"
fi
mkdir -p "$HOST_DATA_DIR_VALUE"

if [ "$(docker ps -aq -f "name=^${CONTAINER_NAME}$")" ]; then
  echo "停止并删除旧容器 ${CONTAINER_NAME}..."
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

echo "启动 ${CONTAINER_NAME}"
echo "  image : $IMAGE"
echo "  APP_ENV: $APP_ENV"
echo "  env   : $ENV_FILE"
echo "  data  : $HOST_DATA_DIR_VALUE"

docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --add-host=host.docker.internal:host-gateway \
  -p 8001:8001 \
  --env-file "$ENV_FILE" \
  -e "APP_ENV=$APP_ENV" \
  -e "HOST_DATA_DIR=$HOST_DATA_DIR_VALUE" \
  -v "$HOST_DATA_DIR_VALUE:/app/data" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "$IMAGE"

echo "查看日志: docker logs -f ${CONTAINER_NAME}"
