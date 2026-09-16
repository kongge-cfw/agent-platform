from __future__ import annotations

import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.core.orm import get_db_session
from app.models.embed_app import SysEmbedApp
from app.schemas.embed_app import (
    SysEmbedAppCreate,
    SysEmbedAppResponse,
    SysEmbedAppUpdate,
    dump_json_list,
)
from app.services.embed_app_service import generate_embed_app_key

router = APIRouter()


def _dump_lists(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    for key in ("allowed_agent_ids", "allowed_origins", "claim_keys"):
        if key in payload and payload[key] is not None:
            payload[key] = dump_json_list(payload[key])
    return payload


def _actor_id(user: Dict[str, Any]) -> str:
    return str(user.get("user_id") or user.get("id") or "")


async def _allocate_app_key(db: AsyncSession, requested: str | None) -> str:
    if requested:
        existing = await db.execute(select(SysEmbedApp).where(SysEmbedApp.app_key == requested))
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="app_key 已存在")
        return requested
    for _ in range(8):
        candidate = generate_embed_app_key()
        existing = await db.execute(select(SysEmbedApp).where(SysEmbedApp.app_key == candidate))
        if not existing.scalars().first():
            return candidate
    raise HTTPException(status_code=500, detail="无法生成唯一应用 Key")


@router.get("", response_model=List[SysEmbedAppResponse])
async def list_embed_apps(
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("menu", "menu:embed_apps")),
):
    del user
    result = await db.execute(select(SysEmbedApp).order_by(SysEmbedApp.updated_at.desc()))
    return result.scalars().all()


@router.post("", response_model=SysEmbedAppResponse)
async def create_embed_app(
    app_in: SysEmbedAppCreate,
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("element", "element:embed_apps:create")),
):
    data = _dump_lists(app_in.model_dump())
    data["app_key"] = await _allocate_app_key(db, app_in.app_key)
    app = SysEmbedApp(id=str(uuid.uuid4()), created_by=_actor_id(user), updated_by=_actor_id(user), **data)
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


@router.put("/{app_id}", response_model=SysEmbedAppResponse)
async def update_embed_app(
    app_id: str,
    app_in: SysEmbedAppUpdate,
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("element", "element:embed_apps:edit")),
):
    result = await db.execute(select(SysEmbedApp).where(SysEmbedApp.id == app_id))
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=404, detail="嵌入应用不存在")
    update_data = _dump_lists(app_in.model_dump(exclude_unset=True))
    for field, value in update_data.items():
        setattr(app, field, value)
    app.updated_by = _actor_id(user)
    await db.commit()
    await db.refresh(app)
    return app


@router.delete("/{app_id}")
async def delete_embed_app(
    app_id: str,
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("element", "element:embed_apps:delete")),
):
    result = await db.execute(select(SysEmbedApp).where(SysEmbedApp.id == app_id))
    app = result.scalars().first()
    if not app:
        raise HTTPException(status_code=404, detail="嵌入应用不存在")
    await db.delete(app)
    await db.commit()
    return {"status": "success"}
