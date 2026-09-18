"""嵌入会话 API 面硬隔离：只能走对话、兑换与嵌入运行所需的只读/会话接口。"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from fastapi import HTTPException, Request, status

from app.core.app_prefix import internal_request_path
from app.services.embed_identity import is_embed_session

# (method or *, path glob) — 嵌入 session 默认拒绝，仅允许白名单。
_EMBED_ALLOWED = (
    ("*", "/api/v1/chat/*"),
    ("*", "/api/v1/embed/tickets/exchange"),
    ("POST", "/api/v1/embed/tickets/exchange"),
    ("*", "/api/v1/sandbox/*/workspace"),
    ("*", "/api/v1/sandbox/*/workspace/*"),
    ("GET", "/api/portal/auth/me"),
    ("GET", "/api/portal/auth/user_apikey"),
    ("GET", "/api/portal/quota/me"),
    ("GET", "/api/portal/agents/allowed"),
    ("GET", "/api/portal/agents/*/welcome-cards"),
    ("GET", "/api/portal/agents/*/embed-access"),
    ("GET", "/api/portal/portal-prefs"),
    ("PUT", "/api/portal/portal-prefs"),
    ("PUT", "/api/portal/portal-prefs/routing"),
    ("GET", "/api/portal/metadata/datasets/accessible"),
    ("GET", "/api/portal/ragflow/config"),
    ("GET", "/api/portal/ragflow/datasets"),
    ("GET", "/api/portal/ragflow/datasets/*/documents/*/file"),
    ("GET", "/api/portal/skills"),
    ("GET", "/api/portal/skills/personal"),
    ("GET", "/api/portal/tools/mcp"),
    ("*", "/api/portal/slash-commands"),
    ("*", "/api/portal/slash-commands/"),
    ("*", "/api/portal/slash-commands/*"),
    ("GET", "/api/portal/workbench/home"),
    ("GET", "/api/portal/saved-reports"),
    ("GET", "/api/portal/saved-reports/*"),
    ("GET", "/api/portal/models"),
    ("POST", "/api/portal/saved-reports/*/preview"),
    ("POST", "/api/portal/saved-reports/*/execute"),
    ("POST", "/api/portal/saved-reports/*/analyze"),
    ("POST", "/api/portal/chat/feedback"),
    ("POST", "/api/portal/chatbi-briefs"),
    ("POST", "/api/portal/chatbi-monitors"),
    ("POST", "/api/portal/chatbi-export/result"),
    ("PUT", "/api/portal/portal-prefs/markdown-theme"),
    ("GET", "/api/portal/memory/my/summaries"),
    ("GET", "/api/portal/memory/my/summaries/*"),
    ("DELETE", "/api/portal/memory/my/summaries/*"),
    ("DELETE", "/api/portal/memory/my/session-memory"),
)

_EMBED_DENIED_PREFIXES = (
    "/api/portal/management",
    "/api/portal/mcp/",
    "/api/portal/mcp-service",
    "/api/portal/roles",
    "/api/portal/system",
    "/api/portal/keys",
    "/api/portal/embed-apps",
    "/api/portal/audit",
    "/api/v1/users",
    "/api/v1/schema",
    "/api/v1/chatbi/sql",
)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    if "*" not in pattern:
        return re.compile("^" + re.escape(pattern) + r"/?$")
    if pattern.endswith("/*") and pattern.count("*") == 1:
        return re.compile("^" + re.escape(pattern[:-2]) + r"(?:/.*)?$")
    regex = "^"
    for index, piece in enumerate(pattern.split("*")):
        if index:
            regex += "[^/]+"
        regex += re.escape(piece)
    return re.compile(regex + r"/?$")


_COMPILED = tuple(
    (method, _glob_to_regex(path))
    for method, path in _EMBED_ALLOWED
)


def _normalize_path(path: str) -> str:
    text = str(path or "").split("?", 1)[0]
    if len(text) > 1:
        text = text.rstrip("/")
    return text or "/"


def embed_path_allowed(method: str, path: str) -> bool:
    normalized = _normalize_path(path)
    verb = str(method or "GET").upper()
    for prefix in _EMBED_DENIED_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix.rstrip("/") + "/"):
            return False
    for allowed_method, regex in _COMPILED:
        if allowed_method not in {"*", verb}:
            continue
        if regex.match(normalized) or regex.match(normalized + "/"):
            return True
        # 带尾部斜杠的路由
        if regex.match(path.split("?", 1)[0]):
            return True
    return False


def enforce_embed_api_surface(request: Request, user_info: Optional[Mapping[str, Any]]) -> None:
    if not is_embed_session(user_info):
        return
    path = internal_request_path(request)
    if embed_path_allowed(request.method, path):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="嵌入会话不能调用该接口",
    )
