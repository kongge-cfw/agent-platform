"""AgentScope 工具调用参数恢复辅助。"""
from __future__ import annotations

import json
from typing import Any, Dict


def extract_agentscope_tool_call_input(agent: Any, tool_id: str) -> Any:
    """从 AgentScope 上下文读取已落盘的最终工具参数。"""
    if agent is None or not tool_id:
        return None
    context = getattr(getattr(agent, "state", None), "context", None)
    if not isinstance(context, (list, tuple)):
        return None

    for message in reversed(context):
        blocks: Any = None
        get_content_blocks = getattr(message, "get_content_blocks", None)
        if callable(get_content_blocks):
            try:
                blocks = get_content_blocks("tool_call")
            except Exception:
                blocks = None
        elif isinstance(message, dict):
            blocks = message.get("content")
        if not isinstance(blocks, (list, tuple)):
            blocks = [blocks] if blocks is not None else []

        for block in reversed(blocks):
            block_id = (
                block.get("id")
                if isinstance(block, dict)
                else getattr(block, "id", None)
            )
            if str(block_id or "") != str(tool_id):
                continue
            return (
                block.get("input")
                if isinstance(block, dict)
                else getattr(block, "input", None)
            )
    return None


def _parse_tool_args_object(value: Any) -> Dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def resolve_agentscope_tool_args(
    agent: Any,
    tool_id: str,
    streamed_args: Any,
) -> Dict[str, Any]:
    """优先使用有效流式参数，否则从 AgentScope 状态恢复。"""
    streamed = _parse_tool_args_object(streamed_args)
    saved = _parse_tool_args_object(
        extract_agentscope_tool_call_input(agent, tool_id)
    )
    if streamed:
        return streamed
    if saved is not None:
        return saved
    if streamed is not None:
        return streamed
    return {"input": streamed_args} if streamed_args else {}
