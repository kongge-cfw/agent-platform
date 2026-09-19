from types import SimpleNamespace

import json

import pytest

from app.services.ai.hitl_continuation import (
    HITL_CONTINUATION_MARKER,
    RESOLVED_ENTITIES_MARKER,
    HitlContinuationCoordinator,
    HitlContinuationStore,
    HitlContinuationUnavailableError,
    advance_todo_snapshot_after_hitl_confirm,
    build_continuation_prompt_block,
    build_resolved_entities_prompt_block,
    compact_resolve_tool_result_for_model,
    enrich_confirmation_card,
    enrich_confirmation_fields,
    has_open_hitl_todos,
    is_entity_resolve_tool,
    normalize_skills,
    parse_resolve_tool_fact,
    should_restore_hitl_continuation,
    is_hitl_cancel_receipt,
)
from app.services.ai.skills.injector import SkillInjector


pytestmark = pytest.mark.no_infrastructure


@pytest.fixture(autouse=True)
def _clear_hitl_memory():
    HitlContinuationStore.clear_memory()
    yield
    HitlContinuationStore.clear_memory()


@pytest.mark.asyncio
async def test_coordinator_delegates_to_compatible_store():
    store = HitlContinuationStore(None, allow_memory_fallback=True)
    coordinator = HitlContinuationCoordinator(store)

    await coordinator.remember_skill(
        skill_id="industry-dispatch-task",
        skill_name="行业任务下发",
        user_id="u1",
        conversation_id="conv-1",
    )

    continuation = await coordinator.get(user_id="u1", conversation_id="conv-1")
    assert continuation is not None
    assert continuation["skills"][0]["id"] == "industry-dispatch-task"
    assert continuation["skills"][0]["name"] == "行业任务下发"
    assert continuation["skills"][0]["scope"] == ""


@pytest.mark.asyncio
async def test_store_without_fallback_fails_when_redis_is_missing():
    store = HitlContinuationStore(None, allow_memory_fallback=False)

    with pytest.raises(HitlContinuationUnavailableError):
        await store.get(user_id="u1", conversation_id="conv-1")


def test_prompt_assembler_injects_hitl_continuation_block():
    from app.services.ai.prompt_assembler import PromptAssemblyInput, assemble_system_prompt

    assembled = assemble_system_prompt(
        PromptAssemblyInput(
            agent_system_prompt="Agent DB prompt",
            agent_config=SimpleNamespace(agent_name="TestAgent"),
            engine_type="LOCAL",
            skills_injection=[],
            skills_already_loaded=True,
            skills_dir="/tmp/skills",
            hitl_continuation_block=build_continuation_prompt_block(
                {
                    "skills": [{"id": "industry-dispatch-task", "name": "行业任务下发"}],
                    "original_user_query": "下发任务",
                }
            ),
        )
    )
    assert HITL_CONTINUATION_MARKER in assembled.full_text
    assert "industry-dispatch-task" in assembled.full_text


def test_should_restore_confirm_but_not_cancel():
    assert should_restore_hitl_continuation(
        "【业务确认】用户已确定\nconfirmation_id: bc_1\n- 任务名称 (task_name): x"
    )
    assert is_hitl_cancel_receipt("【业务确认】用户已取消\nconfirmation_id: bc_1")
    assert not should_restore_hitl_continuation("【业务确认】用户已取消\nconfirmation_id: bc_1")
    assert should_restore_hitl_continuation(
        "【用户回答】\ninteraction_type: question\nquestion_id: uq_1\nselected_option_ids: [\"a\"]\ncancelled: false"
    )
    assert not should_restore_hitl_continuation(
        "【用户回答】\ninteraction_type: question\nquestion_id: uq_1\nselected_option_ids: []\ncancelled: true"
    )
    assert not should_restore_hitl_continuation("分析附件并下发任务")


def test_advance_todo_snapshot_after_hitl_confirm_completes_waiting_and_starts_next():
    advanced = advance_todo_snapshot_after_hitl_confirm(
        {
            "todos": [
                {"content": "整理附件", "status": "completed"},
                {"content": "确认下发内容", "status": "in_progress"},
                {"content": "向企业下发任务", "status": "pending"},
            ],
            "counts": {"pending": 1, "in_progress": 1, "completed": 1, "cancelled": 0},
        }
    )

    assert advanced == {
        "todos": [
            {"content": "整理附件", "status": "completed"},
            {"content": "确认下发内容", "status": "completed"},
            {"content": "向企业下发任务", "status": "in_progress"},
        ],
        "counts": {"pending": 0, "in_progress": 1, "completed": 2, "cancelled": 0},
    }
    assert advance_todo_snapshot_after_hitl_confirm({"todos": []}) is None
    assert advance_todo_snapshot_after_hitl_confirm(None) is None
    already_done = advance_todo_snapshot_after_hitl_confirm(
        {"todos": [{"content": "确认下发内容", "status": "completed"}]}
    )
    assert already_done is None


def test_parse_resolve_tool_and_enrich_confirmation_fields():
    fact = parse_resolve_tool_fact(
        "mcp_mcp-public-admin-127-0-0-1-2_enterprise_resolve_33ee1bcf16",
        {
            "total": 2,
            "found": 1,
            "missing": 1,
            "records": [
                {
                    "name": "山西金马捷安物流有限公司",
                    "found": True,
                    "enterpriseId": "15",
                    "matchedName": "山西金马捷安物流有限公司",
                },
                {"name": "霍州市安泰运业有限公司", "found": False, "enterpriseId": None},
            ],
        },
    )
    assert fact["found"] == 1
    assert fact["records"][0]["id_key"] == "enterpriseId"
    assert fact["records"][0]["id_value"] == "15"
    continuation = {
        "facts": {"resolved_entities": fact},
        "skills": [{"id": "industry-dispatch-task", "name": "行业任务下发"}],
    }
    fields = enrich_confirmation_fields(
        [
            {
                "key": "enterprises",
                "label": "下发企业（9家）",
                "value": "山西金马捷安物流有限公司、霍州市安泰运业有限公司",
                "editable": True,
                "value_type": "string",
            }
        ],
        continuation,
    )
    enterprise_field = next(item for item in fields if item["key"] == "enterprises")
    assert enterprise_field["value"] == "山西金马捷安物流有限公司"
    assert "enterpriseId" not in str(enterprise_field["value"])
    assert not any(item.get("key") == "resolved_ids" for item in fields)
    _fields, risk_note = enrich_confirmation_card(
        [
            {
                "key": "enterprises",
                "label": "下发企业",
                "value": "山西金马捷安物流有限公司、霍州市安泰运业有限公司",
                "editable": True,
                "value_type": "string",
            }
        ],
        continuation,
        risk_note="部分企业无法匹配。",
    )
    assert "霍州市安泰运业有限公司" in risk_note


def test_enrich_matches_numbered_name_list():
    fact = parse_resolve_tool_fact(
        "mcp_org_resolve_abcd",
        {
            "records": [
                {"name": "示例组织", "found": True, "orgId": "org-9", "matchedName": "示例组织"}
            ]
        },
    )
    fields = enrich_confirmation_fields(
        [
            {
                "key": "targets",
                "label": "目标对象",
                "value": "1. 示例组织\n2. 未解析对象",
                "editable": True,
                "value_type": "text",
            }
        ],
        {"facts": {"resolved_entities": fact}},
    )
    target = next(item for item in fields if item["key"] == "targets")
    assert target["value"] == "示例组织"
    assert "orgId" not in str(target["value"])
    _fields, risk_note = enrich_confirmation_card(
        [
            {
                "key": "targets",
                "label": "目标对象",
                "value": "1. 示例组织\n2. 未解析对象",
                "editable": True,
                "value_type": "text",
            }
        ],
        {"facts": {"resolved_entities": fact}},
    )
    assert "未解析对象" in risk_note


def test_parse_resolve_tool_extracts_json_from_prefixed_text():
    fact = parse_resolve_tool_fact(
        "mcp_org_resolve_abcd",
        '查询完成\n```json\n{"records":[{"name":"示例组织","found":true,"orgId":"org-9"}]}\n```\n',
    )
    assert fact is not None
    assert fact["records"][0]["id_value"] == "org-9"


def test_relative_date_resolve_is_not_entity_fact():
    assert not is_entity_resolve_tool("resolve_relative_dates")
    assert parse_resolve_tool_fact(
        "resolve_relative_dates",
        {"records": [{"name": "明天", "found": True, "dateId": "2026-09-19"}]},
    ) is None


def _fat_enterprise_resolve_payload(*, found: int = 11, missing: int = 31) -> dict:
    records = []
    for index in range(found):
        records.append(
            {
                "name": f"山西测试运输有限公司{index:02d}加长名称用于撑满工具上下文",
                "found": True,
                "enabled": True,
                "matchCount": 1,
                "enterpriseId": str(1000 + index),
                "matchedName": f"山西测试运输有限公司{index:02d}加长名称用于撑满工具上下文",
                "address": "临汾市尧都区测试路" * 40,
                "creditCode": "91" + ("0" * 16),
                "raw": {"dump": "X" * 180, "candidates": [{"id": "x", "score": 0.9}] * 6},
            }
        )
    for index in range(missing):
        records.append(
            {
                "name": f"未匹配企业名称{index:02d}加长名称",
                "found": False,
                "enabled": False,
                "matchCount": 0,
                "enterpriseId": None,
                "address": "未知地址" * 40,
                "raw": {"dump": "Y" * 180},
            }
        )
    return {
        "total": found + missing,
        "found": found,
        "missing": missing,
        "records": records,
    }


def test_compact_resolve_observation_keeps_all_found_ids():
    payload = _fat_enterprise_resolve_payload()
    raw = json.dumps(payload, ensure_ascii=False)
    assert len(raw) > 20000

    observation = compact_resolve_tool_result_for_model(
        "mcp_mcp-public-admin_enterprise_resolve_33ee1bcf16",
        payload,
    )
    assert observation is not None
    assert "输出已截断" not in observation
    compact = json.loads(observation)
    assert compact["found"] == 11
    found_records = [item for item in compact["records"] if item.get("found")]
    assert len(found_records) == 11
    assert {item["enterpriseId"] for item in found_records} == {str(1000 + i) for i in range(11)}
    fact = parse_resolve_tool_fact(
        "mcp_mcp-public-admin_enterprise_resolve_33ee1bcf16",
        observation,
    )
    assert fact is not None
    assert sum(1 for item in fact["records"] if item["found"]) == 11


def test_compact_resolve_collapses_missing_names_instead_of_dropping_found():
    payload = _fat_enterprise_resolve_payload(found=11, missing=400)
    observation = compact_resolve_tool_result_for_model(
        "mcp_org_enterprise_resolve_abcd",
        payload,
    )
    assert observation is not None
    compact = json.loads(observation)
    assert compact["found"] == 11
    assert compact.get("missing_collapsed") is True
    assert len(compact.get("missing_names") or []) == 400
    assert len([item for item in compact["records"] if item.get("found")]) == 11
    fact = parse_resolve_tool_fact("mcp_org_enterprise_resolve_abcd", observation)
    assert fact is not None
    assert sum(1 for item in fact["records"] if item["found"]) == 11
    assert fact["missing"] == 400


def test_resolve_observation_does_not_mid_cut_json_and_stashes_full_payload():
    from app.services.ai.runtime.agentscope.hitl_tool_result import (
        prepare_runtime_tool_observation_text,
        reset_pending_resolve_payloads,
        take_pending_resolve_payload,
    )
    from app.services.ai.runtime.agentscope.stream_reconcile import truncate_for_context

    reset_pending_resolve_payloads()
    tool_name = "mcp_org_enterprise_resolve_abcd"
    payload = _fat_enterprise_resolve_payload()
    raw = json.dumps(payload, ensure_ascii=False)
    truncated = truncate_for_context(raw)
    assert "输出已截断" in truncated

    observation = prepare_runtime_tool_observation_text(tool_name, payload)
    compact = json.loads(observation)
    assert compact["found"] == 11
    assert len([item for item in compact["records"] if item.get("found")]) == 11
    assert "输出已截断" not in observation

    stashed = take_pending_resolve_payload(tool_name)
    assert stashed is not None
    fact = parse_resolve_tool_fact(tool_name, stashed)
    assert fact is not None
    assert sum(1 for item in fact["records"] if item["found"]) == 11
    assert fact["missing"] == 31


def test_enrich_confirmation_unions_eligible_names_and_syncs_count():
    payload = _fat_enterprise_resolve_payload()
    fact = parse_resolve_tool_fact("mcp_org_enterprise_resolve_abcd", payload)
    visible_names = "、".join(item["name"] for item in payload["records"][:9] if item["found"])
    fields, risk_note = enrich_confirmation_card(
        [
            {
                "key": "targetCount",
                "label": "下发数量",
                "value": "9个",
                "editable": False,
                "value_type": "string",
            },
            {
                "key": "enterprises",
                "label": "下发企业（9家）",
                "value": visible_names,
                "editable": True,
                "value_type": "string",
            },
        ],
        {"facts": {"resolved_entities": fact}},
        risk_note="部分企业无法匹配。",
    )
    enterprise_field = next(item for item in fields if item["key"] == "enterprises")
    count_field = next(item for item in fields if item["key"] == "targetCount")
    assert count_field["value"] == "11个"
    assert "enterpriseId" not in str(enterprise_field["value"])
    for index in range(11):
        assert payload["records"][index]["name"] in str(enterprise_field["value"])
    assert not any(item.get("key") == "resolved_ids" for item in fields)
    assert "无法匹配或不可用" in risk_note


def test_enrich_confirmation_does_not_rewrite_prose_or_title_counts():
    payload = _fat_enterprise_resolve_payload(found=3, missing=1)
    fact = parse_resolve_tool_fact("mcp_org_enterprise_resolve_abcd", payload)
    first_name = payload["records"][0]["name"]
    second_name = payload["records"][1]["name"]
    third_name = payload["records"][2]["name"]
    fields, risk_note = enrich_confirmation_card(
        [
            {
                "key": "name",
                "label": "任务名称",
                "value": "2月专项",
                "editable": True,
                "value_type": "string",
            },
            {
                "key": "requirement",
                "label": "共性要求",
                "value": f"{first_name}需按附件完成整改，并报送佐证。",
                "editable": True,
                "value_type": "text",
            },
            {
                "key": "enterprises",
                "label": "下发对象",
                "value": f"{first_name}、{second_name}",
                "editable": True,
                "value_type": "string",
            },
        ],
        {"facts": {"resolved_entities": fact}},
    )
    assert fields[0]["value"] == "2月专项"
    assert "需按附件完成整改" in str(fields[1]["value"])
    assert third_name in str(fields[2]["value"])
    assert risk_note


def test_generic_resolve_tool_enriches_by_name_value():
    fact = parse_resolve_tool_fact(
        "mcp_org_resolve_abcd",
        {
            "records": [
                {"name": "示例组织", "found": True, "orgId": "org-9", "matchedName": "示例组织"}
            ]
        },
    )
    fields = enrich_confirmation_fields(
        [
            {
                "key": "targets",
                "label": "目标对象",
                "value": "示例组织",
                "editable": True,
                "value_type": "string",
            }
        ],
        {"facts": {"resolved_entities": fact}},
    )
    target = next(item for item in fields if item["key"] == "targets")
    assert target["value"] == "示例组织"
    assert "orgId" not in str(target["value"])
    assert not any(item.get("key") == "resolved_ids" for item in fields)


def test_incomplete_resolve_snapshot_does_not_rewrite_card():
    fact = parse_resolve_tool_fact(
        "mcp_org_resolve_abcd",
        {
            "found": 11,
            "records": [
                {"name": "甲公司", "found": True, "orgId": "1"},
                {"name": "乙公司", "found": True, "orgId": "2"},
            ],
        },
    )
    assert fact is not None
    assert fact["integrity"] == "incomplete"
    assert fact["found_claimed"] == 11
    assert fact["found_records"] == 2
    fields, _note = enrich_confirmation_card(
        [
            {
                "key": "targets",
                "label": "目标对象",
                "value": "甲公司",
                "editable": True,
                "value_type": "string",
            }
        ],
        {"facts": {"resolved_entities": fact}},
    )
    assert fields[0]["value"] == "甲公司"
    compact = json.loads(
        compact_resolve_tool_result_for_model(
            "mcp_org_resolve_abcd",
            {
                "found": 11,
                "records": [
                    {"name": "甲公司", "found": True, "orgId": "1"},
                    {"name": "乙公司", "found": True, "orgId": "2"},
                ],
            },
        )
        or "{}"
    )
    assert compact["integrity"] == "incomplete"
    assert "再次调用解析工具" in str(compact.get("integrity_note") or "")


def test_resolved_entities_prompt_block_is_not_hitl_receipt():
    block = build_resolved_entities_prompt_block(
        {
            "facts": {
                "resolved_entities": {
                    "integrity": "complete",
                    "records": [
                        {
                            "name": "示例组织",
                            "found": True,
                            "id_key": "orgId",
                            "id_value": "org-9",
                        }
                    ],
                }
            }
        }
    )
    assert RESOLVED_ENTITIES_MARKER in block
    assert HITL_CONTINUATION_MARKER not in block
    assert "orgId=org-9" in block


def test_has_open_hitl_todos():
    assert has_open_hitl_todos(
        {"todos": {"todos": [{"content": "确认下发", "status": "in_progress"}]}}
    )
    assert not has_open_hitl_todos(
        {"todos": {"todos": [{"content": "确认下发", "status": "completed"}]}}
    )


def test_continuation_prompt_lists_all_found_ids_before_missing_cap():
    records = []
    for index in range(11):
        records.append(
            {
                "name": f"已匹配企业{index:02d}",
                "found": True,
                "id_key": "enterpriseId",
                "id_value": str(1000 + index),
            }
        )
    for index in range(45):
        records.append({"name": f"未匹配企业{index:02d}", "found": False})
    block = build_continuation_prompt_block({"facts": {"resolved_entities": {"records": records}}})
    for index in range(11):
        assert f"已匹配企业{index:02d} → enterpriseId={1000 + index}" in block
    assert block.count("未解析到主键") == 40


def test_continuation_prompt_block_includes_facts_and_skills():
    block = build_continuation_prompt_block(
        {
            "skills": [{"id": "industry-dispatch-task", "name": "行业任务下发", "scope": "global"}],
            "original_user_query": "分析附件中的问题，下发任务给企业",
            "attachments": [
                {"filename": "超速.xlsx", "path": "/tmp/overspeed.xlsx", "type": "file"}
            ],
            "facts": {
                "enterprise_resolve": {
                    "records": [
                        {
                            "name": "山西金马捷安物流有限公司",
                            "enterpriseId": "15",
                            "found": True,
                        }
                    ]
                }
            },
            "todos": {
                "todos": [
                    {"content": "确认下发内容", "status": "completed"},
                    {"content": "下发任务", "status": "in_progress"},
                ],
                "counts": {},
            },
        }
    )
    assert HITL_CONTINUATION_MARKER in block
    assert "industry-dispatch-task" in block
    assert "enterpriseId=15" in block
    assert "/tmp/overspeed.xlsx" in block
    assert "禁止臆造" in block
    assert "不得写入下发名单" not in block
    assert "[completed] 确认下发内容" in block
    assert "[in_progress] 下发任务" in block
    assert "不要把已完成项改回进行中" in block


@pytest.mark.asyncio
async def test_store_merges_skills_and_does_not_overwrite_names_with_ids():
    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="c1",
        skills=[{"id": "industry-dispatch-task", "name": "行业任务下发", "scope": "global"}],
    )
    await store.merge(
        user_id="u1",
        conversation_id="c1",
        skills=[{"id": "industry-dispatch-task", "name": "industry-dispatch-task"}],
    )
    payload = await store.get(user_id="u1", conversation_id="c1")
    assert payload["skills"][0]["name"] == "行业任务下发"


@pytest.mark.asyncio
async def test_remember_turn_inputs_replaces_query_and_skills():
    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="c1",
        skills=[{"id": "old-skill", "name": "旧技能"}],
        original_user_query="旧任务",
        fact_name="resolved_entities",
        fact_payload={"records": [{"name": "旧对象", "found": True, "id_key": "id", "id_value": "1"}]},
    )
    await store.remember_turn_inputs(
        user_info={"user_id": "u1"},
        conversation_id="c1",
        user_query="新问题，不要粘旧技能",
        messages=[],
        skills=[{"id": "new-skill", "name": "新技能"}],
    )
    payload = await store.get(user_id="u1", conversation_id="c1")
    assert payload["original_user_query"] == "新问题，不要粘旧技能"
    assert [item["id"] for item in payload["skills"]] == ["new-skill"]
    assert payload["facts"] == {}


@pytest.mark.asyncio
async def test_remember_turn_inputs_keeps_facts_when_todos_open():
    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="c1",
        skills=[{"id": "old-skill", "name": "旧技能"}],
        original_user_query="旧任务",
        fact_name="resolved_entities",
        fact_payload={"records": [{"name": "旧对象", "found": True, "id_key": "id", "id_value": "1"}]},
        todos={
            "todos": [{"content": "确认下发内容", "status": "in_progress"}],
            "counts": {"in_progress": 1},
        },
    )
    await store.remember_turn_inputs(
        user_info={"user_id": "u1"},
        conversation_id="c1",
        user_query="继续",
        messages=[],
        skills=[{"id": "old-skill", "name": "旧技能"}],
    )
    payload = await store.get(user_id="u1", conversation_id="c1")
    assert payload["original_user_query"] == "旧任务"
    assert payload["facts"]["resolved_entities"]["records"][0]["id_value"] == "1"
    assert payload["todos"]["todos"][0]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_remember_turn_inputs_ignores_historical_files():
    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="c1",
        skills=[{"id": "old-skill", "name": "旧技能"}],
        attachments=[{"filename": "old.xlsx", "path": "/tmp/old.xlsx", "type": "file"}],
        original_user_query="旧任务",
    )
    await store.remember_turn_inputs(
        user_info={"user_id": "u1"},
        conversation_id="c1",
        user_query="全新问题",
        messages=[
            {
                "role": "user",
                "content": "旧任务",
                "files": [
                    {"type": "skill", "url": "old-skill", "filename": "旧技能 (技能)"},
                    {"type": "file", "url": "/tmp/old.xlsx", "filename": "old.xlsx"},
                ],
            },
            {"role": "assistant", "content": "已处理"},
            {"role": "user", "content": "全新问题", "files": []},
        ],
        skills=[],
    )
    payload = await store.get(user_id="u1", conversation_id="c1")
    assert payload["skills"] == []
    assert payload["attachments"] == []
    assert payload["original_user_query"] == "全新问题"


def test_attachments_from_messages_uses_readable_abs_path():
    from app.services.ai.hitl_continuation import attachments_from_messages

    items = attachments_from_messages(
        [
            {
                "role": "user",
                "content": "分析附件",
                "files": [
                    {
                        "type": "file",
                        "url": "/static/uploads/overspeed.xlsx",
                        "filename": "overspeed.xlsx",
                    }
                ],
            }
        ]
    )
    assert items[0]["path"] == "/app/data/uploads/overspeed.xlsx"
    assert items[0]["filename"] == "overspeed.xlsx"


def test_parse_resolve_tool_unwraps_wrapped_output():
    raw = {
        "records": [
            {"name": "示例组织", "found": True, "orgId": "org-9", "matchedName": "示例组织"}
        ]
    }
    wrapped = {"text": json.dumps(raw, ensure_ascii=False), "data_blocks": [{"block_id": "1"}]}
    fact = parse_resolve_tool_fact("mcp_org_resolve_abcd", wrapped)
    assert fact is not None
    assert fact["records"][0]["id_value"] == "org-9"


@pytest.mark.asyncio
async def test_remember_resolve_tool_merges_records():
    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.remember_resolve_tool(
        user_id="u1",
        conversation_id="c1",
        tool_name="mcp_org_resolve_a",
        tool_output={
            "records": [{"name": "甲", "found": True, "orgId": "1", "matchedName": "甲"}]
        },
    )
    await store.remember_resolve_tool(
        user_id="u1",
        conversation_id="c1",
        tool_name="mcp_user_resolve_b",
        tool_output={
            "records": [{"name": "乙", "found": True, "userId": "2", "matchedName": "乙"}]
        },
    )
    payload = await store.get(user_id="u1", conversation_id="c1")
    names = {item["name"] for item in payload["facts"]["resolved_entities"]["records"]}
    assert names == {"甲", "乙"}


@pytest.mark.asyncio
async def test_inject_skills_restores_hitl_continuation_on_confirm_receipt(
    tmp_path, monkeypatch
):
    skill_dir = tmp_path / "industry-dispatch-task"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: 行业任务下发\ndescription: 下发任务\n---\n\n# 流程\n先解析企业 ID 再下发。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.core.config.settings.SKILLS_DIR",
        str(tmp_path),
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.ai.skill_resolver.settings.SKILLS_DIR",
        str(tmp_path),
        raising=False,
    )

    async def fake_config_get(key, default=None):
        values = {
            "skill_auto_full_load_enabled": "true",
            "skill_auto_full_load_min_score": "0.75",
            "skill_auto_full_load_max_count": "1",
            "skill_auto_full_load_max_bytes": "65536",
        }
        return values.get(key, default)

    monkeypatch.setattr("app.services.config_service.ConfigService.get", fake_config_get)

    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="conv-1",
        skills=[{"id": "industry-dispatch-task", "name": "行业任务下发", "scope": "global"}],
    )

    async def fake_from_runtime():
        return store

    monkeypatch.setattr(HitlContinuationStore, "from_runtime", fake_from_runtime)

    logged = []

    def skills_log_callback(skill_id, skill_name, details_msg):
        logged.append((skill_id, skill_name, details_msg))

    injections = await SkillInjector.inject_skills(
        messages=[{"role": "user", "content": "【业务确认】用户已确定", "files": []}],
        user_query="【业务确认】用户已确定\nconfirmation_id: bc_1\n请根据以下已确认字段继续执行",
        agent_config=SimpleNamespace(skills_custom=False, skills=[]),
        user_info={"user_id": "u1"},
        conversation_id="conv-1",
        skills_log_callback=skills_log_callback,
    )
    joined = "\n".join(injections)
    assert "industry-dispatch-task" in joined
    assert "BEGIN SKILL.md" in joined
    assert logged
    assert logged[0][0] == "industry-dispatch-task"
    assert "HITL 续跑" in logged[0][2]


@pytest.mark.asyncio
async def test_inject_skills_does_not_restore_on_cancel_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.core.config.settings.SKILLS_DIR",
        str(tmp_path),
        raising=False,
    )

    async def fake_config_get(key, default=None):
        return {
            "skill_auto_full_load_enabled": "true",
            "skill_auto_full_load_min_score": "0.75",
            "skill_auto_full_load_max_count": "1",
            "skill_auto_full_load_max_bytes": "65536",
        }.get(key, default)

    monkeypatch.setattr("app.services.config_service.ConfigService.get", fake_config_get)

    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="conv-1",
        skills=[{"id": "industry-dispatch-task", "name": "行业任务下发"}],
    )

    async def fake_from_runtime():
        return store

    monkeypatch.setattr(HitlContinuationStore, "from_runtime", fake_from_runtime)

    injections = await SkillInjector.inject_skills(
        messages=[{"role": "user", "content": "【业务确认】用户已取消", "files": []}],
        user_query="【业务确认】用户已取消\nconfirmation_id: bc_1",
        agent_config=SimpleNamespace(skills_custom=False, skills=[]),
        user_info={"user_id": "u1"},
        conversation_id="conv-1",
    )
    assert injections == [] or all("industry-dispatch-task" not in item for item in injections)


def test_normalize_skills_keeps_content_rev():
    items = normalize_skills(
        [
            {"id": "demo-skill", "name": "演示", "scope": "global", "content_rev": "abc123"},
            {"url": "demo-skill", "name": "重复"},
        ]
    )
    assert items == [
        {"id": "demo-skill", "name": "演示", "scope": "global", "content_rev": "abc123"}
    ]


@pytest.mark.asyncio
async def test_store_merge_keeps_previous_content_rev():
    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="c1",
        skills=[{"id": "demo-skill", "name": "演示", "scope": "global", "content_rev": "rev-1"}],
    )
    await store.merge(
        user_id="u1",
        conversation_id="c1",
        skills=[{"id": "demo-skill", "name": "演示"}],
    )
    payload = await store.get(user_id="u1", conversation_id="c1")
    assert payload["skills"][0]["content_rev"] == "rev-1"


@pytest.mark.asyncio
async def test_inject_skills_remounts_when_content_rev_changes(tmp_path, monkeypatch):
    from app.services.ai.skill_revision import current_skill_revision

    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\nname: 演示技能\ndescription: 演示\n---\n\n# 旧流程\n第一步。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.settings.SKILLS_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(
        "app.services.ai.skill_resolver.settings.SKILLS_DIR",
        str(tmp_path),
        raising=False,
    )

    async def fake_config_get(key, default=None):
        return {
            "skill_auto_full_load_enabled": "true",
            "skill_auto_full_load_min_score": "0.75",
            "skill_auto_full_load_max_count": "1",
            "skill_auto_full_load_max_bytes": "65536",
        }.get(key, default)

    monkeypatch.setattr("app.services.config_service.ConfigService.get", fake_config_get)

    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="conv-1",
        skills=[
            {
                "id": "demo-skill",
                "name": "演示技能",
                "scope": "global",
                "content_rev": "stale-rev",
            }
        ],
    )

    async def fake_from_runtime():
        return HitlContinuationCoordinator(store)

    monkeypatch.setattr(HitlContinuationCoordinator, "from_runtime", fake_from_runtime)

    logged = []

    def skills_log_callback(skill_id, skill_name, details_msg):
        logged.append((skill_id, skill_name, details_msg))

    injections = await SkillInjector.inject_skills(
        messages=[{"role": "user", "content": "按刚才的技能继续", "files": []}],
        user_query="按刚才的技能继续",
        agent_config=SimpleNamespace(skills_custom=False, skills=[]),
        user_info={"user_id": "u1"},
        conversation_id="conv-1",
        skills_log_callback=skills_log_callback,
    )
    joined = "\n".join(injections)
    assert "BEGIN SKILL.md" in joined
    assert "该技能文件已更新" in joined
    assert "必须重新调用 read_skill_instruction" in joined
    assert "禁止沿用历史" in joined
    assert logged
    assert logged[0][0] == "demo-skill"
    assert "已重新挂载" in logged[0][2]

    persisted = await store.get(user_id="u1", conversation_id="conv-1")
    assert persisted["skills"][0]["content_rev"] == current_skill_revision(
        "demo-skill",
        scope="global",
        user_info={"user_id": "u1"},
    )


@pytest.mark.asyncio
async def test_inject_skills_skips_remount_when_content_rev_matches(tmp_path, monkeypatch):
    from app.services.ai.skill_revision import current_skill_revision

    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: 演示技能\ndescription: 演示\n---\n\n# 流程\n保持不变。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.settings.SKILLS_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(
        "app.services.ai.skill_resolver.settings.SKILLS_DIR",
        str(tmp_path),
        raising=False,
    )

    async def fake_config_get(key, default=None):
        return {
            "skill_auto_full_load_enabled": "true",
            "skill_auto_full_load_min_score": "0.75",
            "skill_auto_full_load_max_count": "1",
            "skill_auto_full_load_max_bytes": "65536",
        }.get(key, default)

    monkeypatch.setattr("app.services.config_service.ConfigService.get", fake_config_get)

    current_rev = current_skill_revision("demo-skill", scope="global")
    assert current_rev
    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="conv-1",
        skills=[
            {
                "id": "demo-skill",
                "name": "演示技能",
                "scope": "global",
                "content_rev": current_rev,
            }
        ],
    )

    async def fake_from_runtime():
        return HitlContinuationCoordinator(store)

    monkeypatch.setattr(HitlContinuationCoordinator, "from_runtime", fake_from_runtime)

    logged = []

    injections = await SkillInjector.inject_skills(
        messages=[{"role": "user", "content": "换个无关问题", "files": []}],
        user_query="换个无关问题",
        agent_config=SimpleNamespace(skills_custom=False, skills=[]),
        user_info={"user_id": "u1"},
        conversation_id="conv-1",
        skills_log_callback=lambda *args: logged.append(args),
    )
    joined = "\n".join(injections)
    assert "demo-skill" not in joined
    assert not any("已重新挂载" in str(item) for item in logged)


@pytest.mark.asyncio
async def test_inject_skills_skips_remount_when_stored_rev_missing(tmp_path, monkeypatch):
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: 演示技能\ndescription: 演示\n---\n\n# 流程\n旧会话。\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.core.config.settings.SKILLS_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(
        "app.services.ai.skill_resolver.settings.SKILLS_DIR",
        str(tmp_path),
        raising=False,
    )

    async def fake_config_get(key, default=None):
        return {
            "skill_auto_full_load_enabled": "true",
            "skill_auto_full_load_min_score": "0.75",
            "skill_auto_full_load_max_count": "1",
            "skill_auto_full_load_max_bytes": "65536",
        }.get(key, default)

    monkeypatch.setattr("app.services.config_service.ConfigService.get", fake_config_get)

    store = HitlContinuationStore(None, allow_memory_fallback=True)
    await store.merge(
        user_id="u1",
        conversation_id="conv-1",
        skills=[{"id": "demo-skill", "name": "演示技能", "scope": "global"}],
    )

    async def fake_from_runtime():
        return HitlContinuationCoordinator(store)

    monkeypatch.setattr(HitlContinuationCoordinator, "from_runtime", fake_from_runtime)

    injections = await SkillInjector.inject_skills(
        messages=[{"role": "user", "content": "换个无关问题", "files": []}],
        user_query="换个无关问题",
        agent_config=SimpleNamespace(skills_custom=False, skills=[]),
        user_info={"user_id": "u1"},
        conversation_id="conv-1",
    )
    assert all("demo-skill" not in item for item in injections)
