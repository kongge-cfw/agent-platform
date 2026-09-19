import pytest

from app.services.ai.runtime.agentscope.process_timeline_snapshot import (
    apply_stream_chunk,
    cancel_todo_items,
    complete_todo_items,
    finalize_process_timeline,
    last_todo_update_from_history,
    latest_assistant_todo_update_from_history,
)


pytestmark = pytest.mark.no_infrastructure


def _run(chunks):
    state = []
    for chunk in chunks:
        apply_stream_chunk(state, chunk)
    return finalize_process_timeline(state)


def test_committed_narration_and_tool_are_kept_promoted_candidate_is_dropped():
    items = _run(
        [
            {"type": "process_narration", "content": "我先搜一下。"},
            {"type": "process_narration_commit", "content": "我先搜一下。"},
            {
                "type": "log",
                "id": "tool_1",
                "title": "调用工具: search",
                "details": "query=晋景",
                "status": "success",
                "category": "tool",
                "execution_time_ms": 120,
            },
            {"type": "process_narration", "content": "# 最终报告\n正文"},
            {"type": "process_narration_promote", "content": "# 最终报告\n正文"},
        ]
    )

    kinds = [(item.get("kind"), item.get("textKind"), item.get("pending")) for item in items]
    assert ("text", "narration", False) in kinds
    assert not any(item.get("pending") for item in items)
    narration = next(item for item in items if item.get("textKind") == "narration")
    assert narration["content"] == "我先搜一下。"
    assert narration["children"][0]["title"] == "调用工具: search"
    assert "# 最终报告" not in str(items)


def test_interrupted_narration_is_kept_as_finalized_history_item():
    items = _run([{"type": "process_narration", "content": "正在查询天气"}])

    assert items == [{
        "kind": "text",
        "id": "narration_1",
        "textKind": "narration",
        "content": "正在查询天气",
        "pending": False,
        "interrupted": True,
        "children": [],
    }]


def test_router_log_becomes_intent_style_step_without_raw_event_fields():
    items = _run(
        [
            {
                "type": "router_log",
                "thought": "用户在问数据",
                "selected_agent": "chatbi",
                "confidence": 0.9,
                "status": "success",
                "execution_time_ms": 40,
            }
        ]
    )

    assert len(items) == 1
    assert items[0]["kind"] == "log"
    assert items[0]["id"] == "route:target_selection"
    assert items[0]["title"] == "智能路由决策"
    assert items[0]["category"] == "router"
    assert "用户在问数据" in items[0]["details"]
    assert "chatbi" in items[0]["details"]
    assert "thought" not in items[0]


def test_router_log_updates_route_selection_without_creating_duplicate_step():
    items = _run(
        [
            {
                "type": "log",
                "id": "route:target_selection",
                "title": "判断并匹配目标专家",
                "status": "success",
                "category": "router",
                "execution_time_ms": 6600,
            },
            {
                "type": "router_log",
                "thought": "内部路由原因",
                "selected_agent": "chatbi",
                "confidence": 0.9,
                "status": "success",
                "execution_time_ms": 7200,
            },
        ]
    )

    assert [item["id"] for item in items] == ["route:target_selection"]
    assert items[0]["title"] == "判断并匹配目标专家"
    assert items[0]["execution_time_ms"] == 6600


def test_tool_details_are_truncated_and_empty_snapshot_is_omitted():
    huge = "抓取结果" * 800
    items = _run(
        [
            {
                "type": "log",
                "id": "tool_big",
                "title": "调用工具: crawl",
                "details": huge,
                "status": "success",
                "category": "tool",
            }
        ]
    )
    assert len(items[0]["details"]) < len(huge)
    assert items[0]["details"].endswith("…")
    assert finalize_process_timeline([]) is None
    interrupted = finalize_process_timeline([{"kind": "text", "id": "n", "textKind": "narration", "pending": True, "content": "候选"}])
    assert interrupted[0]["interrupted"] is True


def test_file_metadata_survives_process_timeline_persistence():
    metadata = {
        "operation": "read",
        "path": "/workspace/docs/report.md",
        "target_type": "file",
    }
    items = _run([
        {
            "type": "log",
            "id": "tool_file",
            "title": "工具完成: Read",
            "details": "正文",
            "status": "success",
            "category": "tool",
            "file_metadata": metadata,
        }
    ])

    assert items[0]["file_metadata"] == metadata


def test_model_call_start_and_end_merge_into_one_timeline_step():
    items = _run(
        [
            {
                "type": "model_call",
                "phase": "start",
                "reply_id": "r1",
                "model_name": "deepseek-chat",
            },
            {"type": "process_narration", "content": "我先搜一下。"},
            {"type": "process_narration_commit", "content": "我先搜一下。"},
            {
                "type": "log",
                "id": "tool_1",
                "title": "调用工具: search",
                "status": "success",
                "category": "tool",
            },
            {
                "type": "model_call",
                "phase": "end",
                "reply_id": "r1",
                "input_tokens": 100,
                "output_tokens": 20,
                "duration_ms": 1500,
            },
            {
                "type": "model_call",
                "phase": "start",
                "reply_id": "r2",
                "model_name": "deepseek-chat",
            },
            {
                "type": "model_call",
                "phase": "end",
                "reply_id": "r2",
                "input_tokens": 80,
                "output_tokens": 40,
                "duration_ms": 900,
            },
        ]
    )

    models = [item for item in items if item.get("category") == "model"]
    assert len(models) == 2
    assert models[0]["title"] == "模型调用: deepseek-chat"
    assert models[0]["status"] == "success"
    assert models[0]["details"] == "输入 100 / 输出 20 tokens，耗时 1500 ms"
    assert models[0]["execution_time_ms"] == 1500
    assert models[1]["details"] == "输入 80 / 输出 40 tokens，耗时 900 ms"
    assert items[0]["category"] == "model"
    assert items[1]["textKind"] == "narration"


def test_todo_update_keeps_only_the_latest_complete_checklist():
    items = _run(
        [
            {
                "type": "todo_update",
                "todos": [
                    {"content": "检索知识库", "status": "in_progress"},
                    {"content": "整理答案", "status": "pending"},
                ],
                "counts": {"pending": 1, "in_progress": 1, "completed": 0},
            },
            {
                "type": "todo_update",
                "todos": [
                    {"content": "检索知识库", "status": "completed"},
                    {"content": "整理答案", "status": "in_progress"},
                ],
                "counts": {"pending": 0, "in_progress": 1, "completed": 1},
            },
        ]
    )

    todo_items = [item for item in items if item.get("kind") == "todo"]
    assert len(todo_items) == 1
    assert todo_items[0]["todos"][0]["status"] == "completed"
    assert todo_items[0]["todos"][1]["status"] == "in_progress"
    assert todo_items[0]["counts"] == {
        "pending": 0,
        "in_progress": 1,
        "completed": 1,
        "cancelled": 0,
    }


def test_empty_todo_update_removes_the_current_checklist():
    items = _run(
        [
            {
                "type": "todo_update",
                "todos": [{"content": "检索知识库", "status": "in_progress"}],
                "counts": {"pending": 0, "in_progress": 1, "completed": 0},
            },
            {"type": "todo_update", "todos": [], "counts": {"pending": 0, "in_progress": 0, "completed": 0}},
        ]
    )

    assert items is None


def test_malformed_todo_update_does_not_corrupt_other_timeline_items():
    items = _run(
        [
            {
                "type": "log",
                "id": "tool_1",
                "title": "调用工具: search_knowledge_base",
                "details": "ok",
                "status": "success",
                "category": "tool",
            },
            {"type": "todo_update", "todos": [{"content": "缺少状态"}]},
        ]
    )

    assert len(items) == 1
    assert items[0]["kind"] == "log"
    assert items[0]["title"] == "调用工具: search_knowledge_base"


def test_history_persistence_contract_covers_redis_audit_and_api():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    mysql = (root / "db-prod/V121-add_process_timeline_to_history.sql").read_text(encoding="utf-8")
    pg = (root / "db-prod-pg/V21-add_process_timeline_to_history.sql").read_text(encoding="utf-8")
    model = (root / "app/models/audit.py").read_text(encoding="utf-8")
    schema = (root / "app/schemas/agent.py").read_text(encoding="utf-8")
    audit = (root / "app/services/ai/audit.py").read_text(encoding="utf-8")
    chat = (root / "app/api/v1/endpoints/chat.py").read_text(encoding="utf-8")
    memory = (root / "app/services/ai/memory_service.py").read_text(encoding="utf-8")

    assert "process_timeline" in mysql
    assert "process_timeline" in pg
    assert "process_timeline" in model
    assert "process_timeline" in schema
    assert "process_timeline" in audit
    assert '"process_timeline"' in chat or "process_timeline" in chat
    assert "process_timeline" in memory


def test_hitl_cards_persist_full_payload_and_result_updates_status():
    fields = [
        {"key": "supplier_name", "label": "供应商名称", "value": "北京神马科技有限公司"},
        {"key": "note", "label": "备注", "value": "新供应商"},
    ]
    items = _run(
        [
            {
                "type": "business_confirmation",
                "confirmation_id": "bc_1",
                "title": "请确认供应商",
                "summary": "即将写入主数据",
                "fields": fields,
                "confirm_label": "确定",
                "cancel_label": "取消",
                "status": "pending",
            },
            {
                "type": "user_question",
                "question_id": "uq_1",
                "question": "按什么维度统计？",
                "options": [{"id": "daily", "label": "按天"}, {"id": "monthly", "label": "按月"}],
                "is_multi_select": False,
                "allow_custom_input": True,
                "status": "pending",
            },
            {
                "type": "permission_required",
                "permission_request_id": "perm_1",
                "title": "需要确认工具调用: bash",
                "details": "参数: {\"command\": \"ls\"}",
                "tool_call": {"id": "call_1", "name": "bash", "args": {"command": "ls"}},
                "status": "pending",
            },
            {
                "type": "external_execution_required",
                "external_execution_request_id": "ext_1",
                "title": "需要外部执行工具: browser",
                "details": "参数: {}",
                "tool_call": {"id": "call_2", "name": "browser", "args": {}},
                "status": "pending",
            },
            {
                "type": "grounding_blocked",
                "title": "暂时无法验证事实",
                "message": "缺少可引用的来源",
                "actions": [{"id": "retry", "label": "重新检索", "style": "primary", "kind": "grounding_retry"}],
                "status": "pending",
            },
            {
                "type": "permission_result",
                "permission_request_id": "perm_1",
                "status": "success",
            },
        ]
    )

    hitl = {item["card_type"]: item for item in items if item.get("kind") == "hitl"}
    assert set(hitl) == {
        "business_confirmation",
        "user_question",
        "permission_required",
        "external_execution_required",
        "grounding_blocked",
    }
    assert hitl["business_confirmation"]["payload"]["fields"] == fields
    assert hitl["user_question"]["payload"]["options"][1]["id"] == "monthly"
    assert hitl["permission_required"]["status"] == "approved"
    assert hitl["permission_required"]["payload"]["tool_call"]["name"] == "bash"
    assert hitl["external_execution_required"]["status"] == "pending"
    assert hitl["grounding_blocked"]["payload"]["actions"][0]["id"] == "retry"
    assert any(item.get("category") == "business_confirmation" for item in items if item.get("kind") == "log")


def test_cancel_todo_items_keeps_completed_and_marks_open_items_cancelled():
    state = [{
        "kind": "todo",
        "id": "todo_current",
        "title": "任务清单",
        "todos": [
            {"content": "已完成步骤", "status": "completed"},
            {"content": "进行中步骤", "status": "in_progress"},
            {"content": "待处理步骤", "status": "pending"},
        ],
        "counts": {"pending": 1, "in_progress": 1, "completed": 1, "cancelled": 0},
    }]

    event = cancel_todo_items(state)

    assert event["type"] == "todo_update"
    assert event["todos"] == [
        {"content": "已完成步骤", "status": "completed"},
        {"content": "进行中步骤", "status": "cancelled"},
        {"content": "待处理步骤", "status": "cancelled"},
    ]
    assert event["counts"] == {
        "pending": 0,
        "in_progress": 0,
        "completed": 1,
        "cancelled": 2,
    }
    assert complete_todo_items(state) is None
    assert cancel_todo_items(state) is None


def test_complete_todo_items_keeps_cancelled_and_completes_only_open_items():
    state = [{
        "kind": "todo",
        "id": "todo_current",
        "title": "任务清单",
        "todos": [
            {"content": "已完成步骤", "status": "completed"},
            {"content": "已取消步骤", "status": "cancelled"},
            {"content": "待处理步骤", "status": "in_progress"},
        ],
    }]

    event = complete_todo_items(state)

    assert event["todos"] == [
        {"content": "已完成步骤", "status": "completed"},
        {"content": "已取消步骤", "status": "cancelled"},
        {"content": "待处理步骤", "status": "completed"},
    ]
    assert event["counts"] == {
        "pending": 0,
        "in_progress": 0,
        "completed": 2,
        "cancelled": 1,
    }


def test_last_todo_update_from_history_reads_latest_assistant_checklist():
    event = last_todo_update_from_history(
        [
            {
                "role": "assistant",
                "process_timeline": [
                    {
                        "kind": "todo",
                        "todos": [{"content": "旧任务", "status": "completed"}],
                    }
                ],
            },
            {"role": "user", "content": "继续"},
            {
                "role": "assistant",
                "process_timeline": [
                    {
                        "kind": "log",
                        "title": "提问",
                        "status": "success",
                    },
                    {
                        "kind": "todo",
                        "todos": [
                            {"content": "当前任务", "status": "in_progress"},
                            {"content": "后续任务", "status": "pending"},
                        ],
                    },
                ],
            },
        ]
    )

    assert event["todos"][0]["content"] == "当前任务"
    assert event["counts"]["in_progress"] == 1
    assert event["counts"]["pending"] == 1
    assert last_todo_update_from_history([]) is None
    assert last_todo_update_from_history([{"role": "user", "content": "hi"}]) is None


def test_latest_assistant_todo_does_not_fall_back_to_unrelated_older_task():
    history = [
        {
            "role": "assistant",
            "process_timeline": [
                {
                    "kind": "todo",
                    "todos": [{"content": "无关旧任务", "status": "in_progress"}],
                }
            ],
        },
        {"role": "user", "content": "新的任务"},
        {
            "role": "assistant",
            "content": "请确认",
            "process_timeline": [{"kind": "hitl", "card_type": "business_confirmation"}],
        },
    ]

    assert latest_assistant_todo_update_from_history(history) is None
    assert last_todo_update_from_history(history)["todos"][0]["content"] == "无关旧任务"
