"""对话运行时个人偏好：嵌入应用 + 业务用户（session_owner）。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Mapping, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_chat_pref import UserChatRuntimePref
from app.schemas.ai_model import normalize_legacy_reasoning_effort
from app.services.ai.conversation_identity import try_session_user_id
from app.services.embed_identity import is_embed_session
from app.services.slash_command_service import resolve_slash_command_app_key


class ChatRuntimePrefPayload(BaseModel):
    override_model: Optional[str] = None
    thinking_enable: Optional[bool] = None
    reasoning_effort: Optional[str] = None
    temperature: Optional[float] = None
    persistable: bool = True
    embed_app_key: str = ""


class ChatRuntimePrefUpdate(BaseModel):
    override_model: Optional[str] = Field(default=None)
    thinking_enable: Optional[bool] = Field(default=None)
    reasoning_effort: Optional[str] = Field(default=None)
    temperature: Optional[float] = Field(default=None)


def resolve_chat_runtime_pref_scope(
    user_info: Optional[Mapping[str, Any]],
) -> Optional[tuple[str, str]]:
    """返回 (embed_app_key, owner_key)；无法稳定识别用户时返回 None。

    嵌入必须有 ``e:`` session_owner（应用+业务 subject 摘要），禁止退回签发人。
    站内会话 ``embed_app_key`` 为空串，``owner_key`` 为平台 user_id。
    """
    owner = try_session_user_id(user_info)
    if not owner:
        return None
    if is_embed_session(user_info):
        if not str(owner).startswith("e:"):
            return None
        app_key = resolve_slash_command_app_key(user_info)
        return (app_key, owner)
    return ("", owner)


def empty_pref_payload(*, persistable: bool, embed_app_key: str = "") -> ChatRuntimePrefPayload:
    return ChatRuntimePrefPayload(persistable=persistable, embed_app_key=embed_app_key)


def _sanitize_override_model(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:255]


def _sanitize_reasoning_effort(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    return normalize_legacy_reasoning_effort(value)


def _sanitize_temperature(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return max(0.0, min(2.0, round(number, 2)))


def _row_to_payload(row: UserChatRuntimePref) -> ChatRuntimePrefPayload:
    return ChatRuntimePrefPayload(
        override_model=row.override_model,
        thinking_enable=row.thinking_enable,
        reasoning_effort=row.reasoning_effort,
        temperature=row.temperature,
        persistable=True,
        embed_app_key=row.embed_app_key or "",
    )


async def get_chat_runtime_pref(
    session: AsyncSession,
    user_info: Optional[Mapping[str, Any]],
) -> ChatRuntimePrefPayload:
    scope = resolve_chat_runtime_pref_scope(user_info)
    if scope is None:
        return empty_pref_payload(persistable=False)
    app_key, owner_key = scope
    row = await session.scalar(
        select(UserChatRuntimePref).where(
            UserChatRuntimePref.embed_app_key == app_key,
            UserChatRuntimePref.owner_key == owner_key,
        )
    )
    if row is None:
        return empty_pref_payload(persistable=True, embed_app_key=app_key)
    return _row_to_payload(row)


async def upsert_chat_runtime_pref(
    session: AsyncSession,
    user_info: Optional[Mapping[str, Any]],
    update: ChatRuntimePrefUpdate,
) -> ChatRuntimePrefPayload:
    scope = resolve_chat_runtime_pref_scope(user_info)
    if scope is None:
        return empty_pref_payload(persistable=False)
    app_key, owner_key = scope
    row = await session.scalar(
        select(UserChatRuntimePref).where(
            UserChatRuntimePref.embed_app_key == app_key,
            UserChatRuntimePref.owner_key == owner_key,
        )
    )
    now = datetime.now()
    if row is None:
        row = UserChatRuntimePref(
            id=str(uuid.uuid4()),
            embed_app_key=app_key,
            owner_key=owner_key,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    data = update.model_dump(exclude_unset=True)
    if "override_model" in data:
        row.override_model = _sanitize_override_model(data["override_model"])
    if "thinking_enable" in data:
        value = data["thinking_enable"]
        row.thinking_enable = None if value is None else bool(value)
    if "reasoning_effort" in data:
        row.reasoning_effort = _sanitize_reasoning_effort(data["reasoning_effort"])
    if "temperature" in data:
        row.temperature = _sanitize_temperature(data["temperature"])
    row.updated_at = now
    await session.flush()
    await session.refresh(row)
    return _row_to_payload(row)
