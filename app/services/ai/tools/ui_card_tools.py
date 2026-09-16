"""Platform tool: show a registered business UI card and wait for user action."""
from __future__ import annotations

import json
import secrets
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.core.context import get_current_agent_context
from app.core.orm import AsyncSessionLocal
from app.models.ui_card import SysUiCard
from app.schemas.ui_card import _parse_json_list
from app.services.ai.tools.tool_compat import BaseTool
from app.services.ai.ui_card import (
    MAX_DATA_BYTES,
    UI_CARD_TOOL_NAME,
    append_query,
    origin_from_url,
)


class ShowUiCardArgs(BaseModel):
    card_key: str = Field(description="已登记的卡片标识，禁止传 URL")
    title: str = Field(description="对话气泡标题")
    data: dict[str, Any] = Field(default_factory=dict, description="灌给业务页的 JSON 数据")
    actions: list[str] = Field(description="本次开放的动作，必须是登记 allowed_actions 的子集")

    @field_validator("card_key")
    @classmethod
    def _card_key(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("card_key 不能为空")
        return text

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("title 不能为空")
        return text[:80]

    @field_validator("data")
    @classmethod
    def _data(cls, value: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(value or {}, ensure_ascii=False)
        if len(raw.encode("utf-8")) > MAX_DATA_BYTES:
            raise ValueError("data 不能超过 64KB")
        return value or {}

    @field_validator("actions")
    @classmethod
    def _actions(cls, value: list[str]) -> list[str]:
        actions = [str(item).strip() for item in value if str(item).strip()]
        if not actions:
            raise ValueError("actions 不能为空")
        return list(dict.fromkeys(actions))


def _error(message: str, hint: str = "") -> str:
    payload: dict[str, Any] = {"status": "error", "error": message}
    if hint:
        payload["hint"] = hint
    return json.dumps(payload, ensure_ascii=False)


class ShowUiCardTool(BaseTool):
    name = UI_CARD_TOOL_NAME
    description = (
        "向用户展示已登记的业务对话卡片（定制化页面：查看数据、确认、驳回、修改等）。"
        "只传 card_key 与 data，禁止传 URL/HTML。"
        "调用后返回 awaiting_user，必须停止并等待【UI卡片】回执；"
        "写入意向（如 confirm）后再调用写入类 HTTP/MCP 工具；reject 禁止写库；查看类动作（ack/close/viewed）只文字继续。"
        "简单选项提问用 ask_user_question，扁平字段确认用 request_user_confirmation。"
    )
    args_schema = ShowUiCardArgs

    async def ainvoke(self, arguments: dict[str, Any] | None = None) -> str:
        try:
            args = ShowUiCardArgs.model_validate(arguments or {})
        except Exception as exc:
            return _error(f"入参无效: {exc}", "请提供已登记 card_key、title、非空 actions 与可选 data")

        ctx = get_current_agent_context()
        user_id = getattr(ctx, "user_id", None) if ctx else None
        conversation_id = str(getattr(ctx, "conversation_id", "") or "").strip() if ctx else ""
        agent_id = str(getattr(ctx, "agent_id", "") or "").strip() if ctx else ""
        if not conversation_id or user_id in (None, ""):
            return _error("会话上下文缺失，无法展示业务卡片")

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(SysUiCard).where(SysUiCard.card_key == args.card_key)
            )
            card = result.scalar_one_or_none()

        if card is None or not card.is_active:
            return _error("卡片未登记或已停用", "请改用已启用的 card_key，或联系管理员登记")

        allowed_actions = [str(item) for item in _parse_json_list(card.allowed_actions)]
        if any(action not in allowed_actions for action in args.actions):
            return _error(
                "actions 超出登记范围",
                f"允许: {allowed_actions}",
            )

        allowed_agents = [str(item) for item in _parse_json_list(card.allowed_agent_ids)]
        if allowed_agents and agent_id and agent_id not in allowed_agents:
            return _error("当前智能体无权使用该卡片")

        render_url = str(card.url or "").strip()
        token = f"uct_{secrets.token_urlsafe(16)}"
        render_url = append_query(render_url, embed="1", card_token=token)
        origin = origin_from_url(render_url)
        if not origin and render_url.startswith("/"):
            origin = ""

        allowed_origins = [str(item) for item in _parse_json_list(card.allowed_origins)]
        if origin and allowed_origins and origin.rstrip("/") not in [
            item.rstrip("/") for item in allowed_origins
        ]:
            parsed = urlparse(str(card.url))
            origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else origin

        card_id = f"uc_{secrets.token_hex(8)}"
        height = int(card.default_height or 480)
        model_visible = {
            "status": "awaiting_user",
            "interaction_type": "ui_card",
            "card_id": card_id,
            "card_key": card.card_key,
            "title": args.title,
            "message": "已向用户展示业务卡片，请等待提交后再继续。",
            "actions": args.actions,
        }
        full = {
            **model_visible,
            "data": args.data,
            "render": {
                "type": "iframe",
                "url": render_url,
                "origin": origin,
                "height": height,
                "card_token": token,
                "token_ttl_seconds": int(card.token_ttl_seconds or 600),
            },
        }
        # 完整 render 留给 SSE；模型侧仍能看到 card_id/key，但不强调 token URL。
        return json.dumps(full, ensure_ascii=False)


show_ui_card = ShowUiCardTool()
