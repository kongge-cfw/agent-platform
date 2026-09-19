"""Path validation shared by Office document tools."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Sequence

from app.utils.fs_paths import get_data_base_dir

MAX_DOCUMENT_BYTES = 20 * 1024 * 1024


class DocumentPathError(ValueError):
    """A document path is not safe for the current request."""


async def resolve_workspace_root() -> str:
    from app.services.ai.runtime.agentscope.workspace import resolve_workspace_root as resolver

    return await resolver()


def resolve_session_workdir(
    *,
    root: str,
    user_id: int | str | None,
    conversation_id: str,
    user_name: str | None = None,
    user_info: dict | None = None,
) -> str:
    from app.services.ai.runtime.agentscope.workspace import resolve_session_workdir as resolver

    return resolver(
        root=root,
        user_id=user_id,
        conversation_id=conversation_id,
        user_name=user_name,
        user_info=user_info,
    )


def resolve_user_docs_dir(
    *,
    root: str,
    user_id: int | str | None,
    user_name: str | None = None,
    user_info: dict | None = None,
) -> str:
    from app.services.ai.runtime.agentscope.workspace import resolve_user_docs_dir as resolver

    return resolver(
        root=root,
        user_id=user_id,
        user_name=user_name,
        user_info=user_info,
    )


def _path_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _normalize_platform_path(path: str) -> Path:
    data_root = Path(get_data_base_dir()).resolve()
    raw_path = str(path or "")
    if raw_path == "/app/data":
        return data_root
    if raw_path.startswith("/app/data/"):
        raw_path = str(data_root / raw_path.removeprefix("/app/data/"))
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = data_root / candidate
    return candidate.resolve()


def _validate_extension(path: Path, allowed_extensions: Iterable[str]) -> None:
    allowed = {str(ext).lower() for ext in allowed_extensions}
    if path.suffix.lower() not in allowed:
        supported = ", ".join(sorted(allowed))
        raise DocumentPathError(f"不支持的文件类型，仅支持：{supported}")


_UPLOAD_NAME_SUFFIX_RE = re.compile(r"^(.+)_([0-9a-f]{4})(\.[^.]+)$", re.IGNORECASE)


def _attachment_name_keys(name: str) -> set[str]:
    """卡片原名与托管名 `stem_xxxx.ext` 互认，避免模型只抄显示文件名。"""
    raw = Path(str(name or "")).name
    if not raw:
        return set()
    keys = {raw}
    matched = _UPLOAD_NAME_SUFFIX_RE.match(raw)
    if matched:
        keys.add(f"{matched.group(1)}{matched.group(3)}")
    return keys


def _is_basename_only(path: str) -> bool:
    raw = str(path or "").strip().replace("\\", "/")
    return bool(raw) and "/" not in raw and not raw.startswith("/app/data/")


def _pick_newest(matches: Sequence[Path]) -> Path | None:
    existing = [item for item in matches if item.is_file()]
    if not existing:
        return None
    if len(existing) == 1:
        return existing[0]
    return max(existing, key=lambda item: item.stat().st_mtime)


def _match_authorized_attachment(
    requested: str,
    *,
    preferred: set[Path],
    allowed: set[Path],
) -> Path | None:
    requested_name = Path(str(requested or "")).name
    requested_keys = _attachment_name_keys(requested_name)
    if not requested_keys:
        return None

    def _exact(pool: set[Path]) -> list[Path]:
        return [item for item in pool if item.is_file() and item.name == requested_name]

    def _aliased(pool: set[Path]) -> list[Path]:
        return [
            item
            for item in pool
            if item.is_file() and (_attachment_name_keys(item.name) & requested_keys)
        ]

    # 本轮先于历史：否则「foo.xlsx」会命中上一轮原名，而不是本轮的 foo_xxxx.xlsx。
    for matcher in (_exact, _aliased):
        picked = _pick_newest(matcher(preferred))
        if picked is not None:
            return picked
    for matcher in (_exact, _aliased):
        picked = _pick_newest(matcher(allowed))
        if picked is not None:
            return picked
    return None


async def resolve_document_input_path(
    path: str,
    *,
    allowed_attachment_paths: Iterable[str],
    user_id: int | str | None,
    conversation_id: str | None,
    allowed_extensions: Iterable[str],
    user_name: str | None = None,
    preferred_attachment_paths: Iterable[str] | None = None,
) -> Path:
    """Resolve one existing document, limited to this request's attachments or workspace."""
    preferred_resolved = {
        _normalize_platform_path(item)
        for item in (preferred_attachment_paths or [])
        if str(item or "").strip()
    }
    allowed_resolved = {
        _normalize_platform_path(item)
        for item in allowed_attachment_paths
        if str(item or "").strip()
    } | preferred_resolved
    candidate = _normalize_platform_path(path)
    alias = _match_authorized_attachment(
        path,
        preferred=preferred_resolved,
        allowed=allowed_resolved,
    )
    # 模型常只传文件名：不要误用 data 根下的同名残留，优先本轮已授权附件。
    if _is_basename_only(path) and alias is not None:
        candidate = alias
    elif not candidate.is_file():
        if alias is None:
            raise DocumentPathError("文件不存在或不可访问")
        candidate = alias
    if candidate.stat().st_size > MAX_DOCUMENT_BYTES:
        raise DocumentPathError("文件大小超出 20MB 限制")
    _validate_extension(candidate, allowed_extensions)

    if candidate in allowed_resolved:
        return candidate

    data_root = Path(get_data_base_dir()).resolve()
    uploads_root = (data_root / "uploads").resolve()
    allowed_uploads = allowed_resolved
    if _path_under(candidate, uploads_root):
        if candidate not in allowed_uploads:
            raise DocumentPathError("该上传文件不属于当前会话附件")
        return candidate

    workspace_root = Path(await resolve_workspace_root()).resolve()
    from app.services.ai.runtime.agentscope.workspace import resolve_user_workspace_root

    user_workspace_dir = resolve_user_workspace_root(
        root=str(workspace_root),
        user_id=user_id,
        user_name=user_name,
    )
    if user_workspace_dir and _path_under(candidate, Path(user_workspace_dir).resolve()):
        return candidate

    if not conversation_id:
        raise DocumentPathError("当前会话缺少工作目录，无法访问该文件")
    user_docs_dir = Path(
        resolve_user_docs_dir(
            root=str(workspace_root),
            user_id=user_id,
            user_name=user_name,
        )
    ).resolve()
    if _path_under(candidate, user_docs_dir):
        return candidate
    session_workdir = Path(
        resolve_session_workdir(
            root=str(workspace_root),
            user_id=user_id,
            conversation_id=conversation_id,
            user_name=user_name,
        )
    ).resolve()
    if _path_under(candidate, session_workdir):
        return candidate
    from app.services.ai.runtime.agentscope.workspace import resolve_legacy_session_workdir

    legacy_workdir = Path(
        resolve_legacy_session_workdir(
            root=str(workspace_root),
            user_id=user_id,
            conversation_id=conversation_id,
            user_name=user_name,
        )
    ).resolve()
    if legacy_workdir != session_workdir and _path_under(candidate, legacy_workdir):
        return candidate
    raise DocumentPathError("文件不在当前会话允许访问的目录中")


def sanitize_output_filename(filename: str, allowed_extensions: Iterable[str]) -> str:
    raw_name = os.path.basename(str(filename or "")).strip()
    clean_name = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", raw_name)
    if not clean_name or clean_name in {".", ".."}:
        raise DocumentPathError("输出文件名不能为空")
    _validate_extension(Path(clean_name), allowed_extensions)
    return clean_name


async def resolve_document_output_path(
    filename: str,
    *,
    user_id: int | str | None,
    conversation_id: str | None,
    allowed_extensions: Iterable[str],
    user_name: str | None = None,
) -> Path:
    if not conversation_id:
        raise DocumentPathError("当前会话缺少工作目录，无法生成文件")
    clean_name = sanitize_output_filename(filename, allowed_extensions)
    workspace_root = Path(await resolve_workspace_root()).resolve()
    docs_dir = Path(
        resolve_user_docs_dir(
            root=str(workspace_root),
            user_id=user_id,
            user_name=user_name,
        )
    ).resolve()
    docs_dir.mkdir(parents=True, exist_ok=True)
    output_path = (docs_dir / clean_name).resolve()
    if not _path_under(output_path, docs_dir):
        raise DocumentPathError("输出文件路径不安全")
    return output_path
