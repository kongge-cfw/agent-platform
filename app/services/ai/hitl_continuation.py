"""HITL 确认卡 / 提问卡回执轮的续跑上下文（技能、附件、已解析主键、待写入快照、todo）。"""
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
_RESOLVE_OBSERVATION_OPTIONAL_KEYS = (
    ("enabled", "enabled"),
    ("matchCount", "matchCount"),
    ("match_count", "matchCount"),
)
_RESOLVED_ENTITIES_FACT = "resolved_entities"
_PENDING_WRITE_FACT = "pending_write"
_WRITE_TOOL_NAMES = frozenset({"write", "write_file"})
_PENDING_WRITE_DIR = "pending_write"
_MAX_PENDING_WRITE_ITEMS = 40
_WRITE_FAIL_MARKERS = (
    "错误：",
    "错误:",
    "失败：",
    "失败:",
    "写入文件失败",
    "文件访问被拒绝",
    "error:",
    "traceback",
    "permission denied",
)
_WRITE_FAIL_STATES = frozenset(
    {"error", "failed", "failure", "denied", "interrupted", "timeout", "timed_out"}
)
RESOLVED_ENTITIES_MARKER = "[已解析对象快照]"
# 纯数字，或数字加字段里自带的短后缀（最多 2 字，原样保留，不维护量词表）
_COUNT_VALUE_RE = re.compile(r"^(\d+)\s*([^\d\s、，,\n]{0,2})$")
_FALSEY_ENABLED = frozenset({"false", "0", "no", "off", "disabled"})

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



def advance_todo_snapshot_after_hitl_confirm(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """确认/提问回执后把当前项收尾，并启动紧邻的下一项。"""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("todos")
    if not isinstance(raw, list) or not raw:
        return None
    todos: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        status = str(item.get("status") or "").strip()
        if not content or status not in {"pending", "in_progress", "completed", "cancelled"}:
            continue
        todos.append({"content": content, "status": status})
    if not todos or not any(item["status"] in {"pending", "in_progress"} for item in todos):
        return None
    for item in todos:
        if item["status"] == "in_progress":
            item["status"] = "completed"
    for item in todos:
        if item["status"] == "pending":
            item["status"] = "in_progress"
            break
    counts = {
        "pending": sum(item["status"] == "pending" for item in todos),
        "in_progress": sum(item["status"] == "in_progress" for item in todos),
        "completed": sum(item["status"] == "completed" for item in todos),
        "cancelled": sum(item["status"] == "cancelled" for item in todos),
    }
    return {"todos": todos, "counts": counts}


def empty_continuation() -> dict[str, Any]:
    return {
        "skills": [],
        "attachments": [],
        "original_user_query": "",
        "facts": {},
        "todos": None,
        "updated_at": 0,
    }


def has_open_hitl_todos(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    raw = payload.get("todos")
    items = raw.get("todos") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("status") or "").strip() in {"pending", "in_progress"}
        for item in items
    )


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
        item = {
            "id": skill_id,
            "name": str(skill.get("name") or skill_id).strip() or skill_id,
            "scope": str(skill.get("scope") or "").strip(),
        }
        content_rev = str(skill.get("content_rev") or "").strip()
        if content_rev:
            item["content_rev"] = content_rev
        items.append(item)
    return items


def is_entity_resolve_tool(tool_name: str | None) -> bool:
    """解析类工具：名称含 resolve，但排除相对日期等平台内置工具。"""
    name = str(tool_name or "").lower()
    if "resolve" not in name:
        return False
    return not any(marker in name for marker in _NON_ENTITY_RESOLVE_MARKERS)


def is_write_tool(tool_name: str | None) -> bool:
    """会话工作区写入工具（AgentScope Write / 平台 write_file）。"""
    return str(tool_name or "").strip().lower() in _WRITE_TOOL_NAMES


def is_pending_write_path(path: str | None) -> bool:
    """确认前待提交正文的约定目录：路径中含 pending_write 段。"""
    parts = str(path or "").replace("\\", "/").strip().lower().split("/")
    return _PENDING_WRITE_DIR in [part for part in parts if part]


def parse_pending_write_item(
    tool_name: str | None,
    tool_args: Any,
    tool_output: Any = None,
    tool_result_state: Any = None,
) -> dict[str, str] | None:
    if not is_write_tool(tool_name):
        return None
    if _write_result_failed(tool_result_state) or _write_output_failed(tool_output):
        return None
    path = _write_path_from_args(tool_args)
    if not path or not is_pending_write_path(path):
        return None
    filename = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return {"path": path, "filename": filename or path}


def _write_path_from_args(tool_args: Any) -> str:
    if not isinstance(tool_args, dict):
        return ""
    for key in ("file_path", "path"):
        text = str(tool_args.get(key) or "").strip()
        if text:
            return text
    return ""


def _write_result_failed(tool_result_state: Any) -> bool:
    state = str(getattr(tool_result_state, "value", tool_result_state) or "").strip().lower()
    return state in _WRITE_FAIL_STATES


def _write_output_failed(tool_output: Any) -> bool:
    if tool_output is None:
        return False
    if isinstance(tool_output, dict):
        text = str(tool_output.get("raw") or tool_output.get("text") or tool_output or "").strip()
    else:
        text = str(tool_output or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return any(marker in text or marker in lowered for marker in _WRITE_FAIL_MARKERS)


def _pending_write_items(payload: dict[str, Any] | None) -> list[dict[str, str]]:
    facts = (payload or {}).get("facts") or {}
    current = facts.get(_PENDING_WRITE_FACT)
    items = current.get("items") if isinstance(current, dict) else None
    if not isinstance(items, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        filename = str(item.get("filename") or "").strip() or path.replace("\\", "/").rsplit("/", 1)[-1]
        result.append({"path": path, "filename": filename})
    return result


def _pending_write_prompt_lines(payload: dict[str, Any] | None) -> list[str]:
    items = _pending_write_items(payload)
    attachments = (payload or {}).get("attachments") or []
    lines = [
        "- 禁止凭记忆编造源材料中的标识、人员、数值或明细行；没有依据的字段省略或写「无」，不得用示例值填充。",
        "- 确认后优先提交确认前已生成的待写入快照，禁止重写其中的标识与数值。",
    ]
    if items:
        lines.append("- 确认前已生成的待写入文件（必须 Read 后原样提交，禁止凭记忆重写）：")
        for item in items[:_MAX_PENDING_WRITE_ITEMS]:
            filename = item["filename"]
            path = item["path"]
            lines.append(f"  - {filename}: {path}")
        return lines
    if any(isinstance(item, dict) and str(item.get("path") or "").strip() for item in attachments):
        lines.append(
            "- 当前没有待写入快照。写入前必须先读取上一轮附件或工具结果，禁止用记忆补全明细。"
        )
    return lines


def parse_resolve_tool_fact(tool_name: str | None, tool_output: Any) -> dict[str, Any] | None:
    if not is_entity_resolve_tool(tool_name):
        return None
    payload = _unwrap_tool_payload(tool_output)
    if not payload:
        return None
    records = _resolve_record_list(payload)
    if records is None:
        return None
    simplified: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        name = _resolve_record_name(record)
        id_key, id_value = _pick_record_id(record)
        found = bool(record.get("found", bool(id_value))) and bool(id_value)
        if not name and not id_value:
            continue
        if name:
            seen_names.add(name)
        item = {
            "name": name,
            "found": found,
            "id_key": id_key,
            "id_value": id_value if found else "",
            "matchedName": str(record.get("matchedName") or name).strip(),
        }
        _copy_resolve_status_fields(record, item)
        simplified.append(item)
    for name in payload.get("missing_names") or []:
        text = str(name or "").strip()
        if not text or text in seen_names:
            continue
        seen_names.add(text)
        simplified.append(
            {
                "name": text,
                "found": False,
                "id_key": "",
                "id_value": "",
                "matchedName": text,
            }
        )
    if not simplified:
        return None
    found_records_n = sum(1 for item in simplified if item["found"])
    claimed_n = _coerce_int(payload.get("found"), found_records_n)
    return {
        "source_tool": str(tool_name or ""),
        "total": payload.get("total", len(simplified)),
        "found": payload.get("found", found_records_n),
        "found_claimed": claimed_n,
        "found_records": found_records_n,
        "missing": payload.get("missing", sum(1 for item in simplified if not item["found"])),
        "integrity": "complete" if claimed_n == found_records_n else "incomplete",
        "records": simplified,
    }


def compact_resolve_tool_result_for_model(tool_name: str | None, tool_output: Any) -> str | None:
    """把解析名单收成可完整解析的短 JSON，禁止从中间切断 records。"""
    if not is_entity_resolve_tool(tool_name):
        return None
    payload = _unwrap_tool_payload(tool_output)
    if not payload:
        return None
    records = _resolve_record_list(payload)
    if records is None:
        return None

    found_records: list[dict[str, Any]] = []
    missing_records: list[dict[str, Any]] = []
    for record in records:
        slim = _slim_resolve_observation_record(record)
        if slim is None:
            continue
        if slim.get("found"):
            found_records.append(slim)
        else:
            missing_records.append(slim)
    if not found_records and not missing_records:
        return None

    compact = _build_resolve_observation(
        payload,
        found_records=found_records,
        missing_records=missing_records,
    )
    from app.services.ai.runtime.agentscope.stream_reconcile import DEFAULT_TOOL_OUTPUT_MAX_LEN

    text = json.dumps(compact, ensure_ascii=False, default=str)
    if len(text) <= DEFAULT_TOOL_OUTPUT_MAX_LEN or not missing_records:
        return text
    compact = _build_resolve_observation(
        payload,
        found_records=found_records,
        missing_records=[],
        missing_names=[
            str(item.get("name") or "").strip()
            for item in missing_records
            if str(item.get("name") or "").strip()
        ],
        missing_collapsed=True,
    )
    return json.dumps(compact, ensure_ascii=False, default=str)


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
    """兼容旧调用：只回写字段，风险提示请用 enrich_confirmation_card。"""
    next_fields, _ = enrich_confirmation_card(fields, continuation)
    return next_fields


def enrich_confirmation_card(
    fields: list[dict[str, Any]],
    continuation: dict[str, Any] | None,
    *,
    risk_note: str = "",
) -> tuple[list[dict[str, Any]], str]:
    """按完整解析快照回写名称名单和数量字段，不把主键写进名称字段。"""
    next_fields = [dict(field) for field in fields or []]
    note = str(risk_note or "").strip()
    fact = _resolve_fact_from_continuation(continuation)
    records = fact.get("records") if isinstance(fact, dict) else None
    if not isinstance(records, list) or not records:
        return next_fields, note

    eligible_names = _eligible_resolve_names(records)
    ineligible_names = _ineligible_resolve_names(records, eligible_names)
    snapshot_names = set(eligible_names) | set(ineligible_names)
    incomplete = str(fact.get("integrity") or "") == "incomplete"
    aligned_keys: set[str] = set()
    listed_count: int | None = None
    if not incomplete and eligible_names:
        for field in next_fields:
            if not _is_name_list_field(field):
                continue
            tokens = [
                _strip_id_annotation(_normalize_entity_token(token))
                for token in _split_entity_names(field.get("value"))
            ]
            tokens = [token for token in tokens if token]
            if not _is_snapshot_name_list(tokens, snapshot_names):
                continue
            listed_count = len(tokens)
            raw = str(field.get("value") or "")
            if "\n" in raw and "、" not in raw:
                field["value"] = "\n".join(eligible_names)
                field["value_type"] = "text"
            else:
                field["value"] = "、".join(eligible_names)
            aligned_keys.add(str(field.get("key") or ""))
        if listed_count is not None:
            for field in next_fields:
                if str(field.get("key") or "") in aligned_keys:
                    continue
                _sync_count_field(field, listed_count, len(eligible_names))

    if aligned_keys and ineligible_names:
        extra = (
            f"另有{len(ineligible_names)}个对象当前无法匹配或不可用："
            f"{'、'.join(ineligible_names[:40])}"
        )
        if extra not in note:
            note = f"{note} {extra}".strip() if note else extra
    return next_fields, note


def build_continuation_prompt_block(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    skills = normalize_skills(payload.get("skills"))
    attachments = payload.get("attachments") or []
    original = str(payload.get("original_user_query") or "").strip()
    facts = payload.get("facts") or {}
    fact = facts.get(_RESOLVED_ENTITIES_FACT) or facts.get("enterprise_resolve") or {}
    todos = payload.get("todos") if isinstance(payload.get("todos"), dict) else None
    pending_write = _pending_write_items(payload)
    if not skills and not attachments and not original and not fact and not todos and not pending_write:
        return ""

    lines = [
        HITL_CONTINUATION_MARKER,
        "本轮是确认卡/提问卡回执，不是新任务。必须继续上一轮原任务：",
        "- 若已启用技能，按该 SKILL.md 的 workflow 执行，不要跳过解析、校验或结构化说明。",
        "- 禁止臆造外部主键；快照只有名称时必须使用下方已解析 ID，或再次调用解析工具。",
        "- 需要附件内容时直接读取下列路径，不要声称文件不存在。",
    ]
    lines.extend(_pending_write_prompt_lines(payload))
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
    if isinstance(fact, dict) and str(fact.get("integrity") or "") == "incomplete":
        lines.append("- 已解析快照不完整，禁止按汇总数字写入，必须再次调用解析工具。")
    if isinstance(records, list) and records:
        lines.append("- 已解析对象主键（以工具返回为准，禁止改写 ID）：")
        found_lines: list[str] = []
        missing_lines: list[str] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            name = str(record.get("name") or "").strip()
            id_key, id_value = _record_id(record)
            if record.get("found") and id_value:
                found_lines.append(f"  - {name} → {id_key}={id_value}")
            elif name:
                missing_lines.append(f"  - {name} → 未解析到主键，不得写入")
        lines.extend(found_lines)
        lines.extend(missing_lines[:40])
    if todos and isinstance(todos.get("todos"), list) and todos.get("todos"):
        lines.append(
            "- 当前任务清单（回执后已推进，请按此状态继续更新；"
            "不要把已完成项改回进行中，也不要无故整表重开）："
        )
        for item in todos.get("todos")[:20]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            status = str(item.get("status") or "").strip()
            if content and status:
                lines.append(f"  - [{status}] {content}")
    return "\n".join(lines)


def build_resolved_entities_prompt_block(payload: dict[str, Any] | None) -> str:
    """非回执轮：只注入已解析对象快照，不当成确认卡回执。"""
    if not isinstance(payload, dict):
        return ""
    facts = payload.get("facts") or {}
    fact = facts.get(_RESOLVED_ENTITIES_FACT) or facts.get("enterprise_resolve") or {}
    records = fact.get("records") if isinstance(fact, dict) else None
    if not isinstance(records, list) or not records:
        return ""
    lines = [
        RESOLVED_ENTITIES_MARKER,
        "以下对象已由解析工具返回。仅当本轮仍处理同一批对象时使用；禁止改写 ID，禁止臆造未列出的主键。",
    ]
    if str(fact.get("integrity") or "") == "incomplete":
        lines.append(
            "- 快照不完整（汇总条数与名单不一致），禁止按汇总数字出卡或写入，必须再次调用解析工具。"
        )
    found_lines: list[str] = []
    missing_lines: list[str] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name") or "").strip()
        id_key, id_value = _record_id(record)
        if record.get("found") and id_value:
            found_lines.append(f"  - {name} → {id_key}={id_value}")
        elif name:
            missing_lines.append(f"  - {name} → 未解析到主键，不得写入")
    if found_lines:
        lines.append("- 已解析对象主键（以工具返回为准）：")
        lines.extend(found_lines)
    if missing_lines:
        lines.append("- 未匹配对象：")
        lines.extend(missing_lines[:40])
    lines.extend(_pending_write_prompt_lines(payload))
    return "\n".join(lines)


def _resolve_record_list(payload: dict[str, Any]) -> list[Any] | None:
    records = payload.get("records")
    if isinstance(records, list):
        return records
    items = payload.get("items")
    if isinstance(items, list):
        return items
    return None


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _copy_resolve_status_fields(source: dict[str, Any], target: dict[str, Any]) -> None:
    for source_key, target_key in _RESOLVE_OBSERVATION_OPTIONAL_KEYS:
        if source_key in source and target_key not in target:
            target[target_key] = source.get(source_key)


def _resolve_fact_from_continuation(payload: dict[str, Any] | None) -> dict[str, Any]:
    facts = (payload or {}).get("facts") or {}
    current = facts.get(_RESOLVED_ENTITIES_FACT)
    if isinstance(current, dict):
        return current
    legacy = facts.get("enterprise_resolve")
    return legacy if isinstance(legacy, dict) else {}


def _is_truthy_enabled(value: Any) -> bool:
    if value is False or value == 0:
        return False
    text = str(value or "").strip().lower()
    return text not in _FALSEY_ENABLED


def _is_eligible_resolve_record(record: dict[str, Any]) -> bool:
    if not record.get("found"):
        return False
    _, id_value = _record_id(record)
    if not id_value:
        return False
    if "enabled" in record and not _is_truthy_enabled(record.get("enabled")):
        return False
    if "matchCount" in record or "match_count" in record:
        raw = record.get("matchCount", record.get("match_count"))
        try:
            if int(raw) != 1:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _eligible_resolve_names(records: list[Any]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not _is_eligible_resolve_record(record):
            continue
        name = str(record.get("name") or record.get("matchedName") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _ineligible_resolve_names(records: list[Any], eligible_names: list[str]) -> list[str]:
    eligible = set(eligible_names)
    names: list[str] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        name = str(record.get("name") or record.get("matchedName") or "").strip()
        if not name or name in eligible or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def _is_name_list_field(field: dict[str, Any]) -> bool:
    value_type = str(field.get("value_type") or "string")
    return value_type not in {"boolean", "number", "date", "datetime", "enum", "select"}


def _is_snapshot_name_list(tokens: list[str], snapshot_names: set[str]) -> bool:
    """整段都必须是快照里的对象名，避免长文本里偶然出现一个名称就被整段替换。"""
    if not tokens or not snapshot_names:
        return False
    return all(token in snapshot_names for token in tokens)


def _sync_count_field(field: dict[str, Any], listed_count: int, eligible_count: int) -> None:
    value_type = str(field.get("value_type") or "string")
    value = field.get("value")
    if value_type == "number":
        try:
            if int(value) == listed_count:
                field["value"] = eligible_count
        except (TypeError, ValueError):
            return
        return
    text = str(value or "").strip()
    matched = _COUNT_VALUE_RE.fullmatch(text)
    if not matched or int(matched.group(1)) != listed_count:
        return
    field["value"] = f"{eligible_count}{matched.group(2) or ''}"


def _resolve_record_name(record: dict[str, Any]) -> str:
    for key in _RECORD_NAME_KEYS:
        name = str(record.get(key) or "").strip()
        if name:
            return name
    return ""


def _slim_resolve_observation_record(record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    name = _resolve_record_name(record)
    id_key, id_value = _pick_record_id(record)
    found = bool(record.get("found", bool(id_value))) and bool(id_value)
    if not name and not id_value:
        return None
    item: dict[str, Any] = {"name": name, "found": found}
    matched = str(record.get("matchedName") or "").strip()
    if matched and matched != name:
        item["matchedName"] = matched
    for source_key, target_key in _RESOLVE_OBSERVATION_OPTIONAL_KEYS:
        if source_key in record and target_key not in item:
            item[target_key] = record.get(source_key)
    if found and id_value:
        item[id_key or "id"] = id_value
    return item


def _build_resolve_observation(
    payload: dict[str, Any],
    *,
    found_records: list[dict[str, Any]],
    missing_records: list[dict[str, Any]],
    missing_names: list[str] | None = None,
    missing_collapsed: bool = False,
) -> dict[str, Any]:
    records = list(found_records) + list(missing_records)
    found_records_n = len(found_records)
    claimed_n = _coerce_int(payload.get("found"), found_records_n)
    integrity = "complete" if claimed_n == found_records_n else "incomplete"
    compact: dict[str, Any] = {
        "total": payload.get("total", len(records) + len(missing_names or [])),
        "found": payload.get("found", found_records_n),
        "found_claimed": claimed_n,
        "found_records": found_records_n,
        "missing": payload.get("missing", len(missing_names or missing_records)),
        "integrity": integrity,
        "records": records,
        "record_count": len(records),
    }
    if integrity == "incomplete":
        compact["integrity_note"] = (
            "解析汇总与名单条数不一致，禁止按汇总数字出卡；请用同一批名称再次调用解析工具。"
        )
    if missing_collapsed:
        compact["missing_collapsed"] = True
        compact["missing_names"] = list(missing_names or [])
    return compact


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


def _strip_id_annotation(token: str) -> str:
    cleaned = str(token or "").strip()
    for marker in ("（", "("):
        idx = cleaned.find(marker)
        if idx > 0 and "id" in cleaned[idx:].lower():
            return cleaned[:idx].strip()
    return cleaned


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
    cleaned = _strip_id_annotation(_normalize_entity_token(token))
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
    found_records_n = sum(1 for item in records if item.get("found"))
    claimed_n = _coerce_int(incoming.get("found_claimed", incoming.get("found")), found_records_n)
    return {
        "source_tool": incoming.get("source_tool") or previous.get("source_tool") or "",
        "total": len(records),
        "found": incoming.get("found", previous.get("found", found_records_n)),
        "found_claimed": claimed_n,
        "found_records": found_records_n,
        "missing": sum(1 for item in records if not item.get("found")),
        "integrity": "complete" if claimed_n == found_records_n else "incomplete",
        "records": records,
    }


def _merge_pending_write(previous: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    by_path: dict[str, dict[str, str]] = {}
    order: list[str] = []
    for source in (previous, incoming):
        items = source.get("items") if isinstance(source, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            filename = str(item.get("filename") or "").strip() or path.replace("\\", "/").rsplit("/", 1)[-1]
            entry = {"path": path, "filename": filename or path}
            if path not in by_path:
                order.append(path)
            by_path[path] = entry
    return {"items": [by_path[path] for path in order[-_MAX_PENDING_WRITE_ITEMS:]]}


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


class HitlContinuationUnavailableError(RuntimeError):
    """Raised when durable HITL state is required but Redis is unavailable."""


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
        from app.core.config import get_settings
        from app.core.redis import get_redis

        is_production = (
            str(get_settings().API_SERVICE_ENV or "").strip().lower() == "prod"
        )
        try:
            redis_client = await get_redis()
            if redis_client is None and is_production:
                raise HitlContinuationUnavailableError(
                    "生产环境 Redis 不可用，无法保存 HITL 续跑状态"
                )
            return cls(
                redis_client,
                allow_memory_fallback=not is_production,
            )
        except Exception as exc:
            if is_production:
                if isinstance(exc, HitlContinuationUnavailableError):
                    raise
                raise HitlContinuationUnavailableError(
                    "生产环境 Redis 不可用，无法安全恢复 HITL 会话"
                ) from exc
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
                    if not item.get("content_rev") and prev.get("content_rev"):
                        item["content_rev"] = prev["content_rev"]
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
            elif name == _PENDING_WRITE_FACT and isinstance(facts.get(name), dict):
                facts[name] = _merge_pending_write(facts[name], fact_payload)
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
        uid, cid = self._identity(user_info=user_info, conversation_id=conversation_id)
        current = await self._get(self._key(uid, cid)) if uid and cid else None
        keep_task = has_open_hitl_todos(current)
        await self.merge(
            user_info=user_info,
            conversation_id=conversation_id,
            skills=skills if skills is not None else (None if keep_task else skills_from_messages(last_turn)),
            attachments=None if keep_task else attachments_from_messages(last_turn),
            original_user_query=None if keep_task else user_query,
            replace_attachments=not keep_task,
            replace_skills=not keep_task,
            replace_original_query=not keep_task,
            clear_facts=not keep_task,
            clear_todos=not keep_task,
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
        resolved_user = user_info
        if resolved_user is None and user_id:
            resolved_user = {"user_id": user_id}
        from app.services.ai.skill_revision import current_skill_revision

        content_rev = current_skill_revision(
            sid,
            scope=str(scope or "").strip() or None,
            user_info=resolved_user,
        )
        skill_item = {"id": sid, "name": skill_name or sid, "scope": scope}
        if content_rev:
            skill_item["content_rev"] = content_rev
        await self.merge(
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
            skills=[skill_item],
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

    async def remember_write_tool(
        self,
        *,
        tool_name: str,
        tool_args: Any,
        tool_output: Any = None,
        tool_result_state: Any = None,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        item = parse_pending_write_item(
            tool_name,
            tool_args,
            tool_output,
            tool_result_state=tool_result_state,
        )
        if not item:
            return
        await self.merge(
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
            fact_name=_PENDING_WRITE_FACT,
            fact_payload={"items": [item]},
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
                if not self.allow_memory_fallback:
                    raise HitlContinuationUnavailableError(
                        "HITL continuation Redis delete failed"
                    )
        elif not self.allow_memory_fallback:
            raise HitlContinuationUnavailableError(
                "HITL continuation Redis client unavailable"
            )
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
                    raise HitlContinuationUnavailableError(
                        "HITL continuation Redis read failed"
                    )
        elif not self.allow_memory_fallback:
            raise HitlContinuationUnavailableError(
                "HITL continuation Redis client unavailable"
            )
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
                    raise HitlContinuationUnavailableError(
                        "HITL continuation Redis write failed"
                    )
        elif not self.allow_memory_fallback:
            raise HitlContinuationUnavailableError(
                "HITL continuation Redis client unavailable"
            )
        self._memory[key] = copy.deepcopy(record)

    @staticmethod
    def clear_memory() -> None:
        _MEMORY_STORE.clear()


class HitlContinuationCoordinator:
    """HITL 续跑状态门面；业务调用方不直接依赖底层存储实现。"""

    def __init__(self, store: HitlContinuationStore):
        self._store = store

    @classmethod
    async def from_runtime(cls) -> "HitlContinuationCoordinator":
        return cls(await HitlContinuationStore.from_runtime())

    async def get(
        self,
        *,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        return await self._store.get(
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    async def remember_turn_inputs(
        self,
        *,
        user_info: Any,
        conversation_id: str | None,
        user_query: str,
        messages: list[dict[str, Any]] | None,
        skills: list[dict[str, Any]] | None = None,
    ) -> None:
        await self._store.remember_turn_inputs(
            user_info=user_info,
            conversation_id=conversation_id,
            user_query=user_query,
            messages=messages,
            skills=skills,
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
        await self._store.remember_skill(
            skill_id=skill_id,
            skill_name=skill_name,
            scope=scope,
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
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
        await self._store.remember_resolve_tool(
            tool_name=tool_name,
            tool_output=tool_output,
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    async def remember_write_tool(
        self,
        *,
        tool_name: str,
        tool_args: Any = None,
        tool_output: Any = None,
        tool_result_state: Any = None,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        await self._store.remember_write_tool(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_output=tool_output,
            tool_result_state=tool_result_state,
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    async def remember_todos(
        self,
        *,
        todos: dict[str, Any],
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        await self._store.remember_todos(
            todos=todos,
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    async def clear_todos(
        self,
        *,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        await self._store.merge(
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
            clear_todos=True,
        )

    async def clear(
        self,
        *,
        user_info: Any = None,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        await self._store.clear(
            user_info=user_info,
            conversation_id=conversation_id,
            user_id=user_id,
        )
