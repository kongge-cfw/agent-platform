"""Skill directory content revision used to remount updated skills next turn."""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


def skill_dir_content_revision(skill_dir: str | None) -> str:
    """Stable fingerprint of a skill directory (relative path + mtime + size)."""
    if not skill_dir:
        return ""
    abs_dir = os.path.abspath(os.fspath(skill_dir))
    if not os.path.isdir(abs_dir):
        return ""

    entries: list[tuple[str, int, int]] = []
    for root, dir_names, file_names in os.walk(abs_dir):
        dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
        for name in sorted(file_names):
            if name.startswith("."):
                continue
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, abs_dir).replace("\\", "/")
            try:
                stat = os.stat(path)
            except OSError:
                continue
            entries.append((rel, int(stat.st_mtime_ns), int(stat.st_size)))
    if not entries:
        return ""
    payload = repr(entries).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def resolve_skill_dir(
    skill_id: str,
    *,
    scope: str | None = None,
    user_info: Any = None,
) -> Optional[str]:
    sid = str(skill_id or "").strip()
    if not sid:
        return None
    from app.core.config import settings

    del user_info
    resolved_scope = str(scope or "").strip().lower()
    if resolved_scope == "personal":
        return None
    path = os.path.join(os.path.abspath(settings.SKILLS_DIR), sid)
    return path if os.path.isdir(path) else None


def current_skill_revision(
    skill_id: str,
    *,
    scope: str | None = None,
    user_info: Any = None,
) -> str:
    return skill_dir_content_revision(
        resolve_skill_dir(skill_id, scope=scope, user_info=user_info)
    )


def skill_revision_changed(
    skill_id: str,
    stored_rev: str | None,
    *,
    scope: str | None = None,
    user_info: Any = None,
) -> bool:
    stored = str(stored_rev or "").strip()
    if not stored:
        return False
    current = current_skill_revision(skill_id, scope=scope, user_info=user_info)
    return bool(current) and current != stored


def mark_skill_files_changed(
    skill_id: str | None = None,
    *,
    scope: str = "global",
    user_info: Any = None,
) -> None:
    """Clear metadata cache after a skill write so the next turn sees new files."""
    try:
        from app.services.ai.skill_resolver import clear_skill_meta_cache

        clear_skill_meta_cache()
    except Exception:
        logger.debug("[Skills] Failed to clear skill meta cache after write", exc_info=True)
    if skill_id:
        logger.info(
            "[Skills] Marked skill files changed: id=%s scope=%s rev=%s",
            skill_id,
            scope,
            current_skill_revision(skill_id, scope=scope, user_info=user_info) or "-",
        )
