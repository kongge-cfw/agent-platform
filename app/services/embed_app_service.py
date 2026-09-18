"""嵌入应用策略：Ticket 绑定、claims 白名单、角色授权与入口锁定。"""

from __future__ import annotations

import secrets
from typing import Any, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.embed_app import SysEmbedApp
from app.models.permission import Role, UserRoleRelation
from app.schemas.embed_app import parse_json_list, parse_shortcut_prompts, dump_shortcut_prompts

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
    role_id = app.role_id
    try:
        parsed_role_id = int(role_id) if role_id not in (None, "") else None
    except (TypeError, ValueError):
        parsed_role_id = None
    if parsed_role_id is not None and parsed_role_id <= 0:
        parsed_role_id = None
    return {
        "id": app.id,
        "app_key": app.app_key,
        "name": app.name,
        "role_id": parsed_role_id,
        "lock_entry_agent": bool(app.lock_entry_agent),
        "default_entry_agent_id": str(app.default_entry_agent_id or "").strip() or None,
        "allowed_origins": [str(item).strip() for item in parse_json_list(app.allowed_origins)],
        "require_identity": bool(app.require_identity),
        "claim_keys": [str(item).strip() for item in parse_json_list(app.claim_keys)],
        "data_permission_mode": str(app.data_permission_mode or DATA_PERMISSION_SQL_REWRITE).strip()
        or DATA_PERMISSION_SQL_REWRITE,
        "shortcut_prompts": parse_shortcut_prompts(app.shortcut_prompts),
        "is_active": bool(app.is_active),
    }


async def get_embed_app_by_key(db: AsyncSession, app_key: str) -> Optional[SysEmbedApp]:
    key = str(app_key or "").strip()
    if not key:
        return None
    stmt = select(SysEmbedApp).where(SysEmbedApp.app_key == key)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_role_agent_ids(db: AsyncSession, role_id: int) -> set[str]:
    from app.services.permission_service import PermissionService

    perms = await PermissionService(db).get_role_permissions(int(role_id))
    return {str(item).strip() for item in (perms.permissions.agents or []) if str(item).strip()}


async def agent_allowed_by_role(db: AsyncSession, role_id: int, agent_key: str) -> bool:
    key = str(agent_key or "").strip()
    if not key:
        return True
    allowed = await get_role_agent_ids(db, role_id)
    if not allowed:
        return False
    if key in allowed:
        return True
    from app.models.agent import AIAgent

    stmt = select(AIAgent).where(AIAgent.id == key)
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if agent is None:
        stmt = select(AIAgent).where(AIAgent.name == key)
        agent = (await db.execute(stmt)).scalar_one_or_none()
    if agent is None:
        return False
    return str(agent.id or "").strip() in allowed or str(agent.name or "").strip() in allowed


async def list_role_agent_options(db: AsyncSession, role_id: int) -> list[dict[str, Any]]:
    from app.models.agent import AIAgent
    from app.services.ai.agent_manager import MAIN_GENERAL_AGENT_ID, MAIN_GENERAL_AGENT_NAMES
    from sqlalchemy import case, or_

    allowed = await get_role_agent_ids(db, int(role_id))
    if not allowed:
        return []
    keys = {str(item).strip() for item in allowed if str(item).strip()}
    main_first = case(
        (or_(AIAgent.id == MAIN_GENERAL_AGENT_ID, AIAgent.name.in_(tuple(MAIN_GENERAL_AGENT_NAMES))), 0),
        else_=1,
    )
    stmt = (
        select(AIAgent)
        .where(
            AIAgent.is_enabled == True,
            or_(AIAgent.id.in_(keys), AIAgent.name.in_(keys)),
        )
        .order_by(main_first, AIAgent.sort_order.desc(), AIAgent.display_name)
    )
    agents = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(agent.id or "").strip(),
            "name": str(agent.name or "").strip(),
            "display_name": str(agent.display_name or agent.name or agent.id or "").strip(),
            "is_system": bool(agent.is_system),
        }
        for agent in agents
        if str(getattr(agent, "id", "") or "").strip()
    ]


async def ensure_default_entry_allowed(
    db: AsyncSession,
    *,
    role_id: Optional[int],
    agent_id: Optional[str],
) -> None:
    key = str(agent_id or "").strip()
    if not key:
        return
    if role_id is None:
        raise ValueError("必须先关联角色，才能指定默认入口智能体")
    if not await agent_allowed_by_role(db, int(role_id), key):
        raise ValueError("默认入口智能体不在关联角色的授权范围内")


async def operator_has_embed_role(
    db: AsyncSession,
    operator_user: Mapping[str, Any],
    role_id: int,
) -> bool:
    if str(operator_user.get("role") or "").strip().lower() == "admin":
        return True
    try:
        uid = int(operator_user.get("user_id") or 0)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    stmt = select(UserRoleRelation.id).where(
        UserRoleRelation.user_id == uid,
        UserRoleRelation.role_id == int(role_id),
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def ensure_embed_role_exists(db: AsyncSession, role_id: Optional[int]) -> None:
    if role_id is None:
        raise ValueError("必须关联角色")
    role = await db.get(Role, int(role_id))
    if role is None:
        raise ValueError("关联角色不存在")


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
            "shortcut_prompts": [],
            "role_id": None,
            "lock_entry_agent": False,
            "default_entry_agent_id": None,
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
    default_entry = str(policy.get("default_entry_agent_id") or "").strip()
    if policy["lock_entry_agent"] and not agent_key and default_entry:
        agent_key = default_entry
    if policy["lock_entry_agent"] and not agent_key:
        raise ValueError("该嵌入应用已锁定入口智能体，必须指定 agent_id")
    role_id = policy.get("role_id")
    if not role_id:
        raise ValueError("嵌入应用未关联角色，请在管理端绑定角色后再签发")
    if agent_key and not await agent_allowed_by_role(db, int(role_id), agent_key):
        raise ValueError("该智能体不在嵌入应用关联角色的授权范围内")

    normalized_identity = None
    if identity:
        normalized_identity = apply_claim_whitelist(identity, policy["claim_keys"])

    origins = intersect_origins(policy["allowed_origins"], allowed_origins)
    return {
        "app": policy,
        "identity": normalized_identity,
        "agent_id": agent_key,
        "allowed_origins": origins,
        "create_shadow_user": False,
        "data_permission_mode": policy["data_permission_mode"],
        "shortcut_prompts": list(policy.get("shortcut_prompts") or []),
        "role_id": role_id,
        "lock_entry_agent": bool(policy["lock_entry_agent"]),
        "default_entry_agent_id": default_entry or None,
    }


def dump_policy_session_fields(policy: Mapping[str, Any]) -> dict[str, str]:
    app = policy.get("app") or {}
    fields = {
        "embed_app_id": str(app.get("id") or ""),
        "embed_app_key": str(app.get("app_key") or ""),
        "create_shadow_user": "1" if policy.get("create_shadow_user") else "0",
        "data_permission_mode": str(policy.get("data_permission_mode") or DATA_PERMISSION_SQL_REWRITE),
        "shortcut_prompts": dump_shortcut_prompts(app.get("shortcut_prompts") or policy.get("shortcut_prompts") or []),
    }
    if app:
        role_id = policy.get("role_id") if policy.get("role_id") is not None else app.get("role_id")
        lock_entry = policy.get("lock_entry_agent")
        if lock_entry is None:
            lock_entry = bool(app.get("lock_entry_agent"))
        fields["embed_role_id"] = str(role_id or "")
        fields["lock_entry_agent"] = "1" if lock_entry else "0"
        fields["default_entry_agent_id"] = str(
            policy.get("default_entry_agent_id") or app.get("default_entry_agent_id") or ""
        )
    return fields


def policy_from_user_info(user_info: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(user_info, Mapping):
        return {
            "create_shadow_user": False,
            "data_permission_mode": DATA_PERMISSION_SQL_REWRITE,
            "isolate_datasets_by_tenant": False,
            "embed_app_id": "",
            "embed_app_key": "",
            "embed_role_id": "",
            "lock_entry_agent": False,
            "default_entry_agent_id": "",
        }
    return {
        "create_shadow_user": _truthy(user_info.get("create_shadow_user")),
        "data_permission_mode": str(
            user_info.get("data_permission_mode") or DATA_PERMISSION_SQL_REWRITE
        ).strip()
        or DATA_PERMISSION_SQL_REWRITE,
        "isolate_datasets_by_tenant": _truthy(user_info.get("isolate_datasets_by_tenant")),
        "embed_app_id": str(user_info.get("embed_app_id") or "").strip(),
        "embed_app_key": str(user_info.get("embed_app_key") or "").strip(),
        "embed_role_id": str(user_info.get("embed_role_id") or "").strip(),
        "lock_entry_agent": _truthy(user_info.get("lock_entry_agent")),
        "default_entry_agent_id": str(user_info.get("default_entry_agent_id") or "").strip(),
    }
