"""HITL 出卡与解析名单：完整载荷与模型观察文本分离。

确认卡 / 提问卡的字段预览经常超过工具结果 4000 字上限。截断后的残缺 JSON
无法解析 SSE，前端就不出卡。完整载荷走 ContextVar 旁路给 runner 出卡，
回给模型的只保留可解析的短摘要。

解析类工具同样暂存完整 JSON 供续跑记事实；观察文本改为瘦身 records，
禁止从中间切断，避免 found=11 却只剩 9 条名单。
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from app.services.ai.business_confirmation import (
    BUSINESS_CONFIRMATION_TOOL_NAME,
    parse_confirmation_tool_output,
)
from app.services.ai.hitl_continuation import compact_resolve_tool_result_for_model
from app.services.ai.runtime.agentscope.stream_reconcile import truncate_for_context
from app.services.ai.user_question import (
    USER_QUESTION_TOOL_NAME,
    parse_user_question_tool_output,
)

HITL_UI_TOOL_NAMES = frozenset(
    {
        BUSINESS_CONFIRMATION_TOOL_NAME,
        USER_QUESTION_TOOL_NAME,
    }
)

_pending_hitl_ui_payloads: ContextVar[list[tuple[str, str]]] = ContextVar(
    "pending_hitl_ui_payloads",
    default=(),
)
_pending_resolve_payloads: ContextVar[list[tuple[str, str]]] = ContextVar(
    "pending_resolve_payloads",
    default=(),
)


def is_hitl_ui_tool(tool_name: str | None) -> bool:
    return str(tool_name or "").strip() in HITL_UI_TOOL_NAMES


def reset_pending_hitl_ui_payloads() -> None:
    _pending_hitl_ui_payloads.set(())


def stash_pending_hitl_ui_payload(tool_name: str, payload: str) -> None:
    name = str(tool_name or "").strip()
    text = str(payload or "")
    if not name or not text:
        return
    pending = list(_pending_hitl_ui_payloads.get() or ())
    pending.append((name, text))
    _pending_hitl_ui_payloads.set(tuple(pending))


def take_pending_hitl_ui_payload(tool_name: str | None) -> str | None:
    name = str(tool_name or "").strip()
    if not name:
        return None
    pending = list(_pending_hitl_ui_payloads.get() or ())
    for index, (stored_name, payload) in enumerate(pending):
        if stored_name == name:
            pending.pop(index)
            _pending_hitl_ui_payloads.set(tuple(pending))
            return payload
    return None


def reset_pending_resolve_payloads() -> None:
    _pending_resolve_payloads.set(())


def stash_pending_resolve_payload(tool_name: str, payload: str) -> None:
    name = str(tool_name or "").strip()
    text = str(payload or "")
    if not name or not text:
        return
    pending = list(_pending_resolve_payloads.get() or ())
    pending.append((name, text))
    _pending_resolve_payloads.set(tuple(pending))


def take_pending_resolve_payload(tool_name: str | None) -> str | None:
    name = str(tool_name or "").strip()
    if not name:
        return None
    pending = list(_pending_resolve_payloads.get() or ())
    for index, (stored_name, payload) in enumerate(pending):
        if stored_name == name:
            pending.pop(index)
            _pending_resolve_payloads.set(tuple(pending))
            return payload
    return None


def serialize_runtime_tool_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(result)


def compact_hitl_tool_result_for_model(tool_name: str, full_text: str) -> str | None:
    """把完整出卡 JSON 收成模型可读、且仍能表达 awaiting_user 的短摘要。"""
    name = str(tool_name or "").strip()
    if name == BUSINESS_CONFIRMATION_TOOL_NAME:
        payload = parse_confirmation_tool_output(full_text)
        if not payload:
            return None
        ui = payload.get("ui") if isinstance(payload.get("ui"), dict) else {}
        fields = ui.get("fields") if isinstance(ui.get("fields"), list) else []
        return json.dumps(
            {
                "status": "awaiting_user",
                "confirmation_id": payload.get("confirmation_id"),
                "message": payload.get("message")
                or "确认卡已展示给用户。请停止调用工具，等待用户在卡片上确认或取消。",
                "ui": {
                    "title": ui.get("title") or "",
                    "summary": ui.get("summary") or "",
                    "field_count": len(fields),
                },
            },
            ensure_ascii=False,
        )
    if name == USER_QUESTION_TOOL_NAME:
        payload = parse_user_question_tool_output(full_text)
        if not payload:
            return None
        options = payload.get("options") if isinstance(payload.get("options"), list) else []
        return json.dumps(
            {
                "status": "awaiting_user",
                "interaction_type": "question",
                "question_id": payload.get("question_id"),
                "question": payload.get("question"),
                "option_count": len(options),
                "message": "提问卡已展示给用户。请停止调用工具，等待用户作答或取消。",
            },
            ensure_ascii=False,
        )
    return None


def prepare_runtime_tool_observation_text(tool_name: str, result: Any) -> str:
    """生成写入 AgentScope / 模型上下文的工具观察文本。

    HITL 出卡成功时暂存完整载荷，观察文本改为短摘要。
    解析类工具暂存完整名单，观察文本改为可完整解析的瘦身 JSON，不从中间切断。
    其它工具仍按 4000 字截断。
    """
    full_text = serialize_runtime_tool_result(result)
    compact = compact_hitl_tool_result_for_model(tool_name, full_text)
    if compact is not None:
        stash_pending_hitl_ui_payload(tool_name, full_text)
        return compact
    resolve_compact = compact_resolve_tool_result_for_model(tool_name, result)
    if resolve_compact is None:
        resolve_compact = compact_resolve_tool_result_for_model(tool_name, full_text)
    if resolve_compact is not None:
        stash_pending_resolve_payload(tool_name, full_text)
        return resolve_compact
    return truncate_for_context(full_text)
