from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.core.orm import get_db_session
from app.models.ui_card import SysUiCard
from app.schemas.ui_card import SysUiCardCreate, SysUiCardResponse, SysUiCardUpdate

router = APIRouter()
public_router = APIRouter()


def _dump_lists(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    for key in ("allowed_origins", "allowed_actions", "allowed_agent_ids"):
        if key in payload and payload[key] is not None:
            payload[key] = json.dumps(payload[key], ensure_ascii=False)
    return payload


def _actor_id(user: Dict[str, Any]) -> str:
    return str(user.get("user_id") or user.get("id") or "")


@router.get("", response_model=List[SysUiCardResponse])
async def list_ui_cards(
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("menu", "menu:ui_cards")),
):
    result = await db.execute(select(SysUiCard).order_by(SysUiCard.updated_at.desc()))
    return result.scalars().all()


@router.post("", response_model=SysUiCardResponse)
async def create_ui_card(
    card_in: SysUiCardCreate,
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("element", "element:ui_cards:create")),
):
    existing = await db.execute(select(SysUiCard).where(SysUiCard.card_key == card_in.card_key))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="card_key 已存在")
    data = _dump_lists(card_in.model_dump())
    card = SysUiCard(id=str(uuid.uuid4()), created_by=_actor_id(user), updated_by=_actor_id(user), **data)
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


@router.put("/{card_id}", response_model=SysUiCardResponse)
async def update_ui_card(
    card_id: str,
    card_in: SysUiCardUpdate,
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("element", "element:ui_cards:edit")),
):
    result = await db.execute(select(SysUiCard).where(SysUiCard.id == card_id))
    card = result.scalars().first()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    update_data = _dump_lists(card_in.model_dump(exclude_unset=True))
    if "card_key" in update_data and update_data["card_key"] != card.card_key:
        dup = await db.execute(select(SysUiCard).where(SysUiCard.card_key == update_data["card_key"]))
        if dup.scalars().first():
            raise HTTPException(status_code=400, detail="card_key 已存在")
    for field, value in update_data.items():
        setattr(card, field, value)
    card.updated_by = _actor_id(user)
    await db.commit()
    await db.refresh(card)
    return card


@router.delete("/{card_id}")
async def delete_ui_card(
    card_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("element", "element:ui_cards:delete")),
):
    result = await db.execute(select(SysUiCard).where(SysUiCard.id == card_id))
    card = result.scalars().first()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")
    await db.delete(card)
    await db.commit()
    return {"status": "success"}


@public_router.get("/session")
async def get_ui_card_session(card_token: str = Query(..., min_length=8)):
    from app.services.ai.ui_card_store import UiCardStore

    store = await UiCardStore.from_runtime()
    record = await store.get_by_token(card_token.strip())
    if record is None:
        raise HTTPException(status_code=404, detail="card_token 无效或已过期")
    return {
        "card_id": record.get("card_id"),
        "card_key": record.get("card_key"),
        "title": record.get("title"),
        "actions": record.get("actions") or [],
        "data": record.get("data") or {},
        "status": record.get("status"),
    }
