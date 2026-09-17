"""会话存储与执行链使用的稳定用户身份边界。

会话存储钥匙（Redis 历史、HITL、artifact、AgentScope state/lock/pending、工作区）
优先 ``session_owner``（嵌入 ``e:…``），否则 ``user_id`` / ``id``。

控制面（ACL、配额、默认 MCP、SQL 行级改写）不要用本模块，请用
``embed_identity.platform_acl_user_id`` 或数据面整型 user_id。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any


class MissingUserIdentityError(ValueError):
    """请求没有可用于会话隔离的可靠用户身份。"""


def require_user_id(value: Any) -> str:
    """提取并归一化稳定会话用户 ID；缺失时 fail closed。

    ``anonymous`` 不是用户身份，不能作为会话历史、资源范围或压缩记录的
    fallback。调用方可将本异常转换为 HTTP 401，也可让内部执行链直接终止。
    """

    raw_value = value
    if isinstance(value, Mapping):
        owner = str(value.get("session_owner") or "").strip()
        if owner:
            return owner
        raw_value = value.get("user_id") or value.get("id")
    elif not isinstance(value, (str, int)):
        raw_value = getattr(value, "user_id", None) or getattr(value, "id", None)

    normalized = str(raw_value).strip() if raw_value is not None else ""
    if not normalized or normalized.lower() == "anonymous":
        raise MissingUserIdentityError(
            "缺少可靠用户身份，禁止访问或创建会话上下文"
        )
    return normalized


def try_session_user_id(value: Any) -> str | None:
    """会话存储钥匙；缺失时返回 None 而不是抛。"""
    try:
        return require_user_id(value)
    except MissingUserIdentityError:
        return None


def session_user_id_from_agent_context(context: Any) -> str:
    """从 AgentContext 取会话存储钥匙。

    ``AgentContext.user_id`` 是控制面整型（嵌入为签发人）；会话 Redis / 工作区
    必须优先 ``user_dimensions.session_owner``。
    """
    if context is None:
        raise MissingUserIdentityError(
            "缺少可靠用户身份，禁止访问或创建会话上下文"
        )
    dims = getattr(context, "user_dimensions", None) or {}
    if isinstance(dims, Mapping):
        owner = str(dims.get("session_owner") or "").strip()
        if owner:
            return owner
    return require_user_id(getattr(context, "user_id", None))


def try_session_user_id_from_agent_context(context: Any) -> str | None:
    try:
        return session_user_id_from_agent_context(context)
    except MissingUserIdentityError:
        return None


def user_info_from_agent_context(context: Any) -> dict[str, Any]:
    """把 AgentContext 收成可交给 ``require_user_id`` / 工作区解析的 user_info。"""
    dims = dict(getattr(context, "user_dimensions", None) or {}) if context is not None else {}
    user_id = getattr(context, "user_id", None) if context is not None else None
    return {
        "user_id": user_id,
        "id": dims.get("id") or user_id,
        "user_name": dims.get("user_name") or dims.get("username"),
        "username": dims.get("username") or dims.get("user_name"),
        "session_owner": dims.get("session_owner") or "",
        "external_subject": dims.get("external_subject") or "",
    }


def prompt_display_user_id(user_info: Any) -> str:
    """提示词/画像展示用的业务身份，不是控制面签发人。

    嵌入优先 ``external_subject``，否则 ``session_owner``；不要把 ``user_id=1``
    或哈希 ``e:…`` 以外的平台整型误当成宿主业务用户编号。
    """
    if not isinstance(user_info, Mapping):
        return ""
    subject = str(user_info.get("external_subject") or "").strip()
    if subject:
        return subject
    owner = str(user_info.get("session_owner") or "").strip()
    if owner:
        return owner
    return str(user_info.get("user_id") or user_info.get("id") or "").strip()


_SESSION_OWNER_BIGINT_FLAG = 0x4000000000000000
_SESSION_OWNER_BIGINT_MASK = 0x3FFFFFFFFFFFFFFF


def session_numeric_user_id(user_info: Any) -> int | None:
    """需要整型主键的会话附属资源（浏览器 profile 等）。

    嵌入用 ``session_owner`` 稳定哈希，避免多个业务用户共用签发人的行；
    哈希落在 ``2^62`` 区间，与平台顺序 user_id 错开。
    """
    if not isinstance(user_info, Mapping):
        return None
    owner = str(user_info.get("session_owner") or "").strip()
    if owner:
        digest = hashlib.sha256(owner.encode("utf-8")).digest()
        return _SESSION_OWNER_BIGINT_FLAG | (
            int.from_bytes(digest[:8], "big") & _SESSION_OWNER_BIGINT_MASK
        )
    raw = user_info.get("user_id") or user_info.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


__all__ = [
    "MissingUserIdentityError",
    "require_user_id",
    "try_session_user_id",
    "session_user_id_from_agent_context",
    "try_session_user_id_from_agent_context",
    "user_info_from_agent_context",
    "prompt_display_user_id",
    "session_numeric_user_id",
]
