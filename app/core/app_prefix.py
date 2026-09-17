"""Public URL prefix for root (/) or subdirectory (/zhiyuan) reverse-proxy deploys.

应用仍监听 ``/`` + ``/api``。线上共用 Host 时由 Nginx 剥掉 ``/zhiyuan``（见
``docker/nginx-zhiyuan.example.conf``）。本机直连 ``http://localhost:8001/zhiyuan``
时中间件会剥前缀。

不要把前缀写进 ASGI ``scope["root_path"]``：Starlette StaticFiles 在
``root_path`` + 已剥路径下会 404。SPA/Cookie 只走 ContextVar 与 ``APP_ROOT_PATH``。
二级目录生产部署仍须设置 ``APP_ROOT_PATH=/zhiyuan``（MCP issuer / 调度 / OpenAPI）。
"""

from __future__ import annotations

import json
import os
import re
from contextvars import ContextVar
from typing import Optional

from fastapi import Response
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

# 启用二级目录时的约定名（与 nginx location 保持一致）
DEFAULT_SUBPATH_NAME = "zhiyuan"

_HEADER_PREFIX = b"x-forwarded-prefix"
_HEADER_PROTO = b"x-forwarded-proto"
_request_prefix: ContextVar[str] = ContextVar("app_root_path", default="")
_request_secure: ContextVar[bool] = ContextVar("app_request_secure", default=False)
_BASE_TAG_RE = re.compile(r"<base\b[^>]*>", re.IGNORECASE)
_APP_BASE_SCRIPT_RE = re.compile(
    r"<script>\s*window\.__APP_BASE_PATH__\s*=\s*(?:'[^']*'|\"[^\"]*\")\s*;\s*</script>",
    re.IGNORECASE,
)


def normalize_root_path(value: Optional[str]) -> str:
    text = (value or "").strip()
    if not text or text == "/":
        return ""
    return "/" + text.strip("/")


def configured_root_path() -> str:
    try:
        from app.core.config import settings
        return normalize_root_path(getattr(settings, "APP_ROOT_PATH", None) or os.getenv("APP_ROOT_PATH"))
    except Exception:
        return normalize_root_path(os.getenv("APP_ROOT_PATH") or os.getenv("ROOT_PATH"))


def _header_root_path(scope: Scope) -> str:
    for key, raw in scope.get("headers") or []:
        if key == _HEADER_PREFIX:
            return normalize_root_path(raw.decode("latin-1"))
    return ""


def _incoming_path(scope: Scope) -> str:
    return str(scope.get("path") or "").split("?", 1)[0] or "/"


def _path_has_root_prefix(path: str, root: str) -> bool:
    if not root:
        return False
    return path == root or path.startswith(f"{root}/")


def inferred_root_path(path: str) -> str:
    default = normalize_root_path(DEFAULT_SUBPATH_NAME)
    if _path_has_root_prefix(path, default):
        return default
    return ""


def strip_root_from_path(path: str, root: str) -> str:
    if not _path_has_root_prefix(path, root):
        return path or "/"
    remainder = path[len(root):] or "/"
    return remainder if remainder.startswith("/") else f"/{remainder}"


def resolve_root_path(scope: Scope) -> str:
    path = _incoming_path(scope)
    configured = configured_root_path()
    header = _header_root_path(scope)
    if configured and _path_has_root_prefix(path, configured):
        return configured
    if header and _path_has_root_prefix(path, header):
        return header
    inferred = inferred_root_path(path)
    if inferred:
        return inferred
    return header or configured


def get_app_root_path(request: Optional[Request] = None) -> str:
    # 不读 scope["root_path"]：设置它会让 /assets 在二级目录下 404。
    return _request_prefix.get() or configured_root_path()


def cookie_path(request: Optional[Request] = None) -> str:
    return get_app_root_path(request) or "/"


def internal_request_path(request: Request) -> str:
    """Nginx 剥前缀之后的路由路径，供鉴权/白名单/审计使用。"""
    path = str(request.scope.get("path") or "").split("?", 1)[0]
    return path or "/"


def request_is_secure(request: Optional[Request] = None) -> bool:
    if request is not None:
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "").split(",")[0].strip().lower()
        return proto == "https"
    return _request_secure.get()


def public_base_url(fallback: str = "http://localhost:8001", request: Optional[Request] = None) -> str:
    try:
        from app.core.config import settings
        raw = str(getattr(settings, "APP_PUBLIC_URL", None) or fallback).rstrip("/")
    except Exception:
        raw = fallback.rstrip("/")
    return apply_root_to_public_base(raw, request)


def join_app_path(path: str, request: Optional[Request] = None) -> str:
    root = get_app_root_path(request)
    if not path:
        return root or "/"
    if path.startswith("http://") or path.startswith("https://"):
        return path
    normalized = path if path.startswith("/") else f"/{path}"
    if not root:
        return normalized
    if normalized == root or normalized.startswith(f"{root}/"):
        return normalized
    return f"{root}{normalized}"


def _path_already_has_root(path: str, root: str) -> bool:
    normalized = (path or "").rstrip("/")
    if not root or not normalized:
        return False
    if normalized == root:
        return True
    if not normalized.endswith(root):
        return False
    cut = len(normalized) - len(root)
    return cut == 0 or normalized[cut - 1] == "/"


def apply_root_to_public_base(public_base: str, request: Optional[Request] = None) -> str:
    """Append /zhiyuan to the platform origin. Do not use this on CDN prefixes."""
    base = (public_base or "").strip().rstrip("/")
    root = get_app_root_path(request) or configured_root_path()
    if not base or not root:
        return base
    from urllib.parse import urlparse
    parsed = urlparse(base if "://" in base else f"//{base}")
    path = (parsed.path or "").rstrip("/")
    if _path_already_has_root(path, root):
        return base
    return f"{base}{root}"


def _hostname_of(url: str) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url if "://" in url else f"//{url}")
    return (parsed.hostname or "").lower()


def apply_root_if_platform_origin(public_base: str, request: Optional[Request] = None) -> str:
    """给平台 Origin 补 ``/zhiyuan``；CDN 或已带自定义 path 的前缀原样返回。"""
    base = (public_base or "").strip().rstrip("/")
    if not base:
        try:
            from app.core.config import settings
            fallback = str(getattr(settings, "APP_PUBLIC_URL", None) or "").rstrip("/")
        except Exception:
            fallback = ""
        return apply_root_to_public_base(fallback, request)
    from urllib.parse import urlparse
    parsed = urlparse(base if "://" in base else f"//{base}")
    path = (parsed.path or "").rstrip("/")
    root = get_app_root_path(request) or configured_root_path()
    if path and not _path_already_has_root(path, root):
        return base
    try:
        from app.core.config import settings
        platform = str(getattr(settings, "APP_PUBLIC_URL", None) or "").strip()
    except Exception:
        platform = ""
    platform_host = _hostname_of(platform) if platform else ""
    base_host = (parsed.hostname or "").lower()
    if platform_host and base_host and platform_host != base_host:
        return base
    return apply_root_to_public_base(base, request)


def set_admin_token_cookie(
    response: Response,
    value: str,
    *,
    max_age: int = 86400,
    secure: Optional[bool] = None,
    request: Optional[Request] = None,
) -> None:
    response.set_cookie(
        key="admin_token",
        value=value,
        httponly=True,
        max_age=max_age,
        samesite="lax",
        secure=request_is_secure(request) if secure is None else secure,
        path=cookie_path(request),
    )


def clear_admin_token_cookie(response: Response, request: Optional[Request] = None) -> None:
    response.delete_cookie(key="admin_token", path=cookie_path(request))


def inject_spa_index(html: str, root_path: Optional[str] = None) -> str:
    prefix = normalize_root_path(root_path if root_path is not None else get_app_root_path())
    href = f"{prefix}/" if prefix else "/"
    snippet = (
        f'<base href="{href}">'
        f"<script>window.__APP_BASE_PATH__={json.dumps(prefix)};</script>"
    )
    cleaned = _APP_BASE_SCRIPT_RE.sub("", _BASE_TAG_RE.sub("", html), count=1)
    if "<head>" in cleaned:
        return cleaned.replace("<head>", f"<head>{snippet}", 1)
    if "<head " in cleaned.lower():
        return re.sub(r"<head\b[^>]*>", lambda m: m.group(0) + snippet, cleaned, count=1, flags=re.I)
    return snippet + cleaned


class AppRootPathMiddleware:
    """Strip ``/zhiyuan`` from the request path; keep the prefix in a ContextVar."""

    def __init__(self, app: ASGIApp, **_kwargs: object):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        path = _incoming_path(scope)
        root = resolve_root_path(scope)
        forwarded_proto = ""
        for key, raw in scope.get("headers") or []:
            if key == _HEADER_PROTO:
                forwarded_proto = raw.decode("latin-1").split(",")[0].strip().lower()
                break
        scheme = forwarded_proto or str(scope.get("scheme") or "")
        if (
            scope["type"] == "http"
            and root
            and path == root
            and str(scope.get("method") or "GET").upper() in ("GET", "HEAD")
        ):
            from starlette.responses import RedirectResponse
            await RedirectResponse(url=f"{root}/", status_code=307)(scope, receive, send)
            return
        scope = dict(scope)
        if root and _path_has_root_prefix(path, root):
            stripped = strip_root_from_path(path, root)
            scope["path"] = stripped
            raw = scope.get("raw_path")
            if isinstance(raw, (bytes, bytearray)):
                prefix = root.encode("ascii")
                if raw == prefix or raw.startswith(prefix + b"/"):
                    rest = bytes(raw[len(prefix):]) or b"/"
                    if not rest.startswith(b"/"):
                        rest = b"/" + rest
                    scope["raw_path"] = rest
        token = _request_prefix.set(root)
        secure_token = _request_secure.set(scheme == "https")
        try:
            await self.app(scope, receive, send)
        finally:
            _request_prefix.reset(token)
            _request_secure.reset(secure_token)
