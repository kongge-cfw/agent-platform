import json

import pytest

from app.services.mcp.mcp_auth_policy import build_mcp_headers
from app.core.context import AgentContext, set_agent_context
from app.services.ai.tools.mcp_factory import current_mcp_agent_identity
from app.models.mcp import McpToolCache
from app.services.ai.tools.mcp_factory import McpToolFactory


pytestmark = pytest.mark.no_infrastructure


def _server(**overrides):
    values = {
        "auth_headers": json.dumps({"Authorization": "Bearer fixed-token"}),
        "credential_mode": "static",
        "user_assertion_enabled": False,
        "user_assertion_header": "X-Nanzi-User-Context",
    }
    values.update(overrides)
    return type("McpServerStub", (), values)()


def _user_info():
    return {
        "user_id": "123",
        "user_name": "zhangsan",
        "real_name": "张三",
        "role": "user",
        "extra_data": '{"region":"east","password":"drop"}',
    }


def _agent_info():
    return {
        "agent_id": "agent-1",
        "agent_version_id": "version-1",
        "agent_name": "测试助手",
    }


def _identity(headers):
    return json.loads(headers["X-Nanzi-User-Context"])


def test_static_mode_keeps_existing_auth_headers():
    headers = build_mcp_headers(
        _server(),
        user_info=_user_info(),
        agent_info=_agent_info(),
        request_id="req-1",
    )

    assert headers == {"Authorization": "Bearer fixed-token"}


def test_enabled_mode_adds_plaintext_user_identity_without_secrets():
    headers = build_mcp_headers(
        _server(user_assertion_enabled=True),
        user_info=_user_info(),
        agent_info=_agent_info(),
        request_id="req-1",
    )

    assert headers["Authorization"] == "Bearer fixed-token"
    assert headers["X-Request-ID"] == "req-1"
    payload = _identity(headers)
    assert payload["user_id"] == "123"
    assert payload["user_name"] == "zhangsan"
    assert payload["role"] == "user"
    assert payload["custom_attributes"] == {"region": "east"}
    assert payload["agent_id"] == "agent-1"
    assert "password" not in json.dumps(payload)


def test_user_identity_is_independent_of_authorization_bearer_token():
    headers = build_mcp_headers(
        _server(auth_headers="{}", user_assertion_enabled=True),
        user_info=_user_info(),
        agent_info=_agent_info(),
        request_id="req-no-bearer",
    )

    assert "Authorization" not in headers
    assert headers["X-Request-ID"] == "req-no-bearer"
    assert _identity(headers)["user_id"] == "123"


def test_enabled_mode_does_not_require_signing_keys():
    headers = build_mcp_headers(
        _server(user_assertion_enabled=True),
        user_info=_user_info(),
        agent_info=_agent_info(),
        request_id="req-1",
    )

    assert "X-Nanzi-User-Context" in headers
    assert "X-Nanzi-User-Assertion" not in headers


def test_enabled_mode_uses_default_safe_custom_attributes():
    headers = build_mcp_headers(
        _server(user_assertion_enabled=True),
        user_info={
            **_user_info(),
            "extra_data": '{"region":"east","employee_level":"L3","token":"drop"}',
        },
        agent_info=_agent_info(),
        request_id="req-1",
    )

    assert _identity(headers)["custom_attributes"] == {
        "region": "east",
        "employee_level": "L3",
    }


def test_current_mcp_agent_identity_comes_from_runtime_context():
    set_agent_context(
        AgentContext(
            agent_id="agent-runtime",
            agent_name="运行时助手",
            agent_version="v3",
            user_id=123,
            user_dimensions={
                "user_name": "zhangsan",
                "real_name": "张三",
                "extra_data": '{"region":"east"}',
            },
        )
    )
    try:
        user_info, agent_info = current_mcp_agent_identity()
    finally:
        set_agent_context(None)

    assert user_info["user_id"] == "123"
    assert user_info["user_name"] == "zhangsan"
    assert user_info["is_admin"] is False
    assert agent_info == {
        "agent_id": "agent-runtime",
        "agent_version_id": "v3",
        "agent_name": "运行时助手",
    }


@pytest.mark.asyncio
async def test_mcp_tool_forwards_runtime_identity_to_remote_call(monkeypatch):
    set_agent_context(
        AgentContext(
            agent_id="agent-runtime",
            agent_name="运行时助手",
            agent_version="v3",
            user_id=123,
            trace_id="trace-1",
            user_dimensions={"user_name": "zhangsan"},
        )
    )
    try:
        from unittest.mock import AsyncMock

        mocked_call = AsyncMock(return_value={"success": True})
        monkeypatch.setattr(
            "app.services.ai.tools.mcp_factory.McpClientService.call_remote_tool",
            mocked_call,
        )
        tool = McpToolFactory.create_tool(
            McpToolCache(
                id="tool-1",
                server_id="server-1",
                tool_name="crm:query_customer",
                tool_description="query",
                parameter_schema='{"type":"object","properties":{"customer_id":{"type":"string"}}}',
            )
        )
        await tool.ainvoke({"customer_id": "C-1"})
    finally:
        set_agent_context(None)

    mocked_call.assert_awaited_once_with(
        server_id="server-1",
        tool_name="query_customer",
        arguments={"customer_id": "C-1"},
        user_info={"user_name": "zhangsan", "user_id": "123", "is_admin": False},
        agent_info={
            "agent_id": "agent-runtime",
            "agent_name": "运行时助手",
            "agent_version_id": "v3",
        },
        request_id="trace-1",
        require_user_context=True,
    )
