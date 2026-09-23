"""Source-aware qualification for the platform's ChatBI capability.

``data_query`` is retained as a compatibility capability name, but it is not
the generic answer to every request containing an aggregation or visualization
verb.  This module keeps the ChatBI gate independent from action recognition.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)


class ChatBIMode(str, Enum):
    DIRECT = "direct"
    CLARIFY = "clarify"
    DENY = "deny"


DIRECT_DATASET_SIMILARITY = 0.65


@dataclass(frozen=True)
class DatasetCandidate:
    dataset_id: int
    display_name: str
    similarity: float
    content: str = ""


@dataclass(frozen=True)
class ChatBIQualification:
    mode: ChatBIMode
    evidence_level: str
    matched_dataset_ids: tuple[int, ...] = ()
    matched_dataset_names: tuple[str, ...] = ()
    reason: str = ""


_NON_CHATBI_DOMAINS = frozenset({
    "runtime_environment",
    "local_file",
    "public_web",
    "internal_docs",
    "general",
    "unqualified_data_intent",
})


def _candidate_from_value(value: Any) -> DatasetCandidate | None:
    if isinstance(value, DatasetCandidate):
        return value
    if not isinstance(value, Mapping):
        return None
    try:
        dataset_id = int(value.get("dataset_id"))
        similarity = float(value.get("similarity") or 0.0)
    except (TypeError, ValueError):
        return None
    return DatasetCandidate(
        dataset_id=dataset_id,
        display_name=str(value.get("display_name") or value.get("name") or dataset_id),
        similarity=similarity,
        content=str(value.get("content") or ""),
    )


def _normalize_candidates(values: Iterable[Any] | None) -> list[DatasetCandidate]:
    candidates = [candidate for value in values or [] if (candidate := _candidate_from_value(value))]
    return sorted(candidates, key=lambda item: item.similarity, reverse=True)


def qualify_chatbi_request(
    *,
    domain: str | None,
    operation: str | None,
    dataset_candidates: Iterable[Any] | None,
    previous_chatbi_result: bool = False,
    explicit_dataset: bool = False,
) -> ChatBIQualification:
    """Return the least-privileged ChatBI mode supported by current evidence."""
    normalized_domain = str(domain or "unknown").strip().lower()
    candidates = _normalize_candidates(dataset_candidates)

    if normalized_domain in _NON_CHATBI_DOMAINS:
        return ChatBIQualification(
            mode=ChatBIMode.DENY,
            evidence_level="source_conflict",
            reason=f"request domain {normalized_domain!r} is not ChatBI business data",
        )

    if previous_chatbi_result:
        return ChatBIQualification(
            mode=ChatBIMode.DIRECT,
            evidence_level="previous_chatbi_result",
            matched_dataset_ids=tuple(item.dataset_id for item in candidates),
            matched_dataset_names=tuple(item.display_name for item in candidates),
            reason=f"{operation or 'transform'} continues a previous ChatBI result",
        )

    if explicit_dataset:
        return ChatBIQualification(
            mode=ChatBIMode.DIRECT,
            evidence_level="explicit_dataset",
            matched_dataset_ids=tuple(item.dataset_id for item in candidates),
            matched_dataset_names=tuple(item.display_name for item in candidates),
            reason="user explicitly selected a dataset or data portal",
        )

    if candidates and candidates[0].similarity >= DIRECT_DATASET_SIMILARITY:
        return ChatBIQualification(
            mode=ChatBIMode.DIRECT,
            evidence_level="dataset_match",
            matched_dataset_ids=tuple(item.dataset_id for item in candidates[:3]),
            matched_dataset_names=tuple(item.display_name for item in candidates[:3]),
            reason="authorized dataset metadata semantically matches the request",
        )

    if normalized_domain == "chatbi_business_data":
        return ChatBIQualification(
            mode=ChatBIMode.CLARIFY,
            evidence_level="semantic_only",
            matched_dataset_ids=tuple(item.dataset_id for item in candidates[:3]),
            matched_dataset_names=tuple(item.display_name for item in candidates[:3]),
            reason="semantic business-data signal exists, but no sufficiently strong dataset evidence",
        )

    return ChatBIQualification(
        mode=ChatBIMode.DENY,
        evidence_level="none",
        reason="no ChatBI business-data evidence",
    )


async def resolve_authorized_dataset_candidates(
    query: str,
    *,
    user_id: int | None,
    is_admin: bool = False,
    top_k: int = 3,
) -> list[DatasetCandidate]:
    """Find semantically relevant datasets within the caller's authorized scope.

    This is deliberately best-effort.  A missing embedding/Redis service must
    downgrade a request to ``CLARIFY`` rather than turn routing into an
    infrastructure failure or broaden the dataset scope.
    """
    if not str(query or "").strip():
        return []
    # ``search_datasets`` historically returns all datasets when user_id is
    # omitted.  Never use that permissive behavior for a non-admin route.
    from app.core.context import get_current_agent_context
    from app.services.embed_identity import embed_catalog_role_id

    ctx = get_current_agent_context()
    embed_role_id = embed_catalog_role_id((ctx.user_dimensions if ctx else None) or None)
    if embed_role_id is not None:
        is_admin = False
    if not is_admin and user_id is None and embed_role_id is None:
        return []

    try:
        from app.core.orm import AsyncSessionLocal
        from app.services.ai.embedding_client import EmbeddingClient
        from app.services.ai.metadata_index_service import MetadataIndexService
        from app.services.metadata_service import MetadataService

        async with AsyncSessionLocal() as session:
            datasets = await MetadataService.search_datasets(
                session,
                query=None,
                user_id=user_id,
                is_admin=is_admin,
                embed_role_id=embed_role_id,
                status=1,
            )

        dataset_map: dict[int, str] = {}
        for dataset in datasets or []:
            try:
                dataset_id = int(getattr(dataset, "id"))
            except (AttributeError, TypeError, ValueError):
                continue
            dataset_map[dataset_id] = str(
                getattr(dataset, "display_name", None)
                or getattr(dataset, "name", None)
                or dataset_id
            )
        if not dataset_map:
            return []

        query_embedding = await EmbeddingClient.embed_text(
            str(query).strip(),
            use_global=True,
        )
        rows = await MetadataIndexService.search_knn(
            query_embedding=query_embedding,
            authorized_dataset_ids=list(dataset_map),
            top_k=max(1, int(top_k)),
        )
        candidates: list[DatasetCandidate] = []
        for row in rows or []:
            try:
                dataset_id = int(row.get("dataset_id"))
                similarity = float(row.get("similarity") or 0.0)
            except (AttributeError, TypeError, ValueError):
                continue
            if dataset_id not in dataset_map:
                continue
            candidates.append(
                DatasetCandidate(
                    dataset_id=dataset_id,
                    display_name=dataset_map[dataset_id],
                    similarity=similarity,
                    content=str(row.get("content") or row.get("doc_name") or ""),
                )
            )
        return sorted(candidates, key=lambda item: item.similarity, reverse=True)
    except Exception as exc:  # noqa: BLE001 - routing must degrade safely
        logger.info("ChatBI dataset evidence unavailable during routing: %s", exc)
        return []
