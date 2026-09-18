"""Regression tests for the server-side user-question cancellation short circuit."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai.agent_service import AgentService


pytestmark = pytest.mark.no_infrastructure


@pytest.mark.asyncio
async def test_cancelled_user_question_stops_before_agent_resolution():
    class FakeQuestionStore:
        async def submit_answer(self, **kwargs):
            assert kwargs["cancelled"] is True
            return {"status": "cancelled"}

    service = AgentService()
    receipt = (
        "【用户回答】\n"
        "interaction_type: question\n"
        "question_id: uq_cancel\n"
        "selected_option_ids: []\n"
        "custom_input: \n"
        "cancelled: true"
    )

    with (
        patch.object(service, "_quota_block_message", AsyncMock(return_value=None)),
        patch(
            "app.services.ai.agent_service.memory_service.get_history",
            AsyncMock(return_value=[]),
        ) as get_history,
        patch(
            "app.services.ai.agent_service.memory_service.add_message",
            AsyncMock(),
        ) as add_message,
        patch(
            "app.services.ai.user_question_store.UserQuestionStore.from_runtime",
            AsyncMock(return_value=FakeQuestionStore()),
        ),
        patch(
            "app.services.ai.context_manager.AgentContextManager.resolve_agent_config",
            AsyncMock(),
        ) as resolve_agent_config,
        patch(
            "app.services.ai.agent_service.AuditManager.log_transaction",
            AsyncMock(),
        ),
        patch(
            "app.services.config_service.ConfigService.get",
            AsyncMock(return_value="20"),
        ),
        patch(
            "app.core.redis.get_redis",
            AsyncMock(return_value=None),
        ),
    ):
        chunks = [
            chunk
            async for chunk in service.chat_completion_stream(
                [{"role": "user", "content": receipt}],
                conversation_id="conversation-cancel",
                user_info={"user_id": "100", "role": "admin"},
                enable_multi_agent=False,
            )
        ]

    assert chunks[-1]["content"] == "已取消本次提问，本次任务已停止。"
    assert chunks[-1]["status"] == "success"
    resolve_agent_config.assert_not_awaited()
    get_history.assert_awaited_once()
    await asyncio.sleep(0)
    assert add_message.await_count == 2


@pytest.mark.asyncio
async def test_cancelled_user_question_cancels_open_todos_from_previous_turn():
    class FakeQuestionStore:
        async def submit_answer(self, **kwargs):
            return {"status": "cancelled"}

    history = [
        {
            "role": "assistant",
            "content": "请选择统计维度",
            "process_timeline": [
                {
                    "kind": "todo",
                    "id": "todo_current",
                    "title": "任务清单",
                    "todos": [
                        {"content": "读取并分析彭州6月超维Excel数据", "status": "completed"},
                        {"content": "按企业维度汇总问题、细化车/人信息并生成整改建议", "status": "completed"},
                        {"content": "使用统一社会信用代码重新解析6家企业的enterpriseId", "status": "in_progress"},
                        {"content": "创建整改任务（含各企业明细）并下发", "status": "pending"},
                    ],
                }
            ],
        }
    ]
    service = AgentService()
    receipt = (
        "【用户回答】\n"
        "interaction_type: question\n"
        "question_id: uq_cancel_todos\n"
        "selected_option_ids: []\n"
        "custom_input: \n"
        "cancelled: true"
    )

    with (
        patch.object(service, "_quota_block_message", AsyncMock(return_value=None)),
        patch(
            "app.services.ai.agent_service.memory_service.get_history",
            AsyncMock(return_value=history),
        ),
        patch(
            "app.services.ai.agent_service.memory_service.add_message",
            AsyncMock(),
        ) as add_message,
        patch(
            "app.services.ai.user_question_store.UserQuestionStore.from_runtime",
            AsyncMock(return_value=FakeQuestionStore()),
        ),
        patch(
            "app.services.ai.context_manager.AgentContextManager.resolve_agent_config",
            AsyncMock(),
        ) as resolve_agent_config,
        patch(
            "app.services.ai.agent_service.AuditManager.log_transaction",
            AsyncMock(),
        ),
        patch(
            "app.services.config_service.ConfigService.get",
            AsyncMock(return_value="20"),
        ),
        patch(
            "app.core.redis.get_redis",
            AsyncMock(return_value=None),
        ),
    ):
        chunks = [
            chunk
            async for chunk in service.chat_completion_stream(
                [{"role": "user", "content": receipt}],
                conversation_id="conversation-cancel-todos",
                user_info={"user_id": "100", "role": "admin"},
                enable_multi_agent=False,
            )
        ]

    resolve_agent_config.assert_not_awaited()
    todo_events = [chunk for chunk in chunks if chunk.get("type") == "todo_update"]
    assert todo_events
    statuses = {item["content"]: item["status"] for item in todo_events[-1]["todos"]}
    assert statuses["读取并分析彭州6月超维Excel数据"] == "completed"
    assert statuses["按企业维度汇总问题、细化车/人信息并生成整改建议"] == "completed"
    assert statuses["使用统一社会信用代码重新解析6家企业的enterpriseId"] == "cancelled"
    assert statuses["创建整改任务（含各企业明细）并下发"] == "cancelled"
    await asyncio.sleep(0)
    persisted_todos = []
    for call in add_message.await_args_list:
        for item in call.kwargs.get("process_timeline") or []:
            if item.get("kind") == "todo":
                persisted_todos = item["todos"]
    assert persisted_todos
    assert persisted_todos[2]["status"] == "cancelled"
    assert persisted_todos[3]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancelled_business_confirmation_stops_before_agent_resolution():
    service = AgentService()
    receipt = (
        "【业务确认】用户已取消\n"
        "confirmation_id: bc_cancel\n"
        "请立即终止本次录入/变更："
        "不要调用写入类工具；"
        "禁止再次调用 request_user_confirmation（不要重新弹确认卡）。"
    )

    with (
        patch.object(service, "_quota_block_message", AsyncMock(return_value=None)),
        patch(
            "app.services.ai.agent_service.memory_service.get_history",
            AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.ai.agent_service.memory_service.add_message",
            AsyncMock(),
        ),
        patch(
            "app.services.ai.context_manager.AgentContextManager.resolve_agent_config",
            AsyncMock(),
        ) as resolve_agent_config,
        patch(
            "app.services.ai.agent_service.AuditManager.log_transaction",
            AsyncMock(),
        ),
        patch(
            "app.services.config_service.ConfigService.get",
            AsyncMock(return_value="20"),
        ),
        patch(
            "app.core.redis.get_redis",
            AsyncMock(return_value=None),
        ),
    ):
        chunks = [
            chunk
            async for chunk in service.chat_completion_stream(
                [{"role": "user", "content": receipt}],
                conversation_id="conversation-confirm-cancel",
                user_info={"user_id": "100", "role": "admin"},
                enable_multi_agent=False,
            )
        ]

    texts = [str(chunk.get("content") or "") for chunk in chunks]
    assert "已取消本次业务确认，本次任务已停止。" in texts
    resolve_agent_config.assert_not_awaited()


