# 构建前必须已有 frontend/dist、vendor/venv、vendor/ms-playwright。
# 本地：./docker/docker-build.sh
# docker-ops 编译段：
#   1) node:20                 sh docker/ci/compile-frontend.sh
#   2) python:3.11-slim-bookworm  sh docker/ci/compile-python.sh
ARG BASE_IMAGE=docker.1ms.run/library/python:3.11-slim-bookworm
FROM ${BASE_IMAGE}

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    PLATFORM_TIMEZONE=Asia/Shanghai \
    VIRTUAL_ENV=/app/vendor/venv \
    PATH="/app/vendor/venv/bin:${PATH}" \
    PLAYWRIGHT_BROWSERS_PATH=/app/vendor/ms-playwright

# 运行时系统库（阿里云 Debian 源）。SQL Server 驱动改为编译期不拉取，避免卡住。
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e 's|http://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        -e 's|https://deb.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        -e 's|http://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
        -e 's|https://deb.debian.org/debian|http://mirrors.aliyun.com/debian|g' \
        -e 's|http://security.debian.org/debian-security|http://mirrors.aliyun.com/debian-security|g' \
        /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i \
        -e 's|deb.debian.org|mirrors.aliyun.com|g' \
        -e 's|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list; \
    fi; \
    printf '%s\n' \
      'Acquire::Retries "5";' \
      'Acquire::http::Timeout "30";' \
      'Acquire::https::Timeout "30";' \
      > /etc/apt/apt.conf.d/80-retries; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      curl ca-certificates tzdata git procps \
      unixodbc unixodbc-dev; \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime; \
    echo $TZ > /etc/timezone; \
    (apt-get install -y --no-install-recommends libaio1 \
      || apt-get install -y --no-install-recommends libaio1t64); \
    ln -sf /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1 2>/dev/null || true; \
    rm -rf /var/lib/apt/lists/*

COPY vendor/venv /app/vendor/venv
COPY vendor/ms-playwright /app/vendor/ms-playwright

RUN /app/vendor/venv/bin/python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN test -f /app/frontend/dist/index.html \
    && test -x /app/vendor/venv/bin/uvicorn \
    && chmod +x /app/docker/docker-entrypoint.sh

EXPOSE 8001

ENTRYPOINT ["/app/docker/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
