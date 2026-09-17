from __future__ import annotations

import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_permission
from app.core.orm import get_db_session
from app.models.embed_app import SysEmbedApp
from app.models.permission import Role
from app.schemas.embed_app import (
    EmbedRoleOption,
    SysEmbedAppCreate,
    SysEmbedAppResponse,
    SysEmbedAppUpdate,
    dump_json_list,
)
from app.services.embed_app_service import ensure_embed_role_exists, generate_embed_app_key

router = APIRouter()


def _dump_lists(data: dict[str, Any]) -> dict[str, Any]:
    payload = dict(data)
    for key in ("allowed_origins", "claim_keys"):
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


async def _role_names(db: AsyncSession, role_ids: set[int]) -> dict[int, str]:
    if not role_ids:
        return {}
    rows = (await db.execute(select(Role).where(Role.id.in_(role_ids)))).scalars().all()
    return {int(row.id): str(row.name or row.code or "") for row in rows}


def _to_response(app: SysEmbedApp, role_names: dict[int, str]) -> SysEmbedAppResponse:
    payload = SysEmbedAppResponse.model_validate(app)
    role_id = int(app.role_id) if app.role_id not in (None, "") else None
    return payload.model_copy(update={"role_name": role_names.get(role_id) if role_id else None})


@router.get("/role-options", response_model=List[EmbedRoleOption])
async def list_embed_app_role_options(
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("menu", "menu:embed_apps")),
):
    del user
    result = await db.execute(select(Role).order_by(Role.name, Role.code))
    return [
        EmbedRoleOption(id=int(role.id), code=role.code, name=role.name)
        for role in result.scalars().all()
    ]


@router.get("", response_model=List[SysEmbedAppResponse])
async def list_embed_apps(
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("menu", "menu:embed_apps")),
):
    del user
    result = await db.execute(select(SysEmbedApp).order_by(SysEmbedApp.updated_at.desc()))
    apps = result.scalars().all()
    role_ids = {int(app.role_id) for app in apps if app.role_id not in (None, "")}
    names = await _role_names(db, role_ids)
    return [_to_response(app, names) for app in apps]


@router.post("", response_model=SysEmbedAppResponse)
async def create_embed_app(
    app_in: SysEmbedAppCreate,
    db: AsyncSession = Depends(get_db_session),
    user: Dict = Depends(require_permission("element", "element:embed_apps:create")),
):
    data = _dump_lists(app_in.model_dump())
    try:
        await ensure_embed_role_exists(db, data.get("role_id"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data["app_key"] = await _allocate_app_key(db, app_in.app_key)
    app = SysEmbedApp(id=str(uuid.uuid4()), created_by=_actor_id(user), updated_by=_actor_id(user), **data)
    db.add(app)
    await db.commit()
    await db.refresh(app)
    names = await _role_names(db, {int(app.role_id)} if app.role_id not in (None, "") else set())
    return _to_response(app, names)


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
    if "role_id" in update_data:
        try:
            await ensure_embed_role_exists(db, update_data.get("role_id"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    for field, value in update_data.items():
        setattr(app, field, value)
    if app.role_id in (None, ""):
        raise HTTPException(status_code=400, detail="必须关联角色")
    app.updated_by = _actor_id(user)
    await db.commit()
    await db.refresh(app)
    names = await _role_names(db, {int(app.role_id)} if app.role_id not in (None, "") else set())
    return _to_response(app, names)


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
