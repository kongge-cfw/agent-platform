from types import SimpleNamespace

import json

import pytest

from app.services.ai.hitl_continuation import (
    HITL_CONTINUATION_MARKER,
    HitlContinuationStore,
    build_continuation_prompt_block,
    enrich_confirmation_fields,
    is_entity_resolve_tool,
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
    assert "enterpriseId: 15" in str(enterprise_field["value"])
    assert "霍州市安泰运业有限公司" in str(enterprise_field["value"])
    id_field = next(item for item in fields if item["key"] == "resolved_ids")
    assert id_field["editable"] is False
    assert "15" in str(id_field["value"])


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
    assert "orgId: org-9" in str(target["value"])
    assert "未解析对象" in str(target["value"])


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
    assert "orgId: org-9" in str(target["value"])
    assert next(item for item in fields if item["key"] == "resolved_ids")["value"].find("org-9") >= 0


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
            "todos": {"todos": [{"content": "下发任务", "status": "in_progress"}], "counts": {}},
        }
    )
    assert HITL_CONTINUATION_MARKER in block
    assert "industry-dispatch-task" in block
    assert "enterpriseId=15" in block
    assert "/tmp/overspeed.xlsx" in block
    assert "禁止臆造" in block
    assert "不得写入下发名单" not in block


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
