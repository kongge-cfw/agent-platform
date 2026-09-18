"""嵌入会话的应用身份与业务身份分层。

控制面（能否嵌某个智能体、配额、表/知识库 ACL）认签发 Ticket 的服务账号。
数据面（SQL 行级、MCP Header、会话归属）认 Ticket 内的业务 claims。
业务身份只能由宿主后端经 Ticket 传入，不能来自 iframe / postMessage。
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping, Optional

from app.services.ai.business_context import AUTHENTICATED_IDENTITY_KEYS, sanitize_business_context

EMBED_SESSION_TYPE = "embed"
EMBED_SHADOW_REMARK_PREFIX = "embed:shadow"
MAX_SHADOW_USER_NAME_LEN = 50
MAX_EXTRA_DATA_BYTES = 8 * 1024

_SUBJECT_SAFE_RE = re.compile(r"[^a-zA-Z0-9._:-]+")

# 业务 claims 不得把平台管理员、权限列表写进执行身份。
_FORBIDDEN_CLAIM_KEYS = AUTHENTICATED_IDENTITY_KEYS | frozenset(
    {
        "session_type",
        "created_by_user_id",
        "created_by_user_name",
        "created_by_role",
        "platform_user_id",
        "platform_user_name",
        "platform_role",
        "external_subject",
    }
)


def is_embed_session(user_info: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(user_info, Mapping):
        return False
    return str(user_info.get("session_type") or "").strip().lower() == EMBED_SESSION_TYPE


def is_shadow_remark(remark: Any) -> bool:
    return str(remark or "").strip().lower().startswith(EMBED_SHADOW_REMARK_PREFIX)


def shadow_remark_for_operator(operator_user_id: Any) -> str:
    return f"{EMBED_SHADOW_REMARK_PREFIX}:{operator_user_id}"


def _session_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def locked_agent_id(user_info: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(user_info, Mapping):
        return ""
    agent_key = str(user_info.get("agent_id") or "").strip()
    if not agent_key:
        return ""
    lock_flag = user_info.get("lock_entry_agent")
    # 旧 Ticket 没有该字段：有 agent_id 即视为锁定入口。
    if lock_flag in (None, ""):
        return agent_key
    if not _session_flag(lock_flag):
        return ""
    return agent_key


def embed_role_id(user_info: Optional[Mapping[str, Any]]) -> Optional[int]:
    if not isinstance(user_info, Mapping):
        return None
    raw = user_info.get("embed_role_id")
    if raw in (None, "", 0, "0"):
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def default_entry_agent_id(user_info: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(user_info, Mapping):
        return ""
    return str(user_info.get("default_entry_agent_id") or "").strip()


def _user_info_for_delegation_host(user_info: Optional[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    if isinstance(user_info, Mapping):
        return user_info
    try:
        from app.core.context import get_current_agent_context

        ctx = get_current_agent_context()
        dims = getattr(ctx, "user_dimensions", None) if ctx is not None else None
        if isinstance(dims, Mapping):
            return dims
    except Exception:
        return None
    return None


def can_host_smart_delegation(agent_config: Any, user_info: Optional[Mapping[str, Any]] = None) -> bool:
    """本会话的委派宿主才能挂载智能委派。

    嵌入：只认 ``default_entry_agent_id``（空=不智能委派，不回落平台 Main）。
    非嵌入：只认平台主助手 ``is_main_general_agent``。
    """
    if agent_config is None:
        return False
    info = _user_info_for_delegation_host(user_info)
    agent_id = getattr(agent_config, "agent_id", None) or getattr(agent_config, "id", None)
    agent_name = getattr(agent_config, "agent_name", None) or getattr(agent_config, "name", None)
    if is_embed_session(info):
        host = default_entry_agent_id(info)
        if not host:
            return False
        return agent_config_matches_lock(agent_id, agent_name, host)
    from app.services.ai.skill_resolver import is_main_general_agent

    return is_main_general_agent(agent_config)


def agent_matches_lock(agent: Any, locked_key: str) -> bool:
    key = str(locked_key or "").strip()
    if not key or agent is None:
        return not key
    agent_id = str(getattr(agent, "id", "") or "").strip()
    agent_name = str(getattr(agent, "name", "") or "").strip()
    return key in {agent_id, agent_name}


def agent_config_matches_lock(agent_id: Any, agent_name: Any, locked_key: str) -> bool:
    key = str(locked_key or "").strip()
    if not key:
        return True
    candidates = {
        str(agent_id or "").strip(),
        str(agent_name or "").strip(),
    }
    return key in candidates


def platform_acl_user_id(user_info: Optional[Mapping[str, Any]]) -> Optional[int]:
    """控制面鉴权用的南孜用户 ID：嵌入会话用签发人，否则用当前用户。"""
    if not isinstance(user_info, Mapping):
        return None
    raw = user_info.get("created_by_user_id") if is_embed_session(user_info) else (
        user_info.get("user_id") or user_info.get("id")
    )
    if raw in (None, ""):
        raw = user_info.get("platform_user_id") or user_info.get("user_id") or user_info.get("id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def platform_acl_user_name(user_info: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(user_info, Mapping):
        return ""
    if is_embed_session(user_info):
        name = str(
            user_info.get("created_by_user_name")
            or user_info.get("platform_user_name")
            or ""
        ).strip()
        if name:
            return name
    return str(user_info.get("user_name") or user_info.get("username") or "").strip()


def is_platform_admin(user_info: Optional[Mapping[str, Any]]) -> bool:
    """平台管理员仅属于控制面；嵌入业务身份永远不是平台管理员。"""
    if not isinstance(user_info, Mapping) or is_embed_session(user_info):
        return False
    return str(user_info.get("role") or "").strip().lower() == "admin"


def operator_is_admin(user_info: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(user_info, Mapping):
        return False
    if is_embed_session(user_info):
        return str(
            user_info.get("created_by_role") or user_info.get("platform_role") or ""
        ).strip().lower() == "admin"
    return str(user_info.get("role") or "").strip().lower() == "admin"


def shadow_username(subject: str) -> str:
    """把业务 subject 收成 ai_agent_users.user_name（最长 50）。"""
    cleaned = _SUBJECT_SAFE_RE.sub("_", str(subject or "").strip()).strip("._-")
    candidate = f"ext:{cleaned}" if cleaned else ""
    if candidate and len(candidate) <= MAX_SHADOW_USER_NAME_LEN:
        return candidate
    digest = hashlib.sha256(str(subject or "").encode("utf-8")).hexdigest()[:16]
    return f"ext:{digest}"


def sanitize_identity_extra_data(value: Any) -> dict[str, Any]:
    sanitized = sanitize_business_context(value)
    if not isinstance(sanitized, dict):
        return {}
    cleaned: dict[str, Any] = {}
    for key, item in sanitized.items():
        normalized = str(key).strip()
        if not normalized or normalized.lower() in _FORBIDDEN_CLAIM_KEYS:
            continue
        cleaned[normalized] = item
    serialized = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > MAX_EXTRA_DATA_BYTES:
        raise ValueError("identity.extra_data 超过大小限制")
    return cleaned


def build_shadow_extra_data(
    *,
    subject: str,
    tenant_id: str = "",
    extra_data: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    payload = sanitize_identity_extra_data(extra_data)
    payload["external_subject"] = str(subject).strip()
    tenant = str(tenant_id or "").strip()
    if tenant:
        payload["tenant_id"] = tenant
    return payload


def extra_data_json(payload: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(payload or {}), ensure_ascii=False, separators=(",", ":"))


def build_session_owner(*, app_key: str, subject: str, fallback_user_id: Any) -> str:
    """嵌入会话的稳定归属键：优先 (应用, subject)，否则退回用户 ID。"""
    app = str(app_key or "").strip() or "_"
    sub = str(subject or "").strip()
    if sub:
        digest = hashlib.sha256(f"{app}|{sub}".encode("utf-8")).hexdigest()[:40]
        return f"e:{digest}"
    return str(fallback_user_id or "").strip()


def embed_numeric_user_id(user_info: Optional[Mapping[str, Any]]) -> Optional[int]:
    if not isinstance(user_info, Mapping):
        return None
    for raw in (user_info.get("user_id"), user_info.get("id"), user_info.get("created_by_user_id")):
        if raw in (None, ""):
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def conversation_owner_id(user_info: Optional[Mapping[str, Any]]) -> str:
    """会话历史/Redis 记忆用的 owner：有 claims 时用 session_owner，否则用 user_id。"""
    if not isinstance(user_info, Mapping):
        return ""
    owner = str(user_info.get("session_owner") or "").strip()
    if owner:
        return owner
    return str(user_info.get("user_id") or user_info.get("id") or "").strip()


def skip_sql_row_rewrite(user_info: Optional[Mapping[str, Any]]) -> bool:
    if not is_embed_session(user_info):
        return False
    mode = str((user_info or {}).get("data_permission_mode") or "").strip().lower()
    return mode == "mcp_only"


def isolate_datasets_by_tenant(user_info: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(user_info, Mapping):
        return False
    return str(user_info.get("isolate_datasets_by_tenant") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def claims_tenant_id(user_info: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(user_info, Mapping):
        return ""
    tenant = str(user_info.get("tenant_id") or "").strip()
    if tenant:
        return tenant
    extra = user_info.get("extra_data")
    if isinstance(extra, str) and extra.strip():
        try:
            extra = json.loads(extra)
        except json.JSONDecodeError:
            extra = {}
    if isinstance(extra, Mapping):
        return str(extra.get("tenant_id") or "").strip()
    return ""


def resource_visible_for_tenant(resource: Any, user_info: Optional[Mapping[str, Any]]) -> bool:
    if not isolate_datasets_by_tenant(user_info):
        return True
    tenant = claims_tenant_id(user_info)
    if not tenant:
        return False
    resource_tenant = str(getattr(resource, "tenant_id", "") or "").strip()
    if isinstance(resource, Mapping):
        resource_tenant = str(resource.get("tenant_id") or "").strip()
    return (not resource_tenant) or resource_tenant == tenant


def resolve_catalog_acl_from_context(ctx: Any) -> dict[str, Any]:
    dims = dict(getattr(ctx, "user_dimensions", None) or {})
    if getattr(ctx, "user_id", None) is not None:
        dims.setdefault("user_id", ctx.user_id)
    return resolve_catalog_acl(dims)


def resolve_catalog_acl(user_info: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """目录/资源范围用的控制面身份：嵌入认签发人，且永不按业务 claims 升管理员。"""
    if not isinstance(user_info, Mapping):
        return {
            "user_id": None,
            "user_name": "",
            "is_admin": False,
            "tenant_id": "",
            "isolate_by_tenant": False,
        }
    if is_embed_session(user_info):
        return {
            "user_id": platform_acl_user_id(user_info),
            "user_name": platform_acl_user_name(user_info),
            "is_admin": False,
            "tenant_id": claims_tenant_id(user_info),
            "isolate_by_tenant": isolate_datasets_by_tenant(user_info),
        }
    raw = user_info.get("user_id") or user_info.get("id")
    try:
        user_id = int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        user_id = None
    return {
        "user_id": user_id,
        "user_name": str(user_info.get("user_name") or user_info.get("username") or "").strip(),
        "is_admin": is_platform_admin(user_info),
        "tenant_id": claims_tenant_id(user_info),
        "isolate_by_tenant": False,
    }


def normalize_embed_user_info(user_info: Mapping[str, Any]) -> dict[str, Any]:
    """嵌入会话强制数据面非管理员，保留签发人供控制面使用。"""
    normalized = dict(user_info)
    if not is_embed_session(normalized):
        return normalized
    normalized["role"] = "user"
    normalized["is_admin"] = False
    normalized.pop("permissions", None)
    return normalized
