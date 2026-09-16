import logging
from typing import Any, Dict, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import require_api_key, get_db_session
from app.services.embed_service import EmbedService
from app.schemas.response import StandardResponse

logger = logging.getLogger(__name__)

# 需要 API Key 鉴权的路由（供宿主系统后端在服务器内网调用）
router = APIRouter()

# 无需提前持有 API Key、凭 Ticket 自行兑换的路由（供前端 iframe 内部调用）
public_router = APIRouter()


class EmbedIdentityClaims(BaseModel):
    """宿主后端已认证的业务用户声明。只允许服务端 Ticket 传入，不能来自 iframe。"""

    subject: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="业务用户稳定唯一标识，建议 `业务系统:登录名`。",
        json_schema_extra={"example": "crm:zhangsan"},
    )
    display_name: Optional[str] = Field(
        None,
        max_length=50,
        description="展示名。",
        json_schema_extra={"example": "张三"},
    )
    dept_code: Optional[str] = Field(None, max_length=50, json_schema_extra={"example": "SH01"})
    org_path: Optional[str] = Field(
        None,
        max_length=255,
        json_schema_extra={"example": "yovole/sh/dc1"},
    )
    tenant_id: Optional[str] = Field(None, max_length=64, json_schema_extra={"example": "t_1001"})
    extra_data: Optional[Dict[str, Any]] = Field(
        None,
        description="写入 SQL 改写与 MCP custom_attributes 的业务属性。禁止传 role/is_admin/permissions。",
    )

    @field_validator("subject")
    @classmethod
    def _strip_subject(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("identity.subject 不能为空")
        return text


class CreateTicketRequest(BaseModel):
    username: Optional[str] = Field(
        None,
        description="目标南孜用户名（兼容旧代客模式）。与 identity 同时传入时以 identity 为准。",
        json_schema_extra={"example": "zhangsan"},
    )
    user_id: Optional[int] = Field(
        None,
        description="目标南孜用户ID。与 username 二选一；提供 identity 时忽略。",
        json_schema_extra={"example": 123},
    )
    identity: Optional[EmbedIdentityClaims] = Field(
        None,
        description="业务方用户身份。提交后按业务用户 JIT 影子账号并作为执行时数据权限来源。",
    )
    agent_id: Optional[str] = Field(
        None,
        description="锁定的智能体 ID。提交 identity 或 app_key 时必填；嵌入会话不能再切换入口智能体。",
        json_schema_extra={"example": "sys-agent-chatbi"},
    )
    app_key: Optional[str] = Field(
        None,
        max_length=64,
        description="嵌入应用标识。绑定后校验允许的智能体、域名、是否要求 identity、claims 白名单。",
        json_schema_extra={"example": "crm_portal"},
    )
    allowed_origins: Optional[List[str]] = Field(
        None,
        description="限定允许嵌入的宿主域名列表（防盗链）。如 ['https://crm.example.com']。",
        json_schema_extra={"example": ["https://crm.example.com"]},
    )
    expires_in: Optional[int] = Field(
        300,
        description="Ticket 兑换有效时长（秒），默认 300 秒（5分钟），最大 1800 秒。",
        json_schema_extra={"example": 300},
    )


class TicketResponseData(BaseModel):
    ticket: str = Field(..., description="一次性短时 Ticket 字符串")
    expires_in: int = Field(..., description="Ticket 有效时长（秒）")
    target_user: dict = Field(..., description="目标用户信息摘要")


class ExchangeTicketRequest(BaseModel):
    ticket: str = Field(..., description="一次性短时 Ticket 字符串", json_schema_extra={"example": "emt_..."})


class SessionTokenResponseData(BaseModel):
    session_token: str = Field(..., description="短期受限会话凭证（供后续对话 API 使用）")
    expires_in: int = Field(..., description="Session 有效期（秒），活跃调用会自动滑动延长")
    user_info: dict = Field(..., description="用户基本信息")
    agent_id: Optional[str] = Field(None, description="绑定的智能体 ID")


@router.post(
    "/tickets",
    response_model=StandardResponse[TicketResponseData],
    summary="签发嵌入式临时票据 (Embed Ticket)",
    description=(
        "通过宿主服务账号签发一次性短时 Ticket。"
        "推荐提交 identity（业务用户声明），执行权限以业务身份为准；长期 API Key 留在宿主后端。"
    ),
)
async def create_embed_ticket(
    payload: CreateTicketRequest,
    current_user: dict = Depends(require_api_key),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        data = await EmbedService.create_ticket(
            operator_user=current_user,
            target_username=payload.username,
            target_user_id=payload.user_id,
            agent_id=payload.agent_id,
            allowed_origins=payload.allowed_origins,
            expires_in=payload.expires_in or 300,
            db=db,
            identity=payload.identity.model_dump() if payload.identity else None,
            app_key=payload.app_key,
        )
        return StandardResponse(data=data)
    except ValueError as e:
        message = str(e)
        status_code = 400 if any(
            token in message
            for token in ("identity", "agent_id", "嵌入应用", "allowed_origins", "tenant_id", "claims")
        ) else 404
        raise HTTPException(status_code=status_code, detail=message)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error("Failed to create embed ticket: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create embed ticket")


@public_router.post(
    "/tickets/exchange",
    response_model=StandardResponse[SessionTokenResponseData],
    summary="兑换嵌入式临时会话 (Exchange Embed Ticket)",
    description=(
        "供前端 iframe 内部在加载时调用。传入一次性 Ticket，原子核销后换取短期 Session Token。"
        "Session Token 在持续对话中会自动滑动续期，闲置超时后自动作废。"
    ),
)
async def exchange_embed_ticket(
    request: Request,
    payload: ExchangeTicketRequest,
):
    origin = request.headers.get("Origin") or request.headers.get("Referer")
    try:
        data = await EmbedService.exchange_ticket(
            ticket=payload.ticket,
            origin=origin,
            sec_fetch_site=request.headers.get("Sec-Fetch-Site"),
        )
        return StandardResponse(data=data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        logger.warning("Embed ticket exchange forbidden: %s origin=%s", e, origin)
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error("Failed to exchange embed ticket: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to exchange embed ticket")


class RevokeEmbedSessionsRequest(BaseModel):
    app_key: str = Field(..., min_length=1, max_length=64)
    subject: str = Field(..., min_length=1, max_length=128)


@router.post(
    "/sessions/revoke",
    response_model=StandardResponse[dict],
    summary="按业务 subject 作废嵌入会话",
)
async def revoke_embed_sessions(
    payload: RevokeEmbedSessionsRequest,
    current_user: dict = Depends(require_api_key),
    db: AsyncSession = Depends(get_db_session),
):
    from app.services.embed_service import EmbedService as _Embed

    if not await _Embed._operator_can_impersonate(current_user, db):
        raise HTTPException(status_code=403, detail="无权作废嵌入会话")
    try:
        revoked = await EmbedService.revoke_sessions_by_subject(
            app_key=payload.app_key.strip(),
            subject=payload.subject.strip(),
        )
        return StandardResponse(data={"revoked": revoked})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
