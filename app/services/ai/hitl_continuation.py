"""HITL 确认卡 / 提问卡回执轮的续跑上下文（技能、附件、已解析主键、todo）。"""
from __future__ import annotations

import copy
import json
import logging
import re
import time
from typing import Any

from app.services.ai.business_confirmation import (
    is_business_confirmation_cancel_message,
    is_business_confirmation_receipt_message,
)
from app.services.ai.conversation_identity import (
    try_session_user_id,
    try_session_user_id_from_agent_context,
)
from app.services.ai.user_question import (
    is_user_question_receipt_message,
    parse_user_question_receipt,
)

logger = logging.getLogger(__name__)

HITL_CONTINUATION_MARKER = "[HITL 续跑上下文]"
_SKIP_ATTACHMENT_TYPES = frozenset(
    {"skill", "knowledge_base", "metadata_dataset", "memory"}
)
_NON_ENTITY_RESOLVE_MARKERS = ("relative_date", "relative_dates")
_RECORD_NAME_KEYS = ("name", "matchedName", "matched_name", "label", "title")
_GENERIC_ID_KEYS = frozenset({"id", "uuid", "traceid", "requestid", "questionid", "confirmationid"})
_RESOLVED_ENTITIES_FACT = "resolved_entities"

_MEMORY_STORE: dict[str, dict[str, Any]] = {}


def _sticky_skill_exclude_ids() -> frozenset[str]:
    from app.services.ai.skills.injector import SkillInjector

    return frozenset({SkillInjector.USING_SUPERPOWERS_SKILL_ID})


def is_hitl_cancel_receipt(text: str | None) -> bool:
    if is_business_confirmation_cancel_message(text):
        return True
    if is_user_question_receipt_message(text):
        receipt = parse_user_question_receipt(text)
        if receipt and receipt.get("cancelled"):
            return True
        lowered = str(text or "").lower()
        if "cancelled: true" in lowered or "cancelled:true" in lowered:
            return True
    return False


def should_restore_hitl_continuation(text: str | None) -> bool:
    """确定 / 未取消的提问回执才续跑；取消回执不粘技能、不注入 facts。"""
    if not (
        is_business_confirmation_receipt_message(text)
        or is_user_question_receipt_message(text)
    ):
        return False
    return not is_hitl_cancel_receipt(text)


def empty_continuation() -> dict[str, Any]:
    return {
        "skills": [],
        "attachments": [],
        "original_user_query": "",
        "facts": {},
        "todos": None,
        "updated_at": 0,
    }


def attachments_from_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    from app.services.ai.executors.common import _attachment_abs_path

    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for message in messages or []:
        if str(message.get("role") or "").strip().lower() not in {"user", "human"}:
            continue
        for file_obj in message.get("files") or []:
            if not isinstance(file_obj, dict):
                continue
            file_type = str(file_obj.get("type") or "file").strip() or "file"
            if file_type in _SKIP_ATTACHMENT_TYPES:
                continue
            raw_url = str(file_obj.get("url") or "").strip()
            if not raw_url:
                continue
            path = str(_attachment_abs_path(file_obj) or raw_url).strip() or raw_url
            filename = str(file_obj.get("filename") or file_obj.get("name") or "").strip()
            key = f"{file_type}:{path}"
            if key in seen:
                continue
            seen.add(key)
            items.append({"filename": filename or path, "path": path, "type": file_type})
    return items


def last_user_turn_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    for message in reversed(messages or []):
        if str(message.get("role") or "").strip().lower() in {"user", "human"}:
            return [message]
    return []


def skills_from_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for message in messages or []:
        if str(message.get("role") or "").strip().lower() not in {"user", "human"}:
            continue
        for file_obj in message.get("files") or []:
            if not isinstance(file_obj, dict) or str(file_obj.get("type") or "") != "skill":
                continue
            skill_id = str(file_obj.get("url") or "").strip()
            if not skill_id or skill_id in seen or skill_id in _sticky_skill_exclude_ids():
                continue
            seen.add(skill_id)
            meta = file_obj.get("skillMeta") or file_obj.get("skill_meta") or {}
            name = ""
            scope = ""
            if isinstance(meta, dict):
                name = str(meta.get("name") or "").strip()
                scope = str(meta.get("scope") or "").strip()
            items.append(
                {
                    "id": skill_id,
                    "name": name or str(file_obj.get("filename") or skill_id).replace(" (技能)", ""),
                    "scope": scope,
                }
            )
    return items


def attachment_paths(payload: dict[str, Any] | None) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for item in (payload or {}).get("attachments") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def normalize_skills(skills: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for skill in skills or []:
        if not isinstance(skill, dict):
            continue
        skill_id = str(skill.get("id") or skill.get("url") or "").strip()
        if not skill_id or skill_id in seen or skill_id in _sticky_skill_exclude_ids():
            continue
        seen.add(skill_id)
        items.append(
            {
                "id": skill_id,
                "name": str(skill.get("name") or skill_id).strip() or skill_id,
                "scope": str(skill.get("scope") or "").strip(),
            }
        )
    return items


def is_entity_resolve_tool(tool_name: str | None) -> bool:
    """解析类工具：名称含 resolve，但排除相对日期等平台内置工具。"""
    name = str(tool_name or "").lower()
    if "resolve" not in name:
        return False
    return not any(marker in name for marker in _NON_ENTITY_RESOLVE_MARKERS)


def parse_resolve_tool_fact(tool_name: str | None, tool_output: Any) -> dict[str, Any] | None:
    if not is_entity_resolve_tool(tool_name):
        return None
    payload = _unwrap_tool_payload(tool_output)
    if not payload:
        return None
    records = payload.get("records")
    if not isinstance(records, list):
        records = payload.get("items")
    if not isinstance(records, list):
        return None
    simplified: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = ""
        for key in _RECORD_NAME_KEYS:
            name = str(record.get(key) or "").strip()
            if name:
                break
        id_key, id_value = _pick_record_id(record)
        found = bool(record.get("found", bool(id_value))) and bool(id_value)
        if not name and not id_value:
            continue
        simplified.append(
            {
                "name": name,
                "found": found,
                "id_key": id_key,
                "id_value": id_value if found else "",
                "matchedName": str(record.get("matchedName") or name).strip(),
            }
        )
    if not simplified:
        return None
    return {
        "source_tool": str(tool_name or ""),
        "total": payload.get("total", len(simplified)),
        "found": payload.get("found", sum(1 for item in simplified if item["found"])),
        "missing": payload.get("missing", sum(1 for item in simplified if not item["found"])),
        "records": simplified,
    }


def resolved_id_map(payload: dict[str, Any] | None) -> dict[str, tuple[str, str]]:
    """name -> (id_key, id_value)。"""
    mapping: dict[str, tuple[str, str]] = {}
    facts = (payload or {}).get("facts") or {}
    batches = []
    current = facts.get(_RESOLVED_ENTITIES_FACT)
    if isinstance(current, dict):
        batches.append(current)
    # 兼容本能力首版写入 Redis 的 fact 名，下个 TTL 周期后可删。
    legacy = facts.get("enterprise_resolve")
    if isinstance(legacy, dict):
        batches.append(legacy)
    for fact in batches:
        for record in fact.get("records") or []:
            if not isinstance(record, dict) or not record.get("found"):
                continue
            id_key, id_value = _record_id(record)
            if not id_value:
                continue
            for key in (record.get("name"), record.get("matchedName")):
                name = str(key or "").strip()
                if name:
                    mapping[name] = (id_key, id_value)
    return mapping


def enrich_confirmation_fields(
    fields: list[dict[str, Any]],
    continuation: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """若字段值里出现已解析对象名称，则补上工具返回的主键。"""
    id_map = resolved_id_map(continuation)
    if not id_map or not fields:
        return [dict(field) for field in fields]
    enriched: list[dict[str, Any]] = []
    wrote_ids = False
    for field in fields:
        next_field = dict(field)
        value_type = str(next_field.get("value_type") or "string")
        if value_type in {"boolean", "number"}:
            enriched.append(next_field)
            continue
        rewritten, matched = _rewrite_if_resolved_names(next_field.get("value"), id_map)
        if matched:
            next_field["value"] = rewritten
            wrote_ids = True
            if "\n" in str(rewritten or "") and value_type != "boolean":
                next_field["value_type"] = "text"
        key_text = str(next_field.get("key") or "")
        label_text = str(next_field.get("label") or "")
        if key_text == "resolved_ids" or "已解析主键" in label_text or _looks_like_id_list_key(key_text):
            wrote_ids = True
        enriched.append(next_field)
    if wrote_ids:
        already = any(
            str(item.get("key") or "") == "resolved_ids"
            or _looks_like_id_list_key(str(item.get("key") or ""))
            or "已解析主键" in str(item.get("label") or "")
            for item in enriched
        )
        if not already:
            lines = [
                f"{name}（{id_key}: {id_value}）"
                for name, (id_key, id_value) in id_map.items()
            ]
            if lines:
                enriched.append(
                    {
                        "key": "resolved_ids",
                        "label": "已解析主键",
                        "value": "\n".join(lines),
                        "editable": False,
                        "value_type": "text",
                    }
                )
    return enriched


def build_continuation_prompt_block(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    skills = normalize_skills(payload.get("skills"))
    attachments = payload.get("attachments") or []
    original = str(payload.get("original_user_query") or "").strip()
    facts = payload.get("facts") or {}
    fact = facts.get(_RESOLVED_ENTITIES_FACT) or facts.get("enterprise_resolve") or {}
    todos = payload.get("todos") if isinstance(payload.get("todos"), dict) else None
    if not skills and not attachments and not original and not fact and not todos:
        return ""

    lines = [
        HITL_CONTINUATION_MARKER,
        "本轮是确认卡/提问卡回执，不是新任务。必须继续上一轮原任务：",
        "- 若已启用技能，按该 SKILL.md 的 workflow 执行，不要跳过解析、校验或结构化说明。",
        "- 禁止臆造外部主键；快照只有名称时必须使用下方已解析 ID，或再次调用解析工具。",
        "- 需要附件内容时直接读取下列路径，不要声称文件不存在。",
    ]
    if skills:
        skill_text = "、".join(f"{item['name']}（ID: {item['id']}）" for item in skills)
        lines.append(f"- 上一轮已启用技能：{skill_text}")
    if original:
        clipped = original if len(original) <= 1200 else original[:1200] + "…"
        lines.append(f"- 原用户任务：{clipped}")
    if attachments:
        lines.append("- 上一轮附件路径：")
        for item in attachments[:12]:
            if not isinstance(item, dict):
                continue
            filename = str(item.get("filename") or "").strip()
            path = str(item.get("path") or "").strip()
            if path:
                lines.append(f"  - {filename or path}: {path}")
    records = fact.get("records") if isinstance(fact, dict) else None
    if isinstance(records, list) and records:
        lines.append("- 已解析对象主键（以工具返回为准，禁止改写 ID）：")
        for record in records[:40]:
            if not isinstance(record, dict):
                continue
            name = str(record.get("name") or "").strip()
            id_key, id_value = _record_id(record)
            if record.get("found") and id_value:
                lines.append(f"  - {name} → {id_key}={id_value}")
            elif name:
                lines.append(f"  - {name} → 未解析到主键，不得写入")
    if todos and isinstance(todos.get("todos"), list) and todos.get("todos"):
        lines.append("- 上一轮任务清单仍有效，请在完成后更新对应项，不要无故整表重开。")
    return "\n".join(lines)


def _record_id(record: dict[str, Any]) -> tuple[str, str]:
    id_key = str(record.get("id_key") or "").strip()
    id_value = str(record.get("id_value") or "").strip()
    if id_value:
        return id_key or "id", id_value
    return _pick_record_id(record)


def _pick_record_id(record: dict[str, Any]) -> tuple[str, str]:
    candidates: list[tuple[str, str]] = []
    for key, value in record.items():
        key_text = str(key or "")
        if not _looks_like_id_key(key_text):
            continue
        text = str(value or "").strip()
        if text and text.lower() not in {"none", "null"}:
            candidates.append((key_text, text))
    if candidates:
        candidates.sort(key=lambda item: len(item[0]), reverse=True)
        return candidates[0]
    raw = record.get("id")
    text = str(raw or "").strip()
    if text and text.lower() not in {"none", "null"}:
        return "id", text
    return "", ""


def _looks_like_id_list_key(key: str) -> bool:
    compact = key.replace("_", "").lower()
    return compact.endswith("ids") or compact.endswith("idlist")


def _looks_like_id_key(key: str) -> bool:
    compact = key.replace("_", "").lower()
    if compact in _GENERIC_ID_KEYS:
        return False
    if key.endswith("Id") or key.endswith("_id") or key.endswith("ID"):
        return True
    return compact.endswith("id")


def _normalize_entity_token(token: str) -> str:
    cleaned = str(token or "").strip()
    cleaned = re.sub(r"^[\-\*\u2022]\s*", "", cleaned)
    cleaned = re.sub(r"^\d+[\.、\.\)）]\s*", "", cleaned)
    return cleaned.strip()


def _rewrite_if_resolved_names(
    value: Any, id_map: dict[str, tuple[str, str]]
) -> tuple[Any, bool]:
    if isinstance(value, list):
        parts = []
        matched = False
        for item in value:
            token = str(item).strip()
            if not token:
                continue
            formatted, hit = _format_resolved_token(token, id_map)
            matched = matched or hit
            parts.append(formatted)
        joined = "\n".join(parts) if len(parts) > 3 else "、".join(parts)
        return joined, matched
    text = str(value or "").strip()
    if not text:
        return value, False
    tokens = _split_entity_names(text)
    formatted = []
    matched = False
    for token in tokens:
        item, hit = _format_resolved_token(token, id_map)
        matched = matched or hit
        formatted.append(item)
    if not matched:
        return value, False
    if len(formatted) > 3:
        return "\n".join(formatted), True
    return "、".join(formatted), True


def _split_entity_names(text: str) -> list[str]:
    raw = text.replace("\n", "、").replace(";", "、").replace("，", "、").replace(",", "、")
    return [part.strip() for part in raw.split("、") if part.strip()]


def _format_resolved_token(token: str, id_map: dict[str, tuple[str, str]]) -> tuple[str, bool]:
    cleaned = _normalize_entity_token(token)
    for marker in ("（", "("):
        idx = cleaned.find(marker)
        if idx > 0 and "id" in cleaned[idx:].lower():
            cleaned = cleaned[:idx].strip()
            break
    mapped = id_map.get(cleaned) or id_map.get(token.strip())
    if not mapped:
        return token, False
    id_key, id_value = mapped
    return f"{cleaned}（{id_key}: {id_value}）", True


def _unwrap_tool_payload(tool_output: Any) -> dict[str, Any] | None:
    if isinstance(tool_output, list):
        return {"records": tool_output}
    payload = _as_dict(tool_output)
    if payload is None:
        return None
    if isinstance(payload.get("records"), list) or isinstance(payload.get("items"), list):
        return payload
    for key in ("text", "output", "result", "content", "data"):
        nested = payload.get(key)
        if isinstance(nested, list):
            if nested and all(isinstance(item, dict) for item in nested):
                return {"records": nested}
            chunks = []
            for item in nested:
                if isinstance(item, dict):
                    chunks.append(str(item.get("text") or item.get("content") or ""))
                else:
                    chunks.append(str(item or ""))
            nested = "\n".join(chunk for chunk in chunks if chunk)
        if isinstance(nested, str):
            parsed = _parse_json_object(nested.strip())
        else:
            parsed = _as_dict(nested)
        if isinstance(parsed, dict) and (
            isinstance(parsed.get("records"), list) or isinstance(parsed.get("items"), list)
        ):
            return parsed
        if isinstance(parsed, list):
            return {"records": parsed}
    return None


def _merge_resolved_entities(previous: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    for source in (previous, incoming):
        for record in source.get("records") or []:
            if not isinstance(record, dict):
                continue
            name = str(record.get("name") or record.get("matchedName") or "").strip()
            key = name or f"{record.get('id_key')}:{record.get('id_value')}"
            if not key:
                continue
            merged[key] = record
    records = list(merged.values())
    return {
        "source_tool": incoming.get("source_tool") or previous.get("source_tool") or "",
        "total": len(records),
        "found": sum(1 for item in records if item.get("found")),
        "missing": sum(1 for item in records if not item.get("found")),
        "records": records,
    }


def _as_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        parsed = _parse_json_object(text)
        return parsed if isinstance(parsed, dict) else None
    return None


def _parse_json_object(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            start = text.find("[")
        if start < 0:
            return None
        try:
            parsed, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            return None
        return parsed


class HitlContinuationStore:
    KEY_PREFIX = "ai:hitl-continuation"
    DEFAULT_TTL_SECONDS = 21600

    def __init__(
        self,
        redis_client: Any = None,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        allow_memory_fallback: bool = True,
    ):
        self.redis_client = redis_client
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.allow_memory_fallback = allow_memory_fallback
        self._memory = _MEMORY_STORE

    @classmethod
    async def from_runtime(cls) -> "HitlContinuationStore":
        from app.core.redis import get_redis

        try:
            return cls(await get_redis(), allow_memory_fallback=True)
        except Exception:
            logger.warning("[HITL continuation] Redis unavailable, using process memory")
            return cls(None, allow_memory_fallback=True)

    @classmethod
    def _key(cls, user_id: str, conversation_id: str) -> str:
        return f"{cls.KEY_PREFIX}:{user_id}:{conversation_id}"

    async def get(
        self,
        *,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        uid, cid = self._identity(user_info=user_info, conversation_id=conversation_id, user_id=user_id)
        if not uid or not cid:
            return None
        record = await self._get(self._key(uid, cid))
        if not record:
            return None
        return copy.deepcopy(record)

    async def merge(
        self,
        *,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
        skills: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        original_user_query: str | None = None,
        fact_name: str | None = None,
        fact_payload: dict[str, Any] | None = None,
        todos: dict[str, Any] | None = None,
        replace_attachments: bool = False,
        replace_skills: bool = False,
        replace_original_query: bool = False,
        clear_facts: bool = False,
        clear_todos: bool = False,
    ) -> dict[str, Any] | None:
        uid, cid = self._identity(user_info=user_info, conversation_id=conversation_id, user_id=user_id)
        if not uid or not cid:
            return None
        key = self._key(uid, cid)
        current = await self._get(key) or empty_continuation()
        if skills is not None and replace_skills:
            current["skills"] = normalize_skills(skills)
        elif skills:
            merged = {item["id"]: item for item in normalize_skills(current.get("skills"))}
            for item in normalize_skills(skills):
                prev = merged.get(item["id"])
                if prev:
                    if (not item.get("name") or item["name"] == item["id"]) and prev.get("name"):
                        item["name"] = prev["name"]
                    if not item.get("scope") and prev.get("scope"):
                        item["scope"] = prev["scope"]
                merged[item["id"]] = item
            current["skills"] = list(merged.values())
        if attachments is not None and replace_attachments:
            current["attachments"] = [
                item for item in attachments if isinstance(item, dict) and str(item.get("path") or "").strip()
            ]
        elif attachments:
            seen = {str(item.get("path") or "") for item in current.get("attachments") or []}
            next_items = list(current.get("attachments") or [])
            for item in attachments:
                path = str((item or {}).get("path") or "").strip()
                if not path or path in seen:
                    continue
                seen.add(path)
                next_items.append(item)
            current["attachments"] = next_items
        query = str(original_user_query or "").strip()
        if query and (replace_original_query or not current.get("original_user_query")):
            current["original_user_query"] = query[:4000]
        if clear_facts:
            current["facts"] = {}
        if fact_name and fact_payload:
            facts = dict(current.get("facts") or {})
            name = str(fact_name)
            if name == _RESOLVED_ENTITIES_FACT and isinstance(facts.get(name), dict):
                facts[name] = _merge_resolved_entities(facts[name], fact_payload)
            else:
                facts[name] = fact_payload
            current["facts"] = facts
        if clear_todos:
            current["todos"] = None
        if todos is not None:
            current["todos"] = copy.deepcopy(todos)
        current["updated_at"] = int(time.time())
        await self._set(key, current)
        return copy.deepcopy(current)

    async def remember_turn_inputs(
        self,
        *,
        user_info: Any,
        conversation_id: str | None,
        user_query: str,
        messages: list[dict[str, Any]] | None,
        skills: list[dict[str, Any]] | None = None,
    ) -> None:
        if not conversation_id or should_restore_hitl_continuation(user_query):
            return
        if is_business_confirmation_receipt_message(user_query) or is_user_question_receipt_message(
            user_query
        ):
            return
        last_turn = last_user_turn_messages(messages)
        await self.merge(
            user_info=user_info,
            conversation_id=conversation_id,
            skills=skills if skills is not None else skills_from_messages(last_turn),
            attachments=attachments_from_messages(last_turn),
            original_user_query=user_query,
            replace_attachments=True,
            replace_skills=True,
            replace_original_query=True,
            clear_facts=True,
            clear_todos=True,
        )

    async def remember_skill(
        self,
        *,
        skill_id: str,
        skill_name: str = "",
        scope: str = "",
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        sid = str(skill_id or "").strip()
        if not sid or sid in _sticky_skill_exclude_ids():
            return
        await self.merge(
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
            skills=[{"id": sid, "name": skill_name or sid, "scope": scope}],
        )

    async def remember_resolve_tool(
        self,
        *,
        tool_name: str,
        tool_output: Any,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        fact = parse_resolve_tool_fact(tool_name, tool_output)
        if not fact:
            return
        await self.merge(
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
            fact_name=_RESOLVED_ENTITIES_FACT,
            fact_payload=fact,
        )

    async def remember_todos(
        self,
        *,
        todos: dict[str, Any],
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        await self.merge(
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
            todos=todos,
        )

    async def clear(
        self,
        *,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        uid, cid = self._identity(user_info=user_info, conversation_id=conversation_id, user_id=user_id)
        if not uid or not cid:
            return
        key = self._key(uid, cid)
        if self.redis_client is not None:
            try:
                await self.redis_client.delete(key)
            except Exception:
                logger.warning("[HITL continuation] Failed to delete Redis key", exc_info=True)
        self._memory.pop(key, None)

    def _identity(
        self,
        *,
        user_info: Any,
        conversation_id: str | None,
        user_id: str | None = None,
    ) -> tuple[str, str]:
        uid = str(user_id or "").strip()
        if not uid:
            uid = try_session_user_id(user_info) or ""
        if not uid:
            uid = try_session_user_id_from_agent_context(user_info) or ""
        cid = str(conversation_id or "").strip()
        if cid and not uid:
            logger.warning("[HITL continuation] missing session user id for conversation %s", cid)
        return uid, cid

    async def _get(self, key: str) -> dict[str, Any] | None:
        if self.redis_client is not None:
            try:
                raw = await self.redis_client.get(key)
                if raw:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        return parsed
            except Exception:
                logger.warning("[HITL continuation] Redis get failed", exc_info=True)
                if not self.allow_memory_fallback:
                    return None
        return copy.deepcopy(self._memory.get(key))

    async def _set(self, key: str, record: dict[str, Any]) -> None:
        payload = json.dumps(record, ensure_ascii=False)
        if self.redis_client is not None:
            try:
                await self.redis_client.set(key, payload, ex=self.ttl_seconds)
                return
            except Exception:
                logger.warning("[HITL continuation] Redis set failed", exc_info=True)
                if not self.allow_memory_fallback:
                    return
        self._memory[key] = copy.deepcopy(record)

    @staticmethod
    def clear_memory() -> None:
        _MEMORY_STORE.clear()
