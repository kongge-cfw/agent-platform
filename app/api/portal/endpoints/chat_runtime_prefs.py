from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_api_key
from app.core.orm import get_db_session
from app.services.chat_runtime_pref_service import (
    ChatRuntimePrefUpdate,
    get_chat_runtime_pref,
    upsert_chat_runtime_pref,
)

router = APIRouter()


@router.get("", summary="读取当前用户的对话运行时偏好")
async def get_runtime_prefs(
    user_info: Dict[str, Any] = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    payload = await get_chat_runtime_pref(session, user_info)
    return {"code": 0, "data": payload.model_dump()}


@router.put("", summary="保存当前用户的对话运行时偏好")
async def put_runtime_prefs(
    body: ChatRuntimePrefUpdate,
    user_info: Dict[str, Any] = Depends(require_api_key),
    session: AsyncSession = Depends(get_db_session),
):
    payload = await upsert_chat_runtime_pref(session, user_info, body)
    return {"code": 0, "data": payload.model_dump(), "message": "偏好已保存"}
