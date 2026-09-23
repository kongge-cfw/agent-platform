import json
import logging
import secrets
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.models.user import User
from app.schemas.embed_app import parse_chat_settings, parse_examples, parse_shortcut_prompts
from app.services.embed_app_service import (
    dump_policy_session_fields,
    operator_has_embed_role,
    resolve_ticket_app_policy,
    _truthy,
)
from app.services.embed_identity import (
    EMBED_SESSION_TYPE,
    build_session_owner,
    build_shadow_extra_data,
    extra_data_json,
    is_shadow_remark,
    shadow_remark_for_operator,
    shadow_username,
)
from app.services.config_service import ConfigService
from app.utils.encryption import get_api_key_manager

logger = logging.getLogger(__name__)

TICKET_TTL_SECONDS = 300  # Ticket 一次性有效时长：5 分钟
SESSION_TOKEN_TTL_SECONDS = 86400  # Session Token 初始时长：24 小时 (滑动续期)


def _normalize_origin(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "null":
        return ""
    parsed = urlparse(text if "://" in text else f"https://{text}")
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return text.rstrip("/").lower()


def _is_embed_document_url(value: Optional[str]) -> bool:
    """iframe 文档地址：/embed 或 /zhiyuan/embed（Referer 带路径，Origin 通常不带）。"""
    text = str(value or "").strip()
    if not text or text.lower() == "null":
        return False
    parsed = urlparse(text if "://" in text else f"https://{text}")
    path = parsed.path or ""
    if not path:
        return False
    from app.core.app_prefix import configured_root_path, inferred_root_path, strip_root_from_path

    root = configured_root_path() or inferred_root_path(path)
    internal = strip_root_from_path(path, root) if root else path
    return internal == "/embed" or internal.startswith("/embed/")


def collect_platform_origins(request: Optional[Any] = None) -> set[str]:
    """平台自己的 Origin（无路径）。iframe 换票的 Origin 是它，不是宿主页。"""
    found: set[str] = set()

    def _add(value: Optional[str]) -> None:
        normalized = _normalize_origin(value)
        if normalized:
            found.add(normalized)

    try:
        from app.core.config import settings

        _add(str(getattr(settings, "APP_PUBLIC_URL", None) or ""))
    except Exception:
        pass
    try:
        from app.core.app_prefix import public_base_url

        _add(public_base_url())
    except Exception:
        pass
    if request is None:
        return found
    headers = request.headers
    proto = str(headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",", 1)[0].strip().lower()
    for host_value in (headers.get("x-forwarded-host"), headers.get("host"), request.url.netloc):
        host = str(host_value or "").split(",", 1)[0].strip()
        if proto and host:
            _add(f"{proto}://{host}")
    return found


def ticket_origin_allowed(
    origin: Optional[str],
    allowed_origins: list[str],
    sec_fetch_site: Optional[str] = None,
    *,
    referer: Optional[str] = None,
    platform_origins: Optional[set[str]] = None,
) -> bool:
    """兑换请求来自 iframe，Origin 是南孜站点；宿主域名白名单不能拿来卡同源换票。"""
    cleaned = [str(item).strip() for item in (allowed_origins or []) if str(item).strip()]
    if not cleaned or "*" in cleaned:
        return True
    site = str(sec_fetch_site or "").strip().lower()
    if site in {"same-origin", "same-site"}:
        return True
    if _is_embed_document_url(origin) or _is_embed_document_url(referer):
        return True
    incoming = _normalize_origin(origin) or _normalize_origin(referer)
    if not incoming:
        return True
    allowed_platform = {_normalize_origin(item) for item in (platform_origins or set()) if item}
    if incoming in allowed_platform:
        return True
    allowed = {_normalize_origin(item) for item in cleaned}
    return incoming in allowed


class EmbedService:
    """
    负责嵌入式组件 (EmbedChat) 的安全凭据生命周期管理：
    1. 签发短期一次性 Ticket (由宿主后端在内网发起，长期 API Key 不出内网)
    2. 兑换受限短期 Session Token (由前端 iframe 发起，一次性核销 Ticket)
    """

    @staticmethod
    async def _operator_can_impersonate(operator_user: Dict[str, Any], db: AsyncSession) -> bool:
        if str(operator_user.get("role") or "").strip().lower() == "admin":
            return True
        from app.services.permission_service import PermissionService

        perm_service = PermissionService(db)
        op_uid = int(operator_user.get("user_id", 0))
        return await perm_service.check_permission(
            op_uid,
            "api",
            "GET:/api/v1/users/profile",
        )

    @staticmethod
    async def _assert_operator_can_embed_agent(
        operator_user: Dict[str, Any],
        agent_id: str,
        db: AsyncSession,
    ) -> None:
        key = str(agent_id or "").strip()
        if not key:
            return
        from app.services.ai.agent_manager import AgentManagerService

        try:
            await AgentManagerService.resolve_embed_agent_access(db, key, operator_user)
        except LookupError as exc:
            raise ValueError("指定的智能体不存在或已禁用") from exc
        except PermissionError as exc:
            raise PermissionError("服务账号无权嵌入该智能体") from exc

    @staticmethod
    async def _upsert_shadow_user(
        db: AsyncSession,
        *,
        identity: Mapping[str, Any],
        operator_user_id: Any,
    ) -> User:
        subject = str(identity.get("subject") or "").strip()
        if not subject:
            raise ValueError("identity.subject 不能为空")

        username = shadow_username(subject)
        display_name = str(identity.get("display_name") or subject).strip() or subject
        dept_code = str(identity.get("dept_code") or "").strip()
        org_path = str(identity.get("org_path") or "").strip()
        extra_payload = build_shadow_extra_data(
            subject=subject,
            tenant_id=str(identity.get("tenant_id") or ""),
            extra_data=identity.get("extra_data"),
        )
        extra_json = extra_data_json(extra_payload)
        remark = shadow_remark_for_operator(operator_user_id)

        stmt = select(User).where(User.user_name == username)
        user = (await db.execute(stmt)).scalar_one_or_none()
        if user:
            if not is_shadow_remark(user.remark):
                raise ValueError("identity.subject 对应的用户名已被平台账号占用，请更换业务主体标识")
            user.real_name = display_name[:50]
            user.role = "user"
            user.dept_code = dept_code[:50] if dept_code else None
            user.org_path = org_path[:255] if org_path else None
            user.extra_data = extra_json
            user.remark = remark
            user.status = 1
            user.password_hash = None
            user.api_key_encrypted = None
            user.api_key_hash = None
            await db.commit()
            await db.refresh(user)
            return user

        user = User(
            user_name=username,
            real_name=display_name[:50],
            role="user",
            dept_code=dept_code[:50] if dept_code else None,
            org_path=org_path[:255] if org_path else None,
            extra_data=extra_json,
            remark=remark,
            status=1,
        )
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            user = (await db.execute(stmt)).scalar_one_or_none()
            if not user or not is_shadow_remark(user.remark):
                raise ValueError("identity.subject 对应的用户名已被占用")
            user.real_name = display_name[:50]
            user.role = "user"
            user.dept_code = dept_code[:50] if dept_code else None
            user.org_path = org_path[:255] if org_path else None
            user.extra_data = extra_json
            user.remark = remark
            user.status = 1
            await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    def _ticket_payload(
        *,
        ticket_id: str,
        user_id: Any,
        user_name: str,
        real_name: str,
        dept_code: str,
        org_path: str,
        extra_data: str,
        operator_user: Dict[str, Any],
        agent_id: str,
        allowed_origins: Optional[list[str]],
        identity: Optional[Mapping[str, Any]] = None,
        session_fields: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, Any]:
        subject = ""
        if identity:
            subject = str(identity.get("subject") or "").strip()
        app_key = str((session_fields or {}).get("embed_app_key") or "")
        session_owner = build_session_owner(
            app_key=app_key,
            subject=subject,
            fallback_user_id=user_id,
        )
        payload = {
            "ticket": ticket_id,
            "user_id": str(user_id),
            "user_name": user_name,
            "real_name": real_name or user_name,
            "role": "user",
            "dept_code": dept_code or "",
            "org_path": org_path or "",
            "extra_data": extra_data or "",
            "agent_id": agent_id or "",
            "allowed_origins": json.dumps(allowed_origins or []),
            "created_by_user_id": str(operator_user.get("user_id", "")),
            "created_by_user_name": str(operator_user.get("user_name") or ""),
            "created_by_role": str(operator_user.get("role") or "user"),
            "external_subject": subject,
            "identity_mode": "claims" if identity else "mapped_user",
            "session_owner": session_owner,
            "tenant_id": str((identity or {}).get("tenant_id") or ""),
        }
        payload.update(dict(session_fields or {}))
        return payload

    @staticmethod
    async def create_ticket(
        operator_user: Dict[str, Any],
        target_username: Optional[str] = None,
        target_user_id: Optional[int] = None,
        agent_id: Optional[str] = None,
        allowed_origins: Optional[list[str]] = None,
        expires_in: int = TICKET_TTL_SECONDS,
        db: Optional[AsyncSession] = None,
        identity: Optional[Mapping[str, Any]] = None,
        app_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        为指定目标用户签发一次性短时 Ticket。
        - identity：业务方登录用户声明。不要求该用户事先存在于南孜；默认 JIT 影子账号。
        - 若未提供 identity 且未提供 target_username/target_user_id，默认代表当前调用者自己。
        - 无 identity 时目标用户必须存在且为启用状态 (status == 1)。
        - app_key：绑定嵌入应用（角色授权、入口锁定、域名、claims 白名单、是否要求 identity）。
        """
        if db is None:
            raise RuntimeError("Database session is required")

        redis = await get_redis()
        if not redis:
            raise RuntimeError("Redis service unavailable")

        policy = await resolve_ticket_app_policy(
            db,
            app_key=app_key,
            identity=identity,
            agent_id=agent_id,
            allowed_origins=allowed_origins,
        )
        agent_key = str(policy.get("agent_id") or agent_id or "").strip()
        allowed_origins = list(policy.get("allowed_origins") or allowed_origins or [])
        identity_payload = dict(policy["identity"]) if policy.get("identity") else (
            dict(identity) if identity else None
        )
        create_shadow = bool(policy.get("create_shadow_user"))
        session_fields = dump_policy_session_fields(policy)
        role_id = policy.get("role_id")
        if role_id and not await operator_has_embed_role(db, operator_user, int(role_id)):
            raise PermissionError("服务账号未绑定该嵌入应用关联的角色")
        if identity_payload is not None:
            if not str(identity_payload.get("subject") or "").strip():
                raise ValueError("identity.subject 不能为空")
            if not agent_key:
                if policy.get("lock_entry_agent") or not policy.get("app"):
                    raise ValueError(
                        "该嵌入应用已锁定入口智能体，必须指定 agent_id"
                        if policy.get("app")
                        else "使用业务身份签发嵌入凭证时必须指定 agent_id"
                    )
            if not await EmbedService._operator_can_impersonate(operator_user, db):
                raise PermissionError(
                    "无权以业务用户身份签发 Ticket：仅管理员或具备「GET:/api/v1/users/profile（获取用户画像）」权限的服务账号允许提交 identity。"
                )
            await EmbedService._assert_operator_can_embed_agent(operator_user, agent_key, db)
            extra_payload = build_shadow_extra_data(
                subject=str(identity_payload.get("subject") or "").strip(),
                tenant_id=str(identity_payload.get("tenant_id") or ""),
                extra_data=identity_payload.get("extra_data"),
            )
            if create_shadow:
                target_user = await EmbedService._upsert_shadow_user(
                    db,
                    identity=identity_payload,
                    operator_user_id=operator_user.get("user_id"),
                )
                ticket_user_id = target_user.id
                ticket_user_name = target_user.user_name
                ticket_real_name = target_user.real_name or target_user.user_name
                ticket_dept = target_user.dept_code or ""
                ticket_org = target_user.org_path or ""
                ticket_extra = target_user.extra_data or extra_data_json(extra_payload)
            else:
                ticket_user_id = operator_user.get("user_id")
                ticket_user_name = shadow_username(str(identity_payload.get("subject") or ""))
                ticket_real_name = str(identity_payload.get("display_name") or ticket_user_name)
                ticket_dept = str(identity_payload.get("dept_code") or "")
                ticket_org = str(identity_payload.get("org_path") or "")
                ticket_extra = extra_data_json(extra_payload)
        else:
            target_user = None
            is_specifying_other = False

            if target_user_id is not None:
                if str(target_user_id) != str(operator_user.get("user_id")):
                    is_specifying_other = True
                stmt = select(User).where(User.id == int(target_user_id))
                result = await db.execute(stmt)
                target_user = result.scalar_one_or_none()
            elif target_username:
                if str(target_username).strip() != str(operator_user.get("user_name")):
                    is_specifying_other = True
                stmt = select(User).where(User.user_name == str(target_username).strip())
                result = await db.execute(stmt)
                target_user = result.scalar_one_or_none()
            else:
                op_uid = int(operator_user.get("user_id", 0))
                stmt = select(User).where(User.id == op_uid)
                result = await db.execute(stmt)
                target_user = result.scalar_one_or_none()

            if not target_user:
                raise ValueError("目标用户不存在，请核对用户名或用户ID")

            if target_user.status != 1:
                raise PermissionError("目标用户账号已被禁用，无法签发嵌入凭证")

            if is_specifying_other and not await EmbedService._operator_can_impersonate(operator_user, db):
                raise PermissionError(
                    "无权代他人签发 Ticket：仅管理员或具备「GET:/api/v1/users/profile（获取用户画像）」权限的账号允许代表其他用户签发凭证。普通用户请留空或填写自己。"
                )
            ticket_user_id = target_user.id
            ticket_user_name = target_user.user_name
            ticket_real_name = target_user.real_name or target_user.user_name
            ticket_dept = target_user.dept_code or ""
            ticket_org = target_user.org_path or ""
            ticket_extra = target_user.extra_data or ""
            if agent_key:
                await EmbedService._assert_operator_can_embed_agent(operator_user, agent_key, db)

        ticket_id = f"emt_{secrets.token_urlsafe(24)}"
        ticket_key = f"embed:ticket:{ticket_id}"
        ttl = max(60, min(expires_in, 1800))

        ticket_payload = EmbedService._ticket_payload(
            ticket_id=ticket_id,
            user_id=ticket_user_id,
            user_name=ticket_user_name,
            real_name=ticket_real_name,
            dept_code=ticket_dept,
            org_path=ticket_org,
            extra_data=ticket_extra,
            operator_user=operator_user,
            agent_id=agent_key,
            allowed_origins=allowed_origins,
            identity=identity_payload,
            session_fields=session_fields,
        )
        await redis.set(ticket_key, json.dumps(ticket_payload, ensure_ascii=False), ex=ttl)
        logger.info(
            "Embed ticket created: ticket=%s target_user=%s operator=%s identity=%s app=%s ttl=%ds",
            ticket_id,
            ticket_user_name,
            operator_user.get("user_name"),
            bool(identity_payload),
            session_fields.get("embed_app_key") or "-",
            ttl,
        )

        target_summary = {
            "user_id": ticket_user_id,
            "user_name": ticket_user_name,
            "real_name": ticket_real_name,
            "session_owner": ticket_payload.get("session_owner"),
        }
        if identity_payload:
            target_summary["subject"] = str(identity_payload.get("subject") or "").strip()
        if session_fields.get("embed_app_key"):
            target_summary["app_key"] = session_fields["embed_app_key"]
        return {
            "ticket": ticket_id,
            "expires_in": ttl,
            "target_user": target_summary,
        }

    @staticmethod
    async def exchange_ticket(
        ticket: str,
        origin: Optional[str] = None,
        sec_fetch_site: Optional[str] = None,
        *,
        referer: Optional[str] = None,
        platform_origins: Optional[set[str]] = None,
    ) -> Dict[str, Any]:
        """
        原子核销 Ticket 并生成短期会话 Token (session_token)。
        - 只能成功核销一次 (One-Time Use)；
        - 核销后立即从 Redis 移除 Ticket，杜绝重放攻击；
        - 生成的 session_token 写入 auth 鉴权缓存，天然与现存所有 API Key 鉴权体系无缝兼容。
        """
        if not ticket or not isinstance(ticket, str) or not ticket.startswith("emt_"):
            raise ValueError("Invalid ticket format")

        redis = await get_redis()
        if not redis:
            raise RuntimeError("Redis service unavailable")

        ticket_key = f"embed:ticket:{ticket.strip()}"
        raw_ticket_data = await redis.get(ticket_key)
        if not raw_ticket_data:
            raise ValueError("Ticket not found, expired, or already used")

        if isinstance(raw_ticket_data, bytes):
            raw_ticket_data = raw_ticket_data.decode("utf-8")

        ticket_data = json.loads(raw_ticket_data)

        allowed_origins_raw = ticket_data.get("allowed_origins")
        allowed_origins: list[str] = []
        if allowed_origins_raw:
            try:
                parsed_origins = json.loads(allowed_origins_raw) if isinstance(allowed_origins_raw, str) else allowed_origins_raw
                if isinstance(parsed_origins, list):
                    allowed_origins = [str(item).strip() for item in parsed_origins if str(item).strip()]
            except json.JSONDecodeError:
                allowed_origins = []
        if not ticket_origin_allowed(
            origin,
            allowed_origins,
            sec_fetch_site=sec_fetch_site,
            referer=referer,
            platform_origins=platform_origins,
        ):
            logger.warning(
                "Embed ticket origin rejected: origin=%s referer=%s sec_fetch_site=%s allowed=%s",
                origin,
                referer,
                sec_fetch_site,
                allowed_origins,
            )
            raise PermissionError(f"Origin '{origin}' is not allowed for this ticket")
        removed = await redis.delete(ticket_key)
        if not removed:
            raise ValueError("Ticket not found, expired, or already used")

        session_token = f"emb_ses_{secrets.token_urlsafe(32)}"
        manager = get_api_key_manager()
        hashed_token = manager.hash_api_key(session_token)
        cache_key = f"auth:api_key:{hashed_token}"

        user_session_data = {
            "user_id": str(ticket_data["user_id"]),
            "user_name": ticket_data["user_name"],
            "real_name": ticket_data.get("real_name") or ticket_data["user_name"],
            "role": "user",
            "dept_code": ticket_data.get("dept_code", ""),
            "org_path": ticket_data.get("org_path", ""),
            "extra_data": ticket_data.get("extra_data", ""),
            "remark": ticket_data.get("remark") or "Embed Session",
            "status": "1",
            "session_type": EMBED_SESSION_TYPE,
            "agent_id": ticket_data.get("agent_id", ""),
            "created_by_user_id": ticket_data.get("created_by_user_id", ""),
            "created_by_user_name": ticket_data.get("created_by_user_name", ""),
            "created_by_role": ticket_data.get("created_by_role", ""),
            "external_subject": ticket_data.get("external_subject", ""),
            "identity_mode": ticket_data.get("identity_mode", ""),
            "session_owner": ticket_data.get("session_owner", ""),
            "tenant_id": ticket_data.get("tenant_id", ""),
            "embed_app_id": ticket_data.get("embed_app_id", ""),
            "embed_app_key": ticket_data.get("embed_app_key", ""),
            "create_shadow_user": ticket_data.get("create_shadow_user", "1"),
            "data_permission_mode": ticket_data.get("data_permission_mode", "nanzi_sql_rewrite"),
            "isolate_datasets_by_tenant": ticket_data.get("isolate_datasets_by_tenant", "0"),
            "embed_role_id": ticket_data.get("embed_role_id", ""),
            "lock_entry_agent": ticket_data.get("lock_entry_agent", ""),
            "default_entry_agent_id": ticket_data.get("default_entry_agent_id", ""),
            "shortcut_prompts": ticket_data.get("shortcut_prompts") or "[]",
            "examples": ticket_data.get("examples") or "[]",
            "chat_settings": ticket_data.get("chat_settings") or "{}",
        }
        await redis.hset(cache_key, mapping=user_session_data)
        await redis.expire(cache_key, SESSION_TOKEN_TTL_SECONDS)
        session_owner = str(ticket_data.get("session_owner") or "").strip()
        if session_owner:
            index_key = f"embed:owner_sessions:{session_owner}"
            await redis.sadd(index_key, hashed_token)
            await redis.expire(index_key, SESSION_TOKEN_TTL_SECONDS)

        logger.info(
            "Embed ticket exchanged successfully: ticket=%s user=%s session_token_prefix=%s ttl=%ds",
            ticket,
            ticket_data["user_name"],
            session_token[:12],
            SESSION_TOKEN_TTL_SECONDS,
        )

        user_info = {
            "user_id": int(ticket_data["user_id"]),
            "user_name": ticket_data["user_name"],
            "real_name": ticket_data.get("real_name") or ticket_data["user_name"],
            "role": "user",
            "session_owner": ticket_data.get("session_owner") or None,
            "app_key": ticket_data.get("embed_app_key") or None,
            "shortcut_prompts": parse_shortcut_prompts(ticket_data.get("shortcut_prompts")),
            "examples": parse_examples(ticket_data.get("examples")),
            "chat_settings": parse_chat_settings(ticket_data.get("chat_settings")) if ticket_data.get("embed_app_key") else None,
            "default_entry_agent_id": str(ticket_data.get("default_entry_agent_id") or "").strip() or None,
            "watermark": {
                "enabled": await ConfigService.get("embedchat_watermark_enabled") == "true",
                "style": await ConfigService.get("embedchat_watermark_style") or "user_time",
                "text": await ConfigService.get("embedchat_watermark_text") or "南孜系统",
            },
        }
        subject = str(ticket_data.get("external_subject") or "").strip()
        if subject:
            user_info["subject"] = subject
        lock_flag = ticket_data.get("lock_entry_agent")
        lock_entry = _truthy(lock_flag) if lock_flag not in (None, "") else bool(ticket_data.get("agent_id"))
        return {
            "session_token": session_token,
            "expires_in": SESSION_TOKEN_TTL_SECONDS,
            "user_info": user_info,
            "agent_id": (ticket_data.get("agent_id") or None) if lock_entry else None,
            "lock_entry_agent": lock_entry,
            "default_entry_agent_id": str(ticket_data.get("default_entry_agent_id") or "").strip() or None,
            "shortcut_prompts": user_info.get("shortcut_prompts") or [],
            "examples": user_info.get("examples") or [],
        }

    @staticmethod
    async def revoke_sessions_by_subject(*, app_key: str, subject: str) -> int:
        """按嵌入应用 + 业务 subject 作废已兑换的 session。"""
        owner = build_session_owner(app_key=app_key, subject=subject, fallback_user_id="")
        if not owner.startswith("e:"):
            raise ValueError("subject 不能为空")
        redis = await get_redis()
        if not redis:
            raise RuntimeError("Redis service unavailable")
        index_key = f"embed:owner_sessions:{owner}"
        hashed_tokens = await redis.smembers(index_key)
        revoked = 0
        for hashed in hashed_tokens or []:
            token_hash = hashed.decode("utf-8") if isinstance(hashed, bytes) else str(hashed)
            deleted = await redis.delete(f"auth:api_key:{token_hash}")
            revoked += int(deleted or 0)
        await redis.delete(index_key)
        logger.info(
            "Embed sessions revoked: app=%s subject=%s count=%s",
            app_key,
            subject,
            revoked,
        )
        return revoked
