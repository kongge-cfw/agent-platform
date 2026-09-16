from pathlib import Path

import pytest


pytestmark = pytest.mark.no_infrastructure


def test_business_mcp_identity_is_plaintext_header_not_signed_assertion():
    policy = Path("app/services/mcp/mcp_auth_policy.py").read_text(encoding="utf-8")
    payload = Path("app/services/mcp/user_context_assertion.py").read_text(encoding="utf-8")

    assert "X-Nanzi-User-Context" in policy
    assert "build_user_identity_payload" in policy
    assert "issue_user_assertion(" not in policy.split("def build_mcp_headers", 1)[1]
    assert "def build_user_identity_payload" in payload
    assert "不要从参数中的 `user_id` 判断当前操作人" not in policy


def test_business_mcp_identity_keeps_identity_out_of_tool_arguments():
    client = Path("app/services/ai/tools/mcp_client.py").read_text(encoding="utf-8")

    assert "build_mcp_headers" in client
    assert "auth_headers" in client
