"""Platform tool for AI-initiated clarification questions."""
from __future__ import annotations

import json
import re
import secrets
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.ai.tools.tool_compat import BaseTool

_QUESTION_MAX_LEN = 500
_CONTEXT_MAX_LEN = 1000
_OPTION_LABEL_MAX_LEN = 200
_MIN_OPTIONS = 2
_MAX_OPTIONS = 12
_KNOWN_ARG_KEYS = frozenset(
    {
        "question",
        "options",
        "is_multi_select",
        "allow_custom_input",
        "context",
        "purpose",
    }
)
_CONTEXT_MARKER_RE = re.compile(
    r"""(?:
        ["']?context["']?\s*>\s*
        | <parameter\s+name=["']context["']\s*>
        | ["']context["']\s*:\s*
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_XML_CLOSE_RE = re.compile(r"</(?:parameter|context)\s*>.*", re.IGNORECASE | re.DOTALL)


def schema_looks_like_ask_user_question(schema: Any) -> bool:
    """Identify this tool's JSON Schema without relying on the function name."""
    if not isinstance(schema, dict):
        return False
    props = schema.get("properties")
    if not isinstance(props, dict):
        return False
    return "question" in props and "options" in props and "allow_custom_input" in props


def _truncate(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def _extract_json_array(text: str) -> tuple[list[Any] | None, str]:
    start = text.find("[")
    if start < 0:
        return None, text
    depth = 0
    in_str = False
    escape = False
    quote = ""
    for index, char in enumerate(text[start:], start):
        if in_str:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                in_str = False
            continue
        if char in "\"'":
            in_str = True
            quote = char
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                blob = text[start : index + 1]
                parsed = _loads_maybe_repaired(blob)
                if isinstance(parsed, list):
                    return parsed, text[index + 1 :]
                return None, text
    return None, text


def _loads_maybe_repaired(text: str) -> Any:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    try:
        from json_repair import repair_json

        return repair_json(stripped, return_objects=True)
    except Exception:
        return None


def _extract_context(text: str | None) -> str | None:
    if not text:
        return None
    payload = str(text).strip().lstrip(",").strip()
    if not payload:
        return None
    match = _CONTEXT_MARKER_RE.search(payload)
    if match:
        payload = payload[match.end() :]
    payload = _XML_CLOSE_RE.sub("", payload).strip()
    if payload.startswith(("'", '"')) and payload.endswith(("'", '"')) and len(payload) >= 2:
        payload = payload[1:-1].strip()
    return payload or None


def _normalize_option(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    option_id = str(
        item.get("id") or item.get("value") or item.get("key") or ""
    ).strip()
    label = str(
        item.get("label") or item.get("name") or item.get("title") or option_id
    ).strip()
    if not option_id or not label:
        return None
    option: dict[str, str] = {
        "id": option_id[:100],
        "label": _truncate(label, _OPTION_LABEL_MAX_LEN),
    }
    description = item.get("description") or item.get("desc") or item.get("hint")
    if description:
        option["description"] = _truncate(str(description), 500)
    return option


def _dedupe_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for option in options:
        option_id = option["id"]
        suffix = 2
        while option_id in seen:
            option_id = f"{option['id']}_{suffix}"
            suffix += 1
        option = dict(option)
        option["id"] = option_id
        seen.add(option_id)
        unique.append(option)
        if len(unique) >= _MAX_OPTIONS:
            break
    return unique


def _from_options_list(
    options: list[Any],
    *,
    context: str | None = None,
    question: str | None = None,
    synthesized: bool = False,
) -> dict[str, Any] | None:
    normalized = [item for item in (_normalize_option(raw) for raw in options) if item]
    normalized = _dedupe_options(normalized)
    if len(normalized) < _MIN_OPTIONS:
        return None
    labels = [item["label"] for item in normalized if item.get("label")]
    payload: dict[str, Any] = {
        "question": _truncate(
            question or ("请确认以下任务参数" if synthesized else "、".join(labels[:6])),
            _QUESTION_MAX_LEN,
        ),
        "options": normalized,
    }
    if synthesized:
        payload["is_multi_select"] = True
        payload["allow_custom_input"] = True
    if context:
        payload["context"] = _truncate(context, _CONTEXT_MAX_LEN)
    return payload


def _unwrap_questions_alias(data: dict[str, Any]) -> dict[str, Any]:
    if "options" in data or "questions" not in data:
        return data
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        return data
    first = questions[0]
    if isinstance(first, dict) and isinstance(first.get("options"), list):
        data = dict(data)
        data.setdefault(
            "question",
            first.get("question") or first.get("header") or first.get("prompt") or first.get("label"),
        )
        data["options"] = first["options"]
        if first.get("multiSelect") or first.get("is_multi_select"):
            data.setdefault("is_multi_select", True)
        return data
    if all(isinstance(item, dict) and (item.get("id") or item.get("label")) for item in questions):
        data = dict(data)
        data["options"] = questions
        return data
    return data


def _normalize_ask_user_question_dict(data: dict[str, Any]) -> dict[str, Any] | None:
    data = _unwrap_questions_alias(dict(data))
    raw_options = data.get("options")
    if isinstance(raw_options, str):
        parsed = _loads_maybe_repaired(raw_options)
        if isinstance(parsed, list):
            raw_options = parsed
        else:
            extracted, _ = _extract_json_array(raw_options)
            raw_options = extracted
    if not isinstance(raw_options, list):
        return None
    question = data.get("question") or data.get("header") or data.get("prompt")
    synthesized = not str(question or "").strip()
    payload = _from_options_list(
        raw_options,
        context=data.get("context") if isinstance(data.get("context"), str) else None,
        question=str(question).strip() if question else None,
        synthesized=synthesized,
    )
    if payload is None:
        return None
    if "is_multi_select" in data and "is_multi_select" not in payload:
        payload["is_multi_select"] = bool(data.get("is_multi_select"))
    if "allow_custom_input" in data:
        payload["allow_custom_input"] = bool(data.get("allow_custom_input"))
    purpose = data.get("purpose")
    if isinstance(purpose, str) and purpose.strip():
        payload["purpose"] = purpose.strip()[:100]
    return {key: value for key, value in payload.items() if key in _KNOWN_ARG_KEYS}


def coerce_ask_user_question_args(raw: Any) -> dict[str, Any] | None:
    """Best-effort rewrite of model tool arguments into `{question, options, ...}`.

    Qwen and similar models often emit an options array plus XML residue such as
    `"context">...` instead of a JSON object. Returns None when at least two
    options cannot be recovered.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return _normalize_ask_user_question_dict(raw)
    if isinstance(raw, list):
        return _from_options_list(raw, synthesized=True)
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        loaded = None
    if isinstance(loaded, dict):
        return _normalize_ask_user_question_dict(loaded)
    if isinstance(loaded, list):
        return _from_options_list(
            loaded,
            context=_extract_context(stripped),
            synthesized=True,
        )
    options, tail = _extract_json_array(stripped)
    if options:
        return _from_options_list(
            options,
            context=_extract_context(tail) or _extract_context(stripped),
            synthesized=True,
        )
    repaired = _loads_maybe_repaired(stripped)
    if isinstance(repaired, dict):
        return _normalize_ask_user_question_dict(repaired)
    if isinstance(repaired, list):
        return _from_options_list(repaired, synthesized=True)
    return None


def prepare_ask_user_question_tool_input(raw: Any) -> str | None:
    """Return a JSON object string AgentScope can parse, or None if unrecoverable."""
    coerced = coerce_ask_user_question_args(raw)
    if coerced is None:
        return None
    return json.dumps(coerced, ensure_ascii=False)


class QuestionOption(BaseModel):
    id: str = Field(description="选项稳定标识，回传时使用")
    label: str = Field(description="展示给用户的选项名称")
    description: str | None = Field(default=None, description="选项补充说明")

    @field_validator("id", "label")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("选项 id/label 不能为空")
        return text


class AskUserQuestionArgs(BaseModel):
    question: str = Field(description="向用户提出的核心问题")
    options: list[QuestionOption] = Field(description="供用户选择的选项列表，至少两项")
    is_multi_select: bool = Field(default=False, description="是否支持多选")
    allow_custom_input: bool = Field(default=True, description="是否允许用户补充说明")
    context: str | None = Field(default=None, description="问题背景说明")
    purpose: str | None = Field(default=None, description="受控恢复用途标识，普通提问无需填写")

    @model_validator(mode="before")
    @classmethod
    def _coerce_model_payload(cls, value: Any) -> Any:
        coerced = coerce_ask_user_question_args(value)
        return coerced if coerced is not None else value

    @field_validator("question")
    @classmethod
    def _question_non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("question 不能为空")
        return _truncate(text, _QUESTION_MAX_LEN)

    @field_validator("options")
    @classmethod
    def _options_valid(cls, value: list[QuestionOption]) -> list[QuestionOption]:
        if len(value) < 2:
            raise ValueError("options 至少需要两项")
        if len(value) > 12:
            raise ValueError("options 不能超过 12 项")
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("options 的 id 必须唯一")
        if any(len(item.label) > 200 for item in value):
            raise ValueError("选项 label 不能超过 200 个字符")
        return value

    @field_validator("context")
    @classmethod
    def _context_limited(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = _truncate(str(value), _CONTEXT_MAX_LEN)
        return text or None

    @field_validator("purpose")
    @classmethod
    def _purpose_limited(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if len(text) > 100:
            raise ValueError("purpose 不能超过 100 个字符")
        return text or None


class AskUserQuestionTool(BaseTool):
    name = "ask_user_question"
    description = (
        "当用户明确要求互动式提问（如‘随便问我几个问题’、‘考考我’、‘请逐个问我’），"
        "或缺少会实质改变结果的条件、存在多个同等合理的执行分支时，主动向用户提问。"
        "‘列出几个问题’属于文字生成，不等同于‘问我几个问题’。"
        "支持单选、多选和补充输入；调用后必须停止当前执行并等待【用户回答】回执。"
        "能够依据上下文安全推断时不要重复提问；每轮最多提出一个问题。"
        "用户回答后若原任务仍缺输入，下一轮必须再调用本工具出下一张卡，禁止改用纯文字罗列待确认项。"
        "入参必须是 JSON 对象：question 一个问题，options 为 2-12 项（每项含 id 与 label）；"
        "禁止把选项数组、questions 列表或 XML 参数片段当作整个入参，背景说明写入 context。"
    )
    args_schema = AskUserQuestionArgs

    async def ainvoke(self, arguments: dict[str, Any] | None = None) -> str:
        try:
            args = AskUserQuestionArgs.model_validate(arguments or {})
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"入参无效: {exc}",
                    "hint": "请提供非空 question，以及至少两项 id 唯一的 options",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "awaiting_user",
                "interaction_type": "question",
                "question_id": f"uq_{secrets.token_hex(8)}",
                "message": "已向用户展示提问卡，请等待用户回答后再继续执行。",
                "question": args.question,
                "options": [option.model_dump(mode="json") for option in args.options],
                "is_multi_select": args.is_multi_select,
                "allow_custom_input": args.allow_custom_input,
                "context": args.context or "",
                "purpose": args.purpose or "",
            },
            ensure_ascii=False,
        )


ask_user_question = AskUserQuestionTool()
