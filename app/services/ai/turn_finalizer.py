"""Shared, side-effect-light turn finalization helpers."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.ai.runtime.agentscope.process_timeline_snapshot import (
    cancel_todo_items,
    complete_todo_items,
)

logger = logging.getLogger(__name__)


def finalize_todo_state(
    state: Optional[List[Dict[str, Any]]],
    *,
    execution_status: str,
) -> Optional[Dict[str, Any]]:
    """Apply the single Todo terminal transition shared by pipeline and resume."""
    if execution_status == "success":
        event = complete_todo_items(state)
        metric = "completed"
    elif execution_status == "cancelled":
        event = cancel_todo_items(state)
        metric = "cancelled"
    else:
        return None
    if event:
        logger.info(
            "[Todo] Finalized checklist: status=%s %s=%d",
            execution_status,
            metric,
            int((event.get("counts") or {}).get(metric, 0)),
        )
    return event


def should_persist_turn_history(
    content: Optional[str],
    process_timeline: Optional[List[Dict[str, Any]]],
    reasoning_content: Optional[str] = None,
) -> bool:
    return bool(
        str(content or "").strip()
        or process_timeline
        or str(reasoning_content or "").strip()
    )


__all__ = ["finalize_todo_state", "should_persist_turn_history"]
