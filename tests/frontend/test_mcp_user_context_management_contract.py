from pathlib import Path


COMPONENT = Path("frontend/src/components/system/McpServerRegistry.vue")


def test_mcp_registry_exposes_plaintext_user_context_configuration():
    source = COMPONENT.read_text(encoding="utf-8")

    assert "开启用户身份传递" in source
    assert "user_assertion_enabled" in source
    assert "X-Nanzi-User-Context" in source
    assert "明文 JSON" in source
    assert "不加密、不加签" in source
    assert "复制 Audience" not in source
    assert "复制 Issuer" not in source
    assert "公钥获取地址（JWKS）" not in source
    assert "一键生成调用模拟代码" not in source
    assert "NANZI_MCP_JWKS_URL" not in source
    assert "jti" not in source
    assert "字段位置" in source
    assert "是否必有" in source
    assert "业务方使用方式" in source
    assert "custom_attributes" in source
    assert "过滤规则" in source
    assert "私钥" not in source
    assert "class=\"order-2\"" in source
    assert "class=\"order-3 rounded-lg" in source


def test_mcp_registry_preserves_auth_policy_when_toggling_server_status():
    source = COMPONENT.read_text(encoding="utf-8")

    payload_builder = source[source.index("const buildServerPayload"):source.index("watch(", source.index("const buildServerPayload"))]
    assert "credential_mode" in payload_builder
    assert "user_assertion_enabled" in payload_builder
    assert "...buildServerPayload(server)" in source[source.index("const toggleServerStatus"):source.index("const fetchServerUsage")]
    assert "auth_headers: server.auth_headers || '{}'" not in source
    assert "已有认证信息会直接回显" not in source
    assert "已配置 Token 不会回显" in source
    assert "认证信息不会回显；已配置项显示为" not in source
    assert "authorizationEnabled" in source
    assert "authorizationEditing" in source
    assert "existing_server_id" in source
    assert "Bearer" in source
    assert "masked_auth_headers" in source
    assert "auth_headers_patch" in source
    assert "startAuthorizationEdit" in source


def test_mcp_registry_does_not_render_server_authentication_values():
    source = COMPONENT.read_text(encoding="utf-8")

    assert "auth_headers_configured" in source
    assert "auth_headers: server.auth_headers" not in source
    assert "已配置 Token 不会回显" in source
    assert "认证信息不会回显；已配置项显示为" not in source


def test_mcp_tool_tester_exposes_sanitized_user_assertion_status():
    source = Path("frontend/src/components/system/McpToolTester.vue").read_text(encoding="utf-8")

    assert "本次调用认证信息" in source
    assert "X-Nanzi-User-Context" in source
    assert "********" in source
    assert "完整签名值不会展示" not in source
    assert "明文 JSON" in source
    assert "mcp_auth" in source
    assert "user_assertion_sent" in source
