"""Protocol helpers for business UI cards in chat."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

UI_CARD_TOOL_NAME = "show_ui_card"
UI_CARD_MESSAGE_PREFIX = "【UI卡片】"
MAX_DATA_BYTES = 64 * 1024


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value.strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def parse_ui_card_tool_output(tool_output: Any) -> dict[str, Any] | None:
    payload = _as_dict(tool_output)
    if not payload and isinstance(tool_output, dict) and "text" in tool_output:
        payload = _as_dict(tool_output.get("text"))
    if not payload or payload.get("status") != "awaiting_user":
        return None
    if payload.get("interaction_type") != "ui_card":
        return None
    card_id = str(payload.get("card_id") or "").strip()
    card_key = str(payload.get("card_key") or "").strip()
    render = payload.get("render")
    if not card_id or not card_key or not isinstance(render, dict):
        return None
    return payload


def build_ui_card_sse(
    *,
    tool_name: str,
    tool_output: Any,
    tool_call_id: str = "",
) -> dict[str, Any] | None:
    if tool_name != UI_CARD_TOOL_NAME:
        return None
    payload = parse_ui_card_tool_output(tool_output)
    if payload is None:
        return None
    return {
        "type": "ui_card",
        "tool_call_id": tool_call_id,
        "card_id": str(payload["card_id"]),
        "card_key": str(payload["card_key"]),
        "title": str(payload.get("title") or ""),
        "actions": payload.get("actions") or [],
        "data": payload.get("data") or {},
        "render": payload.get("render") or {},
        "status": "pending",
    }


def append_query(url: str, **params: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        if value:
            query[key] = value
    return urlunparse(parsed._replace(query=urlencode(query)))


def origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def is_ui_card_receipt_message(text: str | None) -> bool:
    return UI_CARD_MESSAGE_PREFIX in str(text or "")


def parse_ui_card_receipt(text: str | None) -> dict[str, Any] | None:
    raw = str(text or "")
    if not is_ui_card_receipt_message(raw):
        return None
    values: dict[str, str] = {}
    payload_lines: list[str] = []
    in_payload = False
    for line in raw.splitlines():
        if in_payload:
            payload_lines.append(line)
            continue
        if line.strip().startswith("payload:"):
            in_payload = True
            payload_lines.append(line.split(":", 1)[1].lstrip())
            continue
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    card_id = values.get("card_id", "").strip()
    card_key = values.get("card_key", "").strip()
    action = values.get("action", "").strip()
    if not card_id or values.get("interaction_type") != "ui_card" or not action:
        return None
    payload_text = "\n".join(payload_lines).strip() or "{}"
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return {
        "card_id": card_id,
        "card_key": card_key,
        "action": action,
        "payload": payload,
    }


def build_ui_card_receipt(
    *,
    card_id: str,
    card_key: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> str:
    body = json.dumps(payload or {}, ensure_ascii=False)
    return (
        f"{UI_CARD_MESSAGE_PREFIX}\n"
        "interaction_type: ui_card\n"
        f"card_id: {card_id}\n"
        f"card_key: {card_key}\n"
        f"action: {action}\n"
        f"payload: {body}"
    )


async def persist_ui_card_event(
    *,
    event: dict[str, Any],
    user_id: int | str,
    conversation_id: str,
) -> dict[str, Any]:
    from app.services.ai.ui_card_store import UiCardStore

    if not str(conversation_id or "").strip():
        raise ValueError("业务卡片必须绑定会话")
    render = event.get("render") if isinstance(event.get("render"), dict) else {}
    token = str(render.get("card_token") or "").strip()
    if not token:
        raise ValueError("业务卡片缺少 card_token")
    token_ttl_seconds = int(render.get("token_ttl_seconds") or 600)
    store = await UiCardStore.from_runtime()
    return await store.create_pending(
        user_id=user_id,
        conversation_id=conversation_id,
        card_id=str(event["card_id"]),
        token=token,
        token_ttl_seconds=token_ttl_seconds,
        payload={
            "card_key": str(event.get("card_key") or ""),
            "title": str(event.get("title") or ""),
            "actions": event.get("actions") or [],
            "data": event.get("data") or {},
            "render": render,
            "tool_call_id": str(event.get("tool_call_id") or ""),
        },
    )
