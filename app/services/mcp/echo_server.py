"""NanZi 内置 Echo MCP：用于验证 MCP 调用链路和用户身份透传。"""

from __future__ import annotations

import hmac
import json
import uuid
from contextlib import asynccontextmanager
from collections.abc import Mapping
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import select

from app.core.app_prefix import apply_root_to_public_base
from app.core.config import settings
from app.models.mcp import McpServer
from app.services.mcp.mcp_auth_policy import (
    DEFAULT_IDENTITY_HEADER,
    resolve_mcp_auth_headers,
)
from app.services.mcp.transport_security import (
    _parse_public_url,
    build_mcp_transport_security,
)


ECHO_SERVER_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "nanzi:mcp:echo"))
ECHO_SERVER_NAME = "NanZi Echo 测试 MCP"
ECHO_TOOL_NAME = f"{ECHO_SERVER_NAME}:echo"
ECHO_TOOL_DESCRIPTION = "验证 MCP 请求是否收到，以及 NanZi 用户身份 Header 是否已明文送达。"
_USER_CONTEXT_FIELDS = (
    "user_id",
    "user_name",
    "real_name",
    "role",
    "is_admin",
    "dept_code",
    "org_path",
)
_AGENT_CONTEXT_FIELDS = ("agent_id", "agent_version_id", "agent_name")


def build_echo_transport_security(
    public_url: str | None,
) -> TransportSecuritySettings | None:
    """根据公网地址构造 Echo MCP 的 DNS rebinding 防护配置。"""
    return build_mcp_transport_security(public_url)


def resolve_echo_base_url(request_base_url: str, public_url: str | None) -> str:
    """优先使用有效 APP_PUBLIC_URL，否则回退到当前请求地址。"""
    parsed = _parse_public_url(public_url)
    if parsed is not None:
        return apply_root_to_public_base(parsed[0])
    return apply_root_to_public_base(str(request_base_url).rstrip("/"))


def _mask_secret(value: str | None, *, prefix_length: int = 6, suffix_length: int = 6) -> str | None:
    """仅用于诊断展示，确保短凭证也不会原样返回。"""
    if not value:
        return None
    if len(value) <= prefix_length + suffix_length:
        return "***"
    return f"{value[:prefix_length]}***{value[-suffix_length:]}"


def _mask_authorization(value: str | None) -> str | None:
    """保留认证方案，脱敏 Bearer 凭证内容。"""
    if not value:
        return None
    scheme, separator, credentials = value.partition(" ")
    if separator and scheme.casefold() == "bearer":
        return f"{scheme} {_mask_secret(credentials, prefix_length=4, suffix_length=4)}"
    return _mask_secret(value, prefix_length=4, suffix_length=4)


def _get_header(headers: Mapping[str, Any], name: str) -> str | None:
    """兼容 Starlette Headers 和普通字典的大小写不敏感读取。"""
    direct = headers.get(name)
    if direct is not None:
        return str(direct)
    normalized = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == normalized:
            return str(value)
    return None


def _authorization_is_valid(headers: Mapping[str, Any], server: Any) -> bool:
    expected = resolve_mcp_auth_headers(server).get("Authorization")
    actual = _get_header(headers, "Authorization")
    if not expected or not actual:
        raise ValueError("Echo MCP 未配置 Authorization Bearer Token")
    return hmac.compare_digest(actual, expected)


def _parsed_identity_diagnostics(
    raw_identity: str,
    *,
    request_id_received: bool,
) -> dict[str, Any]:
    try:
        payload = json.loads(raw_identity)
    except json.JSONDecodeError as exc:
        raise PermissionError("NanZi 用户身份 Header 不是合法 JSON") from exc
    if not isinstance(payload, Mapping):
        raise PermissionError("NanZi 用户身份 Header 必须是 JSON 对象")
    user_id = str(payload.get("user_id") or "").strip()
    if not user_id:
        raise PermissionError("NanZi 用户身份 Header 缺少 user_id")

    user_context = {
        key: payload[key]
        for key in _USER_CONTEXT_FIELDS
        if payload.get(key) is not None
    }
    user_context["user_id"] = user_id
    agent_context = {
        key: payload[key]
        for key in _AGENT_CONTEXT_FIELDS
        if payload.get(key) is not None
    }
    custom_attributes = payload.get("custom_attributes")
    if not isinstance(custom_attributes, Mapping):
        custom_attributes = {}

    return {
        "user_assertion_valid": True,
        "request_id_received": request_id_received,
        "verified_user_id": user_id,
        "verified_user_context": user_context,
        "custom_attributes": dict(custom_attributes),
        "verified_agent_context": agent_context,
        "request_context": {
            "request_id": payload.get("request_id"),
            "request_id_header_received": request_id_received,
        },
    }


def build_echo_diagnostics(
    headers: Mapping[str, Any],
    server: Any,
    private_key: Any = None,
) -> dict[str, Any]:
    """校验一次 Echo 请求并返回不含原始凭证的安全诊断结果。"""
    processing_log: list[str] = []
    authorization = _get_header(headers, "Authorization")
    if authorization:
        processing_log.append("已收到 Authorization 请求头")
    else:
        processing_log.append("未收到 Authorization 请求头")

    authorization_valid = _authorization_is_valid(headers, server)
    if not authorization_valid:
        processing_log.append("Authorization Bearer Token 校验失败")
        raise PermissionError("Echo MCP Authorization Bearer Token 无效")
    processing_log.append("Authorization Bearer Token 校验通过")

    identity_header = DEFAULT_IDENTITY_HEADER
    identity = _get_header(headers, identity_header)
    request_id_received = bool(_get_header(headers, "X-Request-ID"))
    authorization_masked = _mask_authorization(authorization)
    diagnostics: dict[str, Any] = {
        "authorization_valid": True,
        "authorization_masked": authorization_masked,
        "user_assertion_received": bool(identity),
        "user_assertion_valid": False,
        "user_assertion_masked": _mask_secret(identity),
        "request_id_received": request_id_received,
        "processing_log": processing_log,
    }
    if identity:
        processing_log.append(f"已收到 {identity_header} 请求头")
        diagnostics.update(
            _parsed_identity_diagnostics(
                identity,
                request_id_received=request_id_received,
            )
        )
        processing_log.append("已解析明文用户身份")
        processing_log.append("已解析用户、扩展字段、智能体和请求信息")
    else:
        processing_log.append(f"未收到 {identity_header} 请求头")
    return {"message": "已收到", "diagnostics": diagnostics}


async def _load_echo_server() -> McpServer:
    from app.core.orm import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        server = (
            await db.execute(
                select(McpServer).where(McpServer.id == ECHO_SERVER_ID)
            )
        ).scalar_one_or_none()
    if server is None or not server.enabled_status:
        raise ValueError("Echo MCP 尚未创建或已被禁用")
    return server


echo_mcp = FastMCP(
    ECHO_SERVER_NAME,
    instructions="用于验证 NanZi MCP 协议和用户身份透传，不执行任何业务操作。",
    streamable_http_path="/mcp",
    json_response=True,
    stateless_http=True,
    transport_security=build_echo_transport_security(settings.APP_PUBLIC_URL),
)


@asynccontextmanager
async def echo_mcp_lifespan():
    """把 FastMCP Streamable HTTP 的 Task Group 接入宿主应用生命周期。"""
    async with echo_mcp.session_manager.run():
        yield


@echo_mcp.tool(name="echo", description=ECHO_TOOL_DESCRIPTION)
async def echo(ctx: Context) -> dict[str, Any]:
    """返回 Echo 请求的安全认证诊断。"""
    server = await _load_echo_server()
    request = getattr(getattr(ctx, "request_context", None), "request", None)
    headers = getattr(request, "headers", {}) if request is not None else {}
    return build_echo_diagnostics(headers, server)


def echo_tool_schema() -> str:
    """返回内置 echo 工具的稳定 JSON Schema，供 MCP 管理页缓存。"""
    return json.dumps(
        {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
