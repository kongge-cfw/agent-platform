import json

import httpx
import pytest

from app.services.mcp import echo_server
from app.services.mcp.echo_server import (
    build_echo_diagnostics,
    echo_mcp,
    echo_mcp_lifespan,
)
from app.services.mcp.user_context_assertion import build_user_identity_payload


pytestmark = pytest.mark.no_infrastructure


def test_echo_transport_security_uses_public_url_host_and_origin():
    security = echo_server.build_echo_transport_security("http://103.79.25.80:8001")

    assert security is not None
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["103.79.25.80:8001"]
    assert security.allowed_origins == ["http://103.79.25.80:8001"]


def test_echo_transport_security_supports_https_domain_without_port():
    security = echo_server.build_echo_transport_security("https://mcp.example.com/")

    assert security is not None
    assert security.allowed_hosts == ["mcp.example.com"]
    assert security.allowed_origins == ["https://mcp.example.com"]


@pytest.mark.parametrize("public_url", ["", "not-a-url", "ftp://mcp.example.com", "https:///missing-host"])
def test_echo_transport_security_ignores_invalid_public_url(public_url):
    assert echo_server.build_echo_transport_security(public_url) is None


def test_echo_base_url_prefers_valid_public_url_and_falls_back_for_invalid_url():
    assert echo_server.resolve_echo_base_url(
        "http://proxy.internal:8001/",
        "https://mcp.example.com/",
    ) == "https://mcp.example.com"
    assert echo_server.resolve_echo_base_url(
        "http://proxy.internal:8001/",
        "not-a-url",
    ) == "http://proxy.internal:8001"


def _server(**overrides):
    values = {
        "auth_headers": json.dumps({"Authorization": "Bearer echo-token"}),
        "fixed_token_encrypted": None,
        "credential_mode": "static",
        "user_assertion_enabled": True,
    }
    values.update(overrides)
    return type("McpServerStub", (), values)()


def _identity_header(*, request_id="req-echo-1"):
    return json.dumps(
        build_user_identity_payload(
            user_info={
                "user_id": "123",
                "user_name": "zhangsan",
                "real_name": "张三",
                "dept_code": "D001",
                "extra_data": {"region": "east", "employee_level": "L3"},
            },
            agent_info={
                "agent_id": "agent-001",
                "agent_version_id": "version-001",
                "agent_name": "测试助手",
            },
            request_id=request_id,
        ),
        ensure_ascii=True,
        separators=(",", ":"),
    )


def test_echo_diagnostics_returns_verified_identity_without_raw_credentials():
    identity = _identity_header()
    authorization = "Bearer echo-token"

    result = build_echo_diagnostics(
        headers={
            "Authorization": authorization,
            "X-Nanzi-User-Context": identity,
            "X-Request-ID": "req-echo-1",
        },
        server=_server(),
    )

    diagnostics = result["diagnostics"]
    assert result["message"] == "已收到"
    assert diagnostics["authorization_valid"] is True
    assert diagnostics["authorization_masked"] == "Bearer echo***oken"
    assert diagnostics["user_assertion_received"] is True
    assert diagnostics["user_assertion_valid"] is True
    assert diagnostics["request_id_received"] is True
    assert diagnostics["processing_log"] == [
        "已收到 Authorization 请求头",
        "Authorization Bearer Token 校验通过",
        "已收到 X-Nanzi-User-Context 请求头",
        "已解析明文用户身份",
        "已解析用户、扩展字段、智能体和请求信息",
    ]
    assert diagnostics["verified_user_id"] == "123"
    assert diagnostics["verified_user_context"] == {
        "user_id": "123",
        "user_name": "zhangsan",
        "real_name": "张三",
        "dept_code": "D001",
    }
    assert diagnostics["verified_agent_context"] == {
        "agent_id": "agent-001",
        "agent_version_id": "version-001",
        "agent_name": "测试助手",
    }
    assert diagnostics["custom_attributes"] == {
        "region": "east",
        "employee_level": "L3",
    }
    serialized = json.dumps(result, ensure_ascii=False)
    assert authorization not in serialized


def test_echo_diagnostics_reports_missing_optional_user_assertion():
    result = build_echo_diagnostics(
        headers={"Authorization": "Bearer echo-token"},
        server=_server(),
    )

    assert result["diagnostics"] == {
        "authorization_valid": True,
        "authorization_masked": "Bearer echo***oken",
        "user_assertion_received": False,
        "user_assertion_valid": False,
        "user_assertion_masked": None,
        "request_id_received": False,
        "processing_log": [
            "已收到 Authorization 请求头",
            "Authorization Bearer Token 校验通过",
            "未收到 X-Nanzi-User-Context 请求头",
        ],
    }


def test_echo_diagnostics_rejects_invalid_authorization():
    with pytest.raises(PermissionError, match="Authorization"):
        build_echo_diagnostics(
            headers={"Authorization": "Bearer wrong-token"},
            server=_server(),
        )


def test_echo_diagnostics_rejects_invalid_user_identity():
    with pytest.raises(PermissionError, match="用户身份"):
        build_echo_diagnostics(
            headers={
                "Authorization": "Bearer echo-token",
                "X-Nanzi-User-Context": "not-json",
            },
            server=_server(),
        )


@pytest.mark.asyncio
async def test_streamable_http_app_has_initialized_task_group_inside_host_lifespan():
    async with echo_mcp_lifespan():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=echo_mcp.streamable_http_app()),
            base_url="http://echo.test",
        ) as client:
            response = await client.get("/mcp")

    assert response.status_code != 500
    assert "Task group is not initialized" not in response.text
