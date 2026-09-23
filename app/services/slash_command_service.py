from typing import Any, List, Mapping, Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.orm import Base
from sqlalchemy import Column, Integer, String, Text, DateTime, func


class SlashCommand(Base):
    __tablename__ = "slash_commands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    label = Column(String(50), nullable=False)
    command = Column(Text, nullable=False)
    scenario = Column(String(200), nullable=False, default="")
    sort_order = Column(Integer, default=0)
    created_by = Column(String(64), default="system")
    embed_app_key = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class SlashCommandBase(BaseModel):
    label: str
    command: str
    scenario: str = ""
    sort_order: int = 0

    @field_validator("scenario", mode="before")
    @classmethod
    def _normalize_scenario(cls, value: Any) -> str:
        return str(value or "").strip()[:200]


class SlashCommandCreate(SlashCommandBase):
    pass


class SlashCommandUpdate(SlashCommandBase):
    pass


class SlashCommandReorderItem(BaseModel):
    id: int
    sort_order: int


class SlashCommandReorderRequest(BaseModel):
    items: List[SlashCommandReorderItem]


class SlashCommandResponse(SlashCommandBase):
    id: int
    created_by: str
    embed_app_key: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


def resolve_slash_command_app_key(user: Optional[Mapping[str, Any]]) -> str:
    """嵌入会话取业务入口 app_key；站内会话为空（走全局快捷指令）。"""
    from app.services.embed_identity import is_embed_session

    if not is_embed_session(user):
        return ""
    return str((user or {}).get("embed_app_key") or (user or {}).get("app_key") or "").strip()


def slash_command_list_mode(user: Optional[Mapping[str, Any]]) -> str:
    """embed_app：按入口隔离；embed_unbound：嵌入但无应用，不读写个人指令；platform：站内全局。"""
    from app.services.embed_identity import is_embed_session

    if not is_embed_session(user):
        return "platform"
    if resolve_slash_command_app_key(user):
        return "embed_app"
    return "embed_unbound"


def _cmd_field(cmd: Any, name: str) -> Any:
    if isinstance(cmd, Mapping):
        return cmd.get(name)
    return getattr(cmd, name, None)


def slash_command_writable(cmd: Any, user: Optional[Mapping[str, Any]]) -> bool:
    """个人指令只能在同一业务入口内由本人改删；站内不能动嵌入入口下的指令。"""
    user = user or {}
    username = str(user.get("user_name") or "")
    cmd_by = str(_cmd_field(cmd, "created_by") or "")
    cmd_key = str(_cmd_field(cmd, "embed_app_key") or "").strip()
    mode = slash_command_list_mode(user)
    if mode == "embed_unbound":
        return False
    if mode == "embed_app":
        return bool(username) and cmd_by == username and cmd_key == resolve_slash_command_app_key(user)
    if cmd_key:
        return False
    if str(user.get("role") or "") == "admin":
        return True
    return bool(username) and cmd_by == username


class SlashCommandService:
    @staticmethod
    async def list_commands(session: AsyncSession, user: dict) -> List[SlashCommand]:
        """
        可见范围：
        - 嵌入应用会话：仅本人在该 app_key 下创建的指令（不含站内 admin/system 全局指令）
        - 未绑定应用的嵌入会话：空列表
        - 站内：system/admin + 本人、且未绑定嵌入应用的指令
        """
        from sqlalchemy import case, or_, and_

        mode = slash_command_list_mode(user)
        if mode == "embed_unbound":
            return []

        username = user.get("user_name", "unknown")
        if mode == "embed_app":
            app_key = resolve_slash_command_app_key(user)
            stmt = (
                select(SlashCommand)
                .where(
                    SlashCommand.created_by == username,
                    SlashCommand.embed_app_key == app_key,
                )
                .order_by(SlashCommand.sort_order.asc())
            )
            result = await session.execute(stmt)
            return result.scalars().all()

        filter_condition = and_(
            or_(
                SlashCommand.created_by.in_(["system", "admin"]),
                SlashCommand.created_by == username,
            ),
            or_(SlashCommand.embed_app_key.is_(None), SlashCommand.embed_app_key == ""),
        )
        priority_sort = case(
            (SlashCommand.created_by == username, 0),
            else_=1,
        )
        stmt = select(SlashCommand).where(filter_condition).order_by(
            priority_sort.asc(),
            SlashCommand.sort_order.asc(),
        )
        result = await session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def create_command(session: AsyncSession, data: SlashCommandCreate, user: dict) -> SlashCommand:
        mode = slash_command_list_mode(user)
        if mode == "embed_unbound":
            raise ValueError("嵌入会话未绑定业务入口，无法保存个人快捷指令")
        app_key = resolve_slash_command_app_key(user) or None
        user_name = str(user.get("user_name") or "unknown")
        cmd = SlashCommand(
            **data.model_dump(),
            created_by=user_name,
            embed_app_key=app_key,
        )
        session.add(cmd)
        await session.commit()
        await session.refresh(cmd)
        return cmd

    @staticmethod
    async def update_command(session: AsyncSession, cmd_id: int, data: SlashCommandUpdate, user: dict) -> Optional[SlashCommand]:
        cmd = await session.get(SlashCommand, cmd_id)
        if not cmd or not slash_command_writable(cmd, user):
            return None

        for key, value in data.model_dump().items():
            setattr(cmd, key, value)

        await session.commit()
        await session.refresh(cmd)
        return cmd

    @staticmethod
    async def delete_command(session: AsyncSession, cmd_id: int, user: dict) -> bool:
        cmd = await session.get(SlashCommand, cmd_id)
        if not cmd or not slash_command_writable(cmd, user):
            return False

        await session.delete(cmd)
        await session.commit()
        return True

    @staticmethod
    async def reorder_commands(session: AsyncSession, data: SlashCommandReorderRequest, user: dict) -> bool:
        ids = [item.id for item in data.items]
        stmt = select(SlashCommand).where(SlashCommand.id.in_(ids))
        result = await session.execute(stmt)
        commands = {c.id: c for c in result.scalars().all()}

        for item in data.items:
            cmd = commands.get(item.id)
            if not cmd or not slash_command_writable(cmd, user):
                continue
            cmd.sort_order = item.sort_order

        await session.commit()
        return True
