"""Shared turn-status definitions for pipeline and resume execution."""

from __future__ import annotations

from typing import Any


AWAITING_EXECUTION_STATUSES = frozenset(
    {"awaiting_permission", "awaiting_external_execution", "awaiting_user"}
)

# These states resume the same trace and therefore defer final audit persistence.
SAME_TRACE_RESUME_STATUSES = frozenset(
    {"interrupted", "awaiting_permission", "awaiting_external_execution"}
)

SHORT_CIRCUIT_NO_FINALIZE_STATUSES = frozenset(
    {"empty_request", "no_agent_config", "quota_exceeded"}
)

PIPELINE_TERMINAL_OR_SHORT_CIRCUIT_STATUSES = frozenset(
    {
        *SHORT_CIRCUIT_NO_FINALIZE_STATUSES,
        "cancelled",
        "denied",
        "error",
    }
)


def set_pipeline_execution_status(context: Any, status: str) -> str:
    """Write the canonical status and its executor compatibility mirror."""
    normalized = str(status or "success")
    context.execution_status = normalized
    shared_state = getattr(context, "shared_state", None)
    if isinstance(shared_state, dict):
        shared_state["execution_status"] = normalized
    return normalized


__all__ = [
    "AWAITING_EXECUTION_STATUSES",
    "PIPELINE_TERMINAL_OR_SHORT_CIRCUIT_STATUSES",
    "SAME_TRACE_RESUME_STATUSES",
    "SHORT_CIRCUIT_NO_FINALIZE_STATUSES",
    "set_pipeline_execution_status",
]
