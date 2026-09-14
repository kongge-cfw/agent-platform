#!/bin/sh
# 按 APP_ENV 加载镜像内 config/env/{base,dev,prod}.env。
# 容器启动时已注入的变量（docker --env-file / -e）优先，不会被覆盖。
set -eu

APP_ENV="${APP_ENV:-prod}"
case "$APP_ENV" in
  dev|prod) ;;
  *)
    echo "Invalid APP_ENV='$APP_ENV' (allowed: dev, prod)" >&2
    exit 1
    ;;
esac

is_set() {
  eval "[ \"\${$1+set}\" = set ]"
}

load_env_file() {
  _file="$1"
  if [ ! -f "$_file" ]; then
    echo "Skip missing env file: $_file"
    return 0
  fi
  echo "Loading env file: $_file"
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
    esac
    key=${line%%=*}
    key=$(printf '%s' "$key" | tr -d ' \t\r')
    case "$key" in
      ''|*[!A-Za-z0-9_]*) continue ;;
    esac
    if is_set "$key"; then
      continue
    fi
    value=${line#*=}
    value=$(printf '%s' "$value" | tr -d '\r')
    case "$value" in
      \"*\") value=${value#\"}; value=${value%\"} ;;
      \'*\') value=${value#\'}; value=${value%\'} ;;
    esac
    export "$key=$value"
  done < "$_file"
}

ENV_DIR="/app/config/env"
load_env_file "$ENV_DIR/base.env"
load_env_file "$ENV_DIR/${APP_ENV}.env"

export APP_ENV
if ! is_set API_SERVICE_ENV; then
  export API_SERVICE_ENV="$APP_ENV"
fi

echo "Using APP_ENV=$APP_ENV"
exec "$@"
