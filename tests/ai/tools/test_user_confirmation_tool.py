"""Tests for request_user_confirmation business data confirmation tool."""
from __future__ import annotations

import json

import pytest

from app.services.ai.business_confirmation import (
    BUSINESS_CONFIRMATION_TOOL_NAME,
    build_business_confirmation_sse,
    parse_confirmation_tool_output,
)
from app.services.ai.tools.registry import ToolRegistry
from app.services.ai.tools.user_confirmation_tools import request_user_confirmation


pytestmark = pytest.mark.no_infrastructure


def test_request_user_confirmation_is_implicit_read_only():
    tool_names = {getattr(tool, "name", "") for tool in ToolRegistry.get_system_implicit_tools()}
    assert BUSINESS_CONFIRMATION_TOOL_NAME in tool_names
    assert ToolRegistry._registry[BUSINESS_CONFIRMATION_TOOL_NAME] is request_user_confirmation

    from app.services.ai.runtime.agentscope.tools import runtime_tool_spec_from_legacy_tool

    spec = runtime_tool_spec_from_legacy_tool(request_user_confirmation, source_type="system")
    assert spec.permission_scope == "read"
    assert spec.is_read_only is True


@pytest.mark.asyncio
async def test_request_user_confirmation_returns_awaiting_user_ui_payload():
    result = await request_user_confirmation.ainvoke(
        {
            "title": "请确认供应商信息",
            "summary": "确认后录入 ITAM",
            "fields": [
                {
                    "key": "supplier_name",
                    "label": "供应商名称",
                    "value": "北京神马科技有限公司",
                    "editable": True,
                    "value_type": "string",
                }
            ],
            "confirm_label": "确定",
            "cancel_label": "取消",
            "risk_note": "请核对原文",
        }
    )
    payload = json.loads(result)
    assert payload["status"] == "awaiting_user"
    assert payload["confirmation_id"].startswith("bc_")
    assert payload["ui"]["title"] == "请确认供应商信息"
    assert payload["ui"]["fields"][0]["key"] == "supplier_name"
    assert payload["ui"]["fields"][0]["value"] == "北京神马科技有限公司"
    assert payload["ui"]["confirm_label"] == "确定"
    assert payload["ui"]["risk_note"] == "请核对原文"


@pytest.mark.asyncio
async def test_request_user_confirmation_rejects_empty_fields():
    result = await request_user_confirmation.ainvoke({"title": "x", "fields": []})
    assert "fields" in result.lower() or "字段" in result


@pytest.mark.asyncio
async def test_request_user_confirmation_repairs_top_level_fields_array():
    result = await request_user_confirmation.ainvoke(
        [
            {
                "key": "task_name",
                "label": "任务名称",
                "value": "疲劳驾驶问题整改",
                "editable": True,
                "value_type": "string",
            },
            {
                "key": "deadline",
                "label": "完成时限",
                "value": "2026-09-26",
                "editable": True,
                "value_type": "date",
            },
        ]
    )

    payload = json.loads(result)
    assert payload["status"] == "awaiting_user"
    assert payload["ui"]["title"] == "请确认以下信息"
    assert [field["key"] for field in payload["ui"]["fields"]] == [
        "task_name",
        "deadline",
    ]


def test_agentscope_jsonschema_accepts_repaired_confirmation_array():
    import jsonschema

    from agentscope.agent import _agent as agent_mod
    from app.services.ai.runtime.agentscope.tools import (
        install_interactive_tool_input_repair,
    )
    from app.services.ai.tools.user_confirmation_tools import (
        RequestUserConfirmationArgs,
    )

    install_interactive_tool_input_repair()
    raw = json.dumps(
        [{"key": "deadline", "label": "完成时限", "value": "2026-09-26"}],
        ensure_ascii=False,
    )
    schema = RequestUserConfirmationArgs.model_json_schema()
    parsed = agent_mod._json_loads_with_repair(raw, schema)
    jsonschema.validate(parsed, schema)
    assert parsed["title"] == "请确认以下信息"
    assert parsed["fields"][0]["key"] == "deadline"


def test_build_business_confirmation_sse_from_tool_output():
    raw = json.dumps(
        {
            "status": "awaiting_user",
            "confirmation_id": "bc_test",
            "message": "等待用户确认",
            "ui": {
                "title": "确认",
                "summary": "摘要",
                "fields": [{"key": "a", "label": "A", "value": "1", "editable": True, "value_type": "string"}],
                "confirm_label": "确定",
                "cancel_label": "取消",
                "risk_note": "",
            },
        },
        ensure_ascii=False,
    )
    assert parse_confirmation_tool_output(raw)["confirmation_id"] == "bc_test"
    event = build_business_confirmation_sse(
        tool_name=BUSINESS_CONFIRMATION_TOOL_NAME,
        tool_output=raw,
        tool_call_id="call_1",
    )
    assert event is not None
    assert event["type"] == "business_confirmation"
    assert event["confirmation_id"] == "bc_test"
    assert event["tool_call_id"] == "call_1"
    assert event["title"] == "确认"
    assert event["fields"][0]["key"] == "a"


def test_build_business_confirmation_sse_ignores_other_tools():
    assert (
        build_business_confirmation_sse(
            tool_name="get_myinfo",
            tool_output="{}",
            tool_call_id="x",
        )
        is None
    )


def test_build_user_confirmation_message_format():
    from app.services.ai.business_confirmation import build_user_confirmation_message

    text = build_user_confirmation_message(
        confirmed=True,
        confirmation_id="bc_abc",
        fields=[{"key": "name", "label": "名称", "value": "测试"}],
    )
    assert "【业务确认】用户已确定" in text
    assert "confirmation_id: bc_abc" in text
    assert "名称 (name): 测试" in text


def test_cancel_message_forbids_reopening_confirmation_card():
    from app.services.ai.business_confirmation import build_user_confirmation_message
    from app.services.ai.agent_prompts import AgentServicePrompts

    text = build_user_confirmation_message(
        confirmed=False,
        confirmation_id="bc_cancel",
        fields=[{"key": "name", "label": "名称", "value": "测试"}],
    )
    assert "禁止再次调用 request_user_confirmation" in text
    assert "不要重新弹确认卡" in text
    section = AgentServicePrompts._PLATFORM_BUSINESS_CONFIRMATION_SECTION
    assert "禁止再次调用 request_user_confirmation" in section
    assert "不得重新弹确认卡" in section
    assert "禁止再输出任何 `quick:` 链接" in section or "禁止再输出任何 quick" in section
    assert "确认/取消只走确认卡按钮" in section


@pytest.mark.asyncio
async def test_cancel_gate_hard_blocks_tool_and_sse():
    from app.services.ai.business_confirmation import (
        arm_cancel_confirmation_gate,
        build_business_confirmation_sse,
    )

    arm_cancel_confirmation_gate("【业务确认】用户已取消\nconfirmation_id: bc_x")
    blocked = await request_user_confirmation.ainvoke(
        {
            "title": "不应出卡",
            "fields": [{"key": "a", "label": "A", "value": "1"}],
        }
    )
    payload = json.loads(blocked)
    assert payload["status"] == "error"
    assert payload["error"] == "business_confirmation_cancelled"
    assert (
        build_business_confirmation_sse(
            tool_name=BUSINESS_CONFIRMATION_TOOL_NAME,
            tool_output=json.dumps(
                {
                    "status": "awaiting_user",
                    "confirmation_id": "bc_should_not",
                    "ui": {
                        "title": "x",
                        "fields": [{"key": "a", "label": "A", "value": "1"}],
                    },
                }
            ),
            tool_call_id="c1",
        )
        is None
    )
    # Clear gate for other tests
    arm_cancel_confirmation_gate("普通用户消息")


def test_infer_confirmation_value_type_uses_value_shape_not_field_name():
    from app.services.ai.business_confirmation import infer_confirmation_value_type

    assert (
        infer_confirmation_value_type({"value": "2026-09-25", "value_type": "string"})
        == "date"
    )
    assert infer_confirmation_value_type({"value": "9月12日车辆超速问题整改"}) == "string"
    assert infer_confirmation_value_type({"value": "2026-09-18 09:30"}) == "datetime"
    assert (
        infer_confirmation_value_type(
            {"key": "deadline", "label": "截止日期", "value": "", "value_type": "string"}
        )
        == "string"
    )
    assert infer_confirmation_value_type({"value": "", "value_type": "date"}) == "date"
    assert infer_confirmation_value_type({"value": "2026年9月25日"}) == "date"


def _awaiting_confirmation_payload(*, field_value: str = "预览") -> dict:
    return {
        "status": "awaiting_user",
        "confirmation_id": "bc_oversize",
        "message": "等待用户确认",
        "ui": {
            "title": "确认立即下发",
            "summary": "向已匹配企业下发整改",
            "fields": [
                {
                    "key": "item_preview",
                    "label": "下发预览",
                    "value": field_value,
                    "editable": False,
                    "value_type": "string",
                }
            ],
            "confirm_label": "确定",
            "cancel_label": "取消",
            "risk_note": "",
        },
    }


def test_parse_confirmation_tool_output_accepts_raw_wrapper():
    raw = json.dumps(_awaiting_confirmation_payload(), ensure_ascii=False)
    parsed = parse_confirmation_tool_output({"raw": raw})
    assert parsed is not None
    assert parsed["confirmation_id"] == "bc_oversize"


def test_truncated_confirmation_json_does_not_parse():
    raw = json.dumps(_awaiting_confirmation_payload(field_value="X" * 5000), ensure_ascii=False)
    truncated = raw[:4000] + "\n… [输出已截断]"
    assert parse_confirmation_tool_output(truncated) is None
    assert (
        build_business_confirmation_sse(
            tool_name=BUSINESS_CONFIRMATION_TOOL_NAME,
            tool_output=truncated,
            tool_call_id="call_trunc",
        )
        is None
    )


def test_hitl_observation_keeps_full_confirmation_payload_for_sse():
    from app.services.ai.runtime.agentscope.hitl_tool_result import (
        prepare_runtime_tool_observation_text,
        reset_pending_hitl_ui_payloads,
        take_pending_hitl_ui_payload,
    )

    reset_pending_hitl_ui_payloads()
    full = json.dumps(_awaiting_confirmation_payload(field_value="企业预览 " + ("详" * 4500)), ensure_ascii=False)
    assert len(full) > 4000

    observation = prepare_runtime_tool_observation_text(BUSINESS_CONFIRMATION_TOOL_NAME, full)
    compact = json.loads(observation)
    assert compact["status"] == "awaiting_user"
    assert compact["confirmation_id"] == "bc_oversize"
    assert compact["ui"]["field_count"] == 1
    assert "fields" not in compact["ui"]
    assert "输出已截断" not in observation

    stashed = take_pending_hitl_ui_payload(BUSINESS_CONFIRMATION_TOOL_NAME)
    assert stashed == full
    event = build_business_confirmation_sse(
        tool_name=BUSINESS_CONFIRMATION_TOOL_NAME,
        tool_output=stashed,
        tool_call_id="call_full",
    )
    assert event is not None
    assert event["title"] == "确认立即下发"
    assert event["fields"][0]["value"].startswith("企业预览")


@pytest.mark.asyncio
async def test_runtime_tool_wrapper_does_not_truncate_confirmation_card_payload():
    from agentscope.message import ToolResultState

    from app.services.ai.runtime.agentscope.hitl_tool_result import (
        reset_pending_hitl_ui_payloads,
        take_pending_hitl_ui_payload,
    )
    from app.services.ai.runtime.agentscope.tools import AgentScopeRuntimeTool, RuntimeToolSpec

    reset_pending_hitl_ui_payloads()
    full = json.dumps(_awaiting_confirmation_payload(field_value="Y" * 5000), ensure_ascii=False)

    async def confirmation_tool() -> str:
        return full

    spec = RuntimeToolSpec(
        name=BUSINESS_CONFIRMATION_TOOL_NAME,
        description="Show confirmation card",
        parameters_schema={"type": "object", "properties": {}},
        source_type="system",
        callable=confirmation_tool,
        permission_scope="read",
    )
    wrapped = AgentScopeRuntimeTool(spec, approval_mode="allow")
    chunk = await wrapped()

    assert chunk.state == ToolResultState.SUCCESS
    observation = chunk.content[0].text
    assert "输出已截断" not in observation
    assert json.loads(observation)["ui"]["field_count"] == 1
    assert take_pending_hitl_ui_payload(BUSINESS_CONFIRMATION_TOOL_NAME) == full
