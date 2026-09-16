"""MCP 出站认证策略：兼容静态 Header，并按配置附加用户断言。"""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from app.utils.encryption import get_api_key_manager
from app.services.mcp.user_context_assertion import build_user_identity_payload


DEFAULT_IDENTITY_HEADER = "X-Nanzi-User-Context"
DEFAULT_ASSERTION_HEADER = DEFAULT_IDENTITY_HEADER
MCP_AUTH_HEADERS_PREFIX = "enc:v1:"


def encode_mcp_http_headers(headers: Mapping[str, Any] | None) -> dict[str, bytes]:
    """把 MCP 出站 Header 编成 UTF-8 bytes。

    httpcore 只允许 ASCII 字符串；含中文的身份 JSON 或 Token 必须以 bytes 发送，
    否则会在连接阶段报 ascii codec 错误。
    """
    encoded: dict[str, bytes] = {}
    for key, value in dict(headers or {}).items():
        name = str(key).strip()
        if not name:
            continue
        if isinstance(value, bytes):
            encoded[name] = value
            continue
        encoded[name] = str(value).encode("utf-8")
    return encoded


def generate_mcp_private_key_pem() -> str:
    """为一个 MCP 实例生成独立的 Ed25519 PKCS8 PEM 私钥。"""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    return Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    ).decode("utf-8")


def _parse_auth_headers(raw: Any) -> dict[str, str]:
    if not raw:
        return {}
    value = raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("MCP auth_headers must be a JSON object") from exc
    if not isinstance(value, Mapping):
        raise ValueError("MCP auth_headers must be a JSON object")
    return {str(key): str(item) for key, item in value.items() if str(key).strip()}


def encrypt_mcp_auth_headers(raw: Any) -> str:
    """加密保存 MCP 静态认证头，兼容接口传入的 JSON 字符串或映射。"""
    headers = _parse_auth_headers(raw)
    payload = json.dumps(headers, ensure_ascii=False, separators=(",", ":"))
    encrypted = get_api_key_manager().encrypt_api_key(payload)
    return f"{MCP_AUTH_HEADERS_PREFIX}{encrypted}"


def _stored_auth_headers(raw: Any) -> Any:
    if isinstance(raw, str) and raw.startswith(MCP_AUTH_HEADERS_PREFIX):
        encrypted = raw[len(MCP_AUTH_HEADERS_PREFIX):]
        return get_api_key_manager().decrypt_api_key(encrypted)
    return raw


def mcp_auth_headers_configured(server: Any) -> bool:
    """只返回认证配置状态，不向 API 响应暴露认证头内容。"""
    try:
        return bool(_parse_auth_headers(_stored_auth_headers(getattr(server, "auth_headers", None))))
    except (TypeError, ValueError):
        # 历史脏值仍视为已配置，避免 UI 误导用户覆盖未知凭据。
        raw = getattr(server, "auth_headers", None)
        return bool(str(raw or "").strip() not in {"", "{}", "null"})


def resolve_mcp_auth_headers(server: Any) -> dict[str, str]:
    """解析固定 MCP 凭证，优先使用新加密字段并兼容旧 auth_headers。"""
    headers = _parse_auth_headers(_stored_auth_headers(getattr(server, "auth_headers", None)))
    encrypted_token = getattr(server, "fixed_token_encrypted", None)
    if encrypted_token:
        token = get_api_key_manager().decrypt_api_key(encrypted_token)
        headers["Authorization"] = f"Bearer {token}"
    return headers


def mcp_auth_headers_summary(server: Any) -> tuple[bool, dict[str, str]]:
    """返回 Authorization 状态与脱敏后的其他 Header，不返回任何凭证原文。"""
    try:
        headers = resolve_mcp_auth_headers(server)
    except (TypeError, ValueError):
        return False, {}

    authorization_configured = any(
        str(key).strip().casefold() == "authorization" and str(value).strip()
        for key, value in headers.items()
    )
    masked_headers = {
        str(key): "********"
        for key in headers
        if str(key).strip().casefold() != "authorization"
    }
    return authorization_configured, masked_headers


def load_mcp_private_key(server: Any) -> Any:
    encrypted_key = str(
        getattr(server, "user_assertion_private_key_encrypted", "") or ""
    ).strip()
    if not encrypted_key:
        return None
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    raw_key = get_api_key_manager().decrypt_api_key(encrypted_key)
    return load_pem_private_key(raw_key.encode("utf-8"), password=None)


def build_mcp_headers(
    server: Any,
    *,
    user_info: Mapping[str, Any] | None = None,
    agent_info: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    private_key: Any = None,
    issuer: str = "nanzi-platform",
) -> dict[str, str]:
    """根据 MCP Server 配置构造一次出站请求 Header。

    用户身份只在显式开启时以明文 JSON 附加，默认行为完全保留旧的静态 auth_headers。
    """
    headers = resolve_mcp_auth_headers(server)
    # 用户身份透传独立于 MCP 自身认证。没有 Authorization 时也可以只发明文身份 Header。
    enabled = bool(getattr(server, "user_assertion_enabled", False))
    if not enabled:
        return headers

    effective_request_id = str(request_id or uuid.uuid4())
    payload = build_user_identity_payload(
        user_info=user_info or {},
        agent_info=agent_info or {},
        request_id=effective_request_id,
    )
    headers[DEFAULT_IDENTITY_HEADER] = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    headers["X-Request-ID"] = effective_request_id
    return headers
