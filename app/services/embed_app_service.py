"""嵌入应用策略：Ticket 绑定、claims 白名单、智能体/域名约束。"""

from __future__ import annotations

import secrets
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embed_app import SysEmbedApp
from app.schemas.embed_app import parse_json_list

DATA_PERMISSION_SQL_REWRITE = "nanzi_sql_rewrite"
DATA_PERMISSION_MCP_ONLY = "mcp_only"


def generate_embed_app_key() -> str:
    """生成符合 app_key 规则的随机标识，如 app_a8f9c2d1e0b34567。"""
    return f"app_{secrets.token_hex(8)}"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def parse_embed_app_row(app: SysEmbedApp) -> dict[str, Any]:
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "allowed_agent_ids": [str(item).strip() for item in parse_json_list(app.allowed_agent_ids)],
        "allowed_origins": [str(item).strip() for item in parse_json_list(app.allowed_origins)],
        "require_identity": bool(app.require_identity),
        "claim_keys": [str(item).strip() for item in parse_json_list(app.claim_keys)],
        "create_shadow_user": bool(app.create_shadow_user),
        "data_permission_mode": str(app.data_permission_mode or DATA_PERMISSION_SQL_REWRITE).strip()
        or DATA_PERMISSION_SQL_REWRITE,
        "isolate_datasets_by_tenant": bool(app.isolate_datasets_by_tenant),
        "is_active": bool(app.is_active),
    }


async def get_embed_app_by_key(db: AsyncSession, app_key: str) -> Optional[SysEmbedApp]:
    key = str(app_key or "").strip()
    if not key:
        return None
    stmt = select(SysEmbedApp).where(SysEmbedApp.app_key == key)
    return (await db.execute(stmt)).scalar_one_or_none()


def apply_claim_whitelist(
    identity: Mapping[str, Any],
    claim_keys: list[str] | None,
) -> dict[str, Any]:
    """按应用白名单裁剪 identity；subject 始终保留。"""
    from app.services.embed_identity import sanitize_identity_extra_data

    payload = dict(identity or {})
    subject = str(payload.get("subject") or "").strip()
    if not subject:
        raise ValueError("identity.subject 不能为空")

    extra = sanitize_identity_extra_data(payload.get("extra_data"))
    allowed = [str(item).strip() for item in (claim_keys or []) if str(item).strip()]
    if not allowed:
        out = {
            "subject": subject,
            "display_name": str(payload.get("display_name") or "").strip() or subject,
            "dept_code": str(payload.get("dept_code") or "").strip(),
            "org_path": str(payload.get("org_path") or "").strip(),
            "tenant_id": str(payload.get("tenant_id") or "").strip(),
            "extra_data": extra,
        }
        return out

    allowed_set = set(allowed)
    extra_keys = [key[len("extra_data.") :] for key in allowed if key.startswith("extra_data.") and key != "extra_data"]
    allow_all_extra = "extra_data" in allowed_set
    if extra_keys and not allow_all_extra:
        extra = {key: extra[key] for key in extra_keys if key in extra}

    out = {"subject": subject}
    for field in ("display_name", "dept_code", "org_path", "tenant_id"):
        if field in allowed_set:
            out[field] = str(payload.get(field) or "").strip()
    if "display_name" not in out:
        out["display_name"] = str(payload.get("display_name") or "").strip() or subject
    if allow_all_extra or extra_keys:
        out["extra_data"] = extra
    else:
        out["extra_data"] = {}
    if "tenant_id" not in out:
        out["tenant_id"] = ""
    return out


def intersect_origins(app_origins: list[str], ticket_origins: Optional[list[str]]) -> list[str]:
    app_set = [item for item in (app_origins or []) if item]
    requested = [str(item).strip() for item in (ticket_origins or []) if str(item).strip()]
    if not app_set:
        return requested
    if "*" in app_set:
        return requested or app_set
    if not requested:
        return app_set
    allowed = {item.rstrip("/") for item in app_set}
    filtered = [item for item in requested if item in app_set or item.rstrip("/") in allowed or "*" in app_set]
    if not filtered:
        raise ValueError("Ticket allowed_origins 不在嵌入应用允许的域名列表内")
    extras = [item for item in requested if item not in filtered]
    if extras:
        raise ValueError("Ticket allowed_origins 超出嵌入应用域名白名单")
    return filtered


def agent_allowed_by_app(agent_id: str, allowed_agent_ids: list[str]) -> bool:
    key = str(agent_id or "").strip()
    if not key:
        return not allowed_agent_ids
    if not allowed_agent_ids:
        return True
    allowed = {str(item).strip() for item in allowed_agent_ids if str(item).strip()}
    return key in allowed


async def resolve_ticket_app_policy(
    db: AsyncSession,
    *,
    app_key: Optional[str],
    identity: Optional[Mapping[str, Any]],
    agent_id: Optional[str],
    allowed_origins: Optional[list[str]],
) -> dict[str, Any]:
    """解析 Ticket 对应的嵌入应用策略。未传 app_key 时走一期兼容（无应用约束）。"""
    key = str(app_key or "").strip()
    if not key:
        return {
            "app": None,
            "identity": dict(identity) if identity else None,
            "agent_id": str(agent_id or "").strip(),
            "allowed_origins": list(allowed_origins or []),
            "create_shadow_user": True,
            "data_permission_mode": DATA_PERMISSION_SQL_REWRITE,
            "isolate_datasets_by_tenant": False,
        }

    app = await get_embed_app_by_key(db, key)
    if not app:
        raise ValueError(f"嵌入应用不存在: {key}")
    if not app.is_active:
        raise ValueError(f"嵌入应用已停用: {key}")

    policy = parse_embed_app_row(app)
    agent_key = str(agent_id or "").strip()
    if policy["require_identity"] and not identity:
        raise ValueError("该嵌入应用要求提交 identity（业务用户 claims）")
    if identity is None and policy["require_identity"]:
        raise ValueError("该嵌入应用要求提交 identity（业务用户 claims）")
    if not agent_key:
        raise ValueError("使用嵌入应用签发 Ticket 时必须指定 agent_id")
    if not agent_allowed_by_app(agent_key, policy["allowed_agent_ids"]):
        raise ValueError("该智能体不在嵌入应用允许列表中")

    normalized_identity = None
    if identity:
        normalized_identity = apply_claim_whitelist(identity, policy["claim_keys"])
        if policy["isolate_datasets_by_tenant"] and not str(normalized_identity.get("tenant_id") or "").strip():
            raise ValueError("该嵌入应用已开启租户隔离，identity.tenant_id 不能为空")

    origins = intersect_origins(policy["allowed_origins"], allowed_origins)
    return {
        "app": policy,
        "identity": normalized_identity,
        "agent_id": agent_key,
        "allowed_origins": origins,
        "create_shadow_user": policy["create_shadow_user"],
        "data_permission_mode": policy["data_permission_mode"],
        "isolate_datasets_by_tenant": policy["isolate_datasets_by_tenant"],
    }


def dump_policy_session_fields(policy: Mapping[str, Any]) -> dict[str, str]:
    app = policy.get("app") or {}
    return {
        "embed_app_id": str(app.get("id") or ""),
        "embed_app_key": str(app.get("app_key") or ""),
        "create_shadow_user": "1" if policy.get("create_shadow_user", True) else "0",
        "data_permission_mode": str(policy.get("data_permission_mode") or DATA_PERMISSION_SQL_REWRITE),
        "isolate_datasets_by_tenant": "1" if policy.get("isolate_datasets_by_tenant") else "0",
    }


def policy_from_user_info(user_info: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(user_info, Mapping):
        return {
            "create_shadow_user": True,
            "data_permission_mode": DATA_PERMISSION_SQL_REWRITE,
            "isolate_datasets_by_tenant": False,
            "embed_app_id": "",
            "embed_app_key": "",
        }
    return {
        "create_shadow_user": _truthy(user_info.get("create_shadow_user", True)),
        "data_permission_mode": str(
            user_info.get("data_permission_mode") or DATA_PERMISSION_SQL_REWRITE
        ).strip()
        or DATA_PERMISSION_SQL_REWRITE,
        "isolate_datasets_by_tenant": _truthy(user_info.get("isolate_datasets_by_tenant")),
        "embed_app_id": str(user_info.get("embed_app_id") or "").strip(),
        "embed_app_key": str(user_info.get("embed_app_key") or "").strip(),
    }
