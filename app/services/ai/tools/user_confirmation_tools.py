"""Platform tool: request user confirmation of business data fields."""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.ai.hitl_continuation import HitlContinuationUnavailableError
from app.services.ai.tools.tool_compat import BaseTool

logger = logging.getLogger(__name__)

ValueType = Literal["string", "number", "boolean", "text", "date", "datetime"]
_KNOWN_ARG_KEYS = frozenset(
    {
        "title",
        "fields",
        "summary",
        "confirm_label",
        "cancel_label",
        "risk_note",
    }
)


def schema_looks_like_request_user_confirmation(schema: Any) -> bool:
    """Identify the confirmation schema before AgentScope validates arguments."""
    if not isinstance(schema, dict):
        return False
    props = schema.get("properties")
    if not isinstance(props, dict):
        return False
    return "title" in props and "fields" in props and "confirm_label" in props


def _loads_maybe_repaired(raw: str) -> Any:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        from json_repair import repair_json

        return repair_json(text, return_objects=True)
    except Exception:
        return None


def _normalize_confirmation_args_dict(data: dict[str, Any]) -> dict[str, Any] | None:
    raw_fields = data.get("fields")
    if isinstance(raw_fields, str):
        raw_fields = _loads_maybe_repaired(raw_fields)
    if not isinstance(raw_fields, list) or not raw_fields:
        return None
    fields = [dict(item) for item in raw_fields if isinstance(item, dict)]
    if not fields or any(
        not str(item.get("key") or "").strip()
        or not str(item.get("label") or "").strip()
        for item in fields
    ):
        return None
    title = str(
        data.get("title")
        or data.get("header")
        or data.get("question")
        or "请确认以下信息"
    ).strip()
    payload = dict(data)
    payload["title"] = title or "请确认以下信息"
    payload["fields"] = fields
    return {key: value for key, value in payload.items() if key in _KNOWN_ARG_KEYS}


def coerce_request_user_confirmation_args(raw: Any) -> dict[str, Any] | None:
    """Best-effort normalization for common model confirmation payload mistakes."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return _normalize_confirmation_args_dict(raw)
    if isinstance(raw, list):
        return _normalize_confirmation_args_dict({"fields": raw})
    if not isinstance(raw, str):
        return None
    loaded = _loads_maybe_repaired(raw)
    if isinstance(loaded, dict):
        return _normalize_confirmation_args_dict(loaded)
    if isinstance(loaded, list):
        return _normalize_confirmation_args_dict({"fields": loaded})
    return None


def prepare_request_user_confirmation_tool_input(raw: Any) -> str | None:
    """Return an object JSON string that can pass AgentScope schema validation."""
    coerced = coerce_request_user_confirmation_args(raw)
    if coerced is None:
        return None
    return json.dumps(coerced, ensure_ascii=False)


class ConfirmationField(BaseModel):
    key: str = Field(description="字段稳定标识，回传时使用")
    label: str = Field(description="展示给用户的字段名")
    value: Any = Field(default="", description="当前字段值")
    editable: bool = Field(default=True, description="是否允许用户在确认卡中编辑")
    value_type: ValueType = Field(
        default="string",
        description="值类型：string/number/boolean/text/date/datetime；日历日期用 date（YYYY-MM-DD），含时刻用 datetime；空日期也要标 date/datetime",
    )

    @field_validator("key", "label")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("key/label 不能为空")
        return text


class RequestUserConfirmationArgs(BaseModel):
    title: str = Field(description="确认卡标题")
    fields: list[ConfirmationField] = Field(description="待确认字段列表，至少一项")
    summary: str = Field(default="", description="标题下的补充说明")
    confirm_label: str = Field(default="确定", description="确定按钮文案")
    cancel_label: str = Field(default="取消", description="取消按钮文案")
    risk_note: str = Field(default="", description="可选风险提示")

    @model_validator(mode="before")
    @classmethod
    def _coerce_model_payload(cls, value: Any) -> Any:
        coerced = coerce_request_user_confirmation_args(value)
        return coerced if coerced is not None else value

    @field_validator("title")
    @classmethod
    def _title_non_empty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("title 不能为空")
        return text

    @field_validator("fields")
    @classmethod
    def _fields_non_empty(cls, value: list[ConfirmationField]) -> list[ConfirmationField]:
        if not value:
            raise ValueError("fields 不能为空")
        return value


class RequestUserConfirmationTool(BaseTool):
    name = "request_user_confirmation"
    description = (
        "在录入/修改/删除业务数据前，向用户展示可编辑的业务确认卡。"
        "调用后返回 awaiting_user，必须停止并等待用户下一条消息："
        "若收到「【业务确认】用户已确定」则继续原任务：按快照与已启用技能/续跑上下文执行，"
        "禁止臆造外部主键；快照只有名称时先解析再写入。"
        "确认前已写入 pending_write/ 的待提交文件必须 Read 后原样提交；没有快照时先读取附件，禁止凭记忆编造标识、人员、数值或明细行。"
        "外部对象字段必须同时给出显示名称和已解析主键；批量写入须按对象写结构化说明，禁止一句通用模板。"
        "若收到「【业务确认】用户已取消」则立即终止本次流程，不得调用写入类工具，"
        "且禁止再次调用本工具重新弹确认卡——只能用文字确认已取消并询问用户；"
        "仅当用户随后明确提供新的/修改后的数据并要求继续时，才可再次调用本工具。"
        "本工具只展示确认信息，不会写入任何业务系统。"
        "入参必须是 JSON 对象：title 为标题，fields 为字段数组；禁止把 fields 数组直接作为整个入参。"
    )
    args_schema = RequestUserConfirmationArgs

    async def ainvoke(self, arguments: Any = None) -> str:
        from app.services.ai.business_confirmation import (
            cancel_gate_block_payload,
            is_cancel_confirmation_gate_armed,
            normalize_confirmation_field_types,
        )

        if is_cancel_confirmation_gate_armed():
            return json.dumps(cancel_gate_block_payload(), ensure_ascii=False)

        arguments = arguments or {}
        try:
            args = RequestUserConfirmationArgs.model_validate(arguments)
        except Exception as exc:
            return json.dumps(
                {
                    "status": "error",
                    "error": f"入参无效: {exc}",
                    "hint": "请提供非空 title，以及至少一项含 key/label 的 fields",
                },
                ensure_ascii=False,
            )

        confirmation_id = f"bc_{secrets.token_hex(8)}"
        fields = normalize_confirmation_field_types(
            [field.model_dump(mode="json") for field in args.fields]
        )
        try:
            from app.core.context import get_current_agent_context
            from app.services.ai.conversation_identity import try_session_user_id_from_agent_context
            from app.services.ai.hitl_continuation import (
                HitlContinuationCoordinator,
                enrich_confirmation_card,
            )

            agent_ctx = get_current_agent_context()
            conversation_id = str(getattr(agent_ctx, "conversation_id", "") or "").strip()
            user_id = try_session_user_id_from_agent_context(agent_ctx) if agent_ctx else None
            if conversation_id:
                coordinator = await HitlContinuationCoordinator.from_runtime()
                continuation = await coordinator.get(user_id=user_id, conversation_id=conversation_id)
                fields, risk_note = enrich_confirmation_card(
                    fields,
                    continuation,
                    risk_note=args.risk_note or "",
                )
                fields = normalize_confirmation_field_types(fields)
                args.risk_note = risk_note
        except HitlContinuationUnavailableError:
            raise
        except Exception:
            logger.warning(
                "[request_user_confirmation] Failed to enrich confirmation fields",
                exc_info=True,
            )
        ui = {
            "title": args.title,
            "summary": args.summary or "",
            "fields": fields,
            "confirm_label": args.confirm_label or "确定",
            "cancel_label": args.cancel_label or "取消",
            "risk_note": args.risk_note or "",
        }
        return json.dumps(
            {
                "status": "awaiting_user",
                "confirmation_id": confirmation_id,
                "message": "已向用户展示确认卡，请等待用户确定或取消后再继续。",
                "ui": ui,
            },
            ensure_ascii=False,
        )


request_user_confirmation = RequestUserConfirmationTool()
