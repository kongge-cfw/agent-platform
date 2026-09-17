import json
import uuid
import pytest
from httpx import AsyncClient
from app.models.agent import AIAgent
from app.services.auth_service import AuthService
from app.core.redis import get_redis
from app.services.embed_identity import (
    build_session_owner,
    build_shadow_extra_data,
    is_platform_admin,
    locked_agent_id,
    normalize_embed_user_info,
    shadow_username,
    skip_sql_row_rewrite,
)
from app.services.embed_app_service import apply_claim_whitelist
from app.services.embed_api_guard import embed_path_allowed


def test_embed_claim_whitelist_and_mcp_only_skip_sql():
    filtered = apply_claim_whitelist(
        {
            "subject": "crm:zhangsan",
            "display_name": "张三",
            "dept_code": "SH01",
            "org_path": "yovole",
            "tenant_id": "t_1001",
            "extra_data": {"data_scope": "dept", "region": "sh"},
        },
        ["subject", "display_name", "tenant_id", "extra_data.data_scope"],
    )
    assert filtered["subject"] == "crm:zhangsan"
    assert "dept_code" not in filtered
    assert filtered["extra_data"] == {"data_scope": "dept"}
    assert filtered["tenant_id"] == "t_1001"
    owner = build_session_owner(app_key="crm_portal", subject="crm:zhangsan", fallback_user_id=9)
    assert owner.startswith("e:")
    assert skip_sql_row_rewrite({"session_type": "embed", "data_permission_mode": "mcp_only"}) is True
    assert skip_sql_row_rewrite({"session_type": "embed", "data_permission_mode": "nanzi_sql_rewrite"}) is False
    assert embed_path_allowed("GET", "/api/portal/auth/me") is True
    assert embed_path_allowed("GET", "/api/portal/skills") is True
    assert embed_path_allowed("GET", "/api/portal/skills/personal") is True
    assert embed_path_allowed("GET", "/api/portal/agents/sys-agent-chat/active-config") is False
    assert embed_path_allowed("GET", "/api/portal/management/users") is False
    assert embed_path_allowed("POST", "/api/portal/mcp/servers") is False
    assert embed_path_allowed("POST", "/api/v1/chat/completions") is True
    assert embed_path_allowed("GET", "/api/portal/workbench/home") is True
    assert embed_path_allowed("GET", "/api/portal/saved-reports") is True
    assert embed_path_allowed("GET", "/api/portal/models") is True
    assert embed_path_allowed("POST", "/api/portal/models") is False
    assert locked_agent_id({"agent_id": "sys-agent-chat"}) == "sys-agent-chat"
    assert locked_agent_id({"agent_id": "sys-agent-chat", "lock_entry_agent": "0"}) == ""
    assert locked_agent_id({"agent_id": "sys-agent-chat", "lock_entry_agent": "1"}) == "sys-agent-chat"
    assert embed_path_allowed("DELETE", "/api/portal/saved-reports/abc") is False
    assert embed_path_allowed("POST", "/api/portal/chatbi-monitors") is True
    assert embed_path_allowed("POST", "/api/portal/chatbi-export/result") is True
    assert embed_path_allowed("PUT", "/api/portal/portal-prefs/markdown-theme") is True
    assert embed_path_allowed("GET", "/api/portal/memory/my/summaries") is True
    assert embed_path_allowed("GET", "/api/portal/memory/my/summaries/conv-1") is True
    assert embed_path_allowed("DELETE", "/api/portal/memory/my/summaries/conv-1") is True
    assert embed_path_allowed("DELETE", "/api/portal/memory/my/session-memory") is True
    assert embed_path_allowed("GET", "/api/portal/memory/my/ltm") is False
    assert embed_path_allowed("GET", "/api/portal/memory/summaries") is False
    assert embed_path_allowed("DELETE", "/api/portal/memory/users/7") is False


def test_embed_identity_helpers_force_non_admin_and_stable_shadow_name():
    assert shadow_username("crm:zhangsan") == "ext:crm:zhangsan"
    payload = build_shadow_extra_data(
        subject="crm:zhangsan",
        tenant_id="t_1001",
        extra_data={"region_codes": ["310000"], "role": "admin", "is_admin": True, "permissions": ["*"]},
    )
    assert payload["external_subject"] == "crm:zhangsan"
    assert payload["tenant_id"] == "t_1001"
    assert payload["region_codes"] == ["310000"]
    assert "role" not in payload
    assert "is_admin" not in payload
    assert "permissions" not in payload

    embed_user = normalize_embed_user_info(
        {"session_type": "embed", "role": "admin", "is_admin": True, "user_name": "ext:crm:zhangsan"}
    )
    assert embed_user["role"] == "user"
    assert embed_user["is_admin"] is False
    assert is_platform_admin(embed_user) is False
    assert is_platform_admin({"role": "admin"}) is True


@pytest.mark.asyncio
async def test_embed_ticket_lifecycle(client: AsyncClient, db_session):
    """
    测试 Embed Ticket 完整生命周期：
    1. 签发 Ticket (POST /api/v1/embed/tickets)
    2. 兑换 Session Token (POST /api/v1/embed/tickets/exchange)
    3. 防重放测试 (同一 Ticket 无法兑换两次)
    4. Session Token 鉴权与滑动续期能力验证 (/api/portal/auth/me)
    """
    suffix = uuid.uuid4().hex[:8]
    # 1. 准备测试用户与操作人 Key
    admin_name = f"ticket_adm_{suffix}"
    admin_key = await AuthService.generate_api_key(
        user_name=admin_name, role="admin", db=db_session
    )

    target_user_name = f"ticket_user_{suffix}"
    target_key = await AuthService.generate_api_key(
        user_name=target_user_name,
        real_name="测试员工张三",
        role="user",
        db=db_session,
    )

    # 2. 服务端代表 target_user_name 签发 Ticket
    ticket_resp = await client.post(
        "/api/v1/embed/tickets",
        json={
            "username": target_user_name,
            "agent_id": "sys-agent-chatbi",
            "expires_in": 300,
        },
        headers={"X-API-Key": admin_key},
    )
    assert ticket_resp.status_code == 200
    ticket_data = ticket_resp.json()
    assert ticket_data["code"] == 200
    assert "ticket" in ticket_data["data"]
    ticket_str = ticket_data["data"]["ticket"]
    assert ticket_str.startswith("emt_")
    assert ticket_data["data"]["target_user"]["user_name"] == target_user_name

    # 3. 前端 iframe 调用兑换接口换取 Session Token
    exchange_resp = await client.post(
        "/api/v1/embed/tickets/exchange",
        json={"ticket": ticket_str},
    )
    assert exchange_resp.status_code == 200
    session_data = exchange_resp.json()
    assert session_data["code"] == 200
    assert "session_token" in session_data["data"]
    session_token = session_data["data"]["session_token"]
    assert session_token.startswith("emb_ses_")
    assert session_data["data"]["user_info"]["user_name"] == target_user_name
    assert session_data["data"]["user_info"]["real_name"] == "测试员工张三"

    # 4. 防重放校验：再次使用该 ticket 兑换应立即失败 (400)
    replay_resp = await client.post(
        "/api/v1/embed/tickets/exchange",
        json={"ticket": ticket_str},
    )
    assert replay_resp.status_code == 400
    assert "not found" in replay_resp.text.lower() or "expired" in replay_resp.text.lower()

    # 5. 使用兑换出的 session_token 调用受保护接口验证鉴权
    me_resp = await client.get(
        "/api/portal/auth/me",
        headers={"X-API-Key": session_token},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["data"]["user_name"] == target_user_name
    assert me_data["data"]["real_name"] == "测试员工张三"

    # 6. 验证滑动续期：请求后 Redis TTL 应被维持在 ~86400 秒 (24 小时)
    r = await get_redis()
    if r:
        from app.utils.encryption import get_api_key_manager

        manager = get_api_key_manager()
        h = manager.hash_api_key(session_token)
        ttl = await r.ttl(f"auth:api_key:{h}")
        assert ttl > 80000  # 接近 86400 秒 (24 小时)


@pytest.mark.asyncio
async def test_embed_ticket_invalid_user_and_token(client: AsyncClient, db_session):
    """
    测试边界与异常场景：
    - 管理员调用但目标用户不存在时报错 404
    - 伪造 ticket 兑换报错 400
    """
    # 1. 管理员调用但目标用户不存在，应返回 404
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"ticket_adm404_{suffix}"
    admin_key = await AuthService.generate_api_key(
        user_name=admin_name, role="admin", db=db_session
    )
    not_found_resp = await client.post(
        "/api/v1/embed/tickets",
        json={"username": "non_existent_user_999"},
        headers={"X-API-Key": admin_key},
    )
    assert not_found_resp.status_code == 404

    # 2. 伪造 Ticket 兑换，应返回 400
    bad_resp = await client.post(
        "/api/v1/embed/tickets/exchange",
        json={"ticket": "emt_fake_ticket_123"},
    )
    assert bad_resp.status_code == 400


@pytest.mark.asyncio
async def test_embed_ticket_impersonation_permissions(client: AsyncClient, db_session):
    """
    测试代客签发 (Impersonation) 权限边界：
    1. 普通用户为自身签发 Ticket -> 200 成功
    2. 普通用户不传参数签发 Ticket (默认自身) -> 200 成功
    3. 普通用户尝试为他人签发 (无 GET:/api/v1/users/profile 权限) -> 403 拒绝
    4. 普通用户获得 GET:/api/v1/users/profile 权限后代他人签发 -> 200 成功
    """
    from app.services.permission_service import PermissionService
    from app.schemas.permission import PermissionUpdate

    suffix = uuid.uuid4().hex[:8]
    # 创建两个普通用户和一个管理员
    user_a_name = f"user_a_{suffix}"
    user_a_key = await AuthService.generate_api_key(
        user_name=user_a_name, role="user", db=db_session
    )

    user_b_name = f"user_b_{suffix}"
    user_b_key = await AuthService.generate_api_key(
        user_name=user_b_name, role="user", db=db_session
    )

    # 获取 user_a 的实际 ID
    user_a_info = await AuthService.verify_api_key(user_a_key, db=db_session)
    user_a_id = int(user_a_info["user_id"])

    # 1. user_a 为自己签发 (传自己用户名) -> 应该 200 成功
    self_resp1 = await client.post(
        "/api/v1/embed/tickets",
        json={"username": user_a_name},
        headers={"X-API-Key": user_a_key},
    )
    assert self_resp1.status_code == 200
    assert self_resp1.json()["data"]["target_user"]["user_name"] == user_a_name

    # 2. user_a 为自己签发 (不传 username/user_id，默认自身) -> 应该 200 成功
    self_resp2 = await client.post(
        "/api/v1/embed/tickets",
        json={},
        headers={"X-API-Key": user_a_key},
    )
    assert self_resp2.status_code == 200
    assert self_resp2.json()["data"]["target_user"]["user_name"] == user_a_name

    # 3. user_a 试图为 user_b 代客签发（此时 user_a 无 GET:/api/v1/users/profile 权限）-> 应该 403 拒绝
    impersonate_resp = await client.post(
        "/api/v1/embed/tickets",
        json={"username": user_b_name},
        headers={"X-API-Key": user_a_key},
    )
    assert impersonate_resp.status_code == 403
    assert "permission denied" in impersonate_resp.text.lower() or "GET:/api/v1/users/profile" in impersonate_resp.text

    # 4. 授予 user_a 'GET:/api/v1/users/profile' API 权限
    perm_service = PermissionService(db_session)
    await perm_service.update_user_permissions(
        user_id=user_a_id,
        permissions=PermissionUpdate(apis=["GET:/api/v1/users/profile"]),
    )

    # 5. user_a 再次为 user_b 代客签发 -> 应该 200 成功
    authorized_impersonate_resp = await client.post(
        "/api/v1/embed/tickets",
        json={"username": user_b_name},
        headers={"X-API-Key": user_a_key},
    )
    assert authorized_impersonate_resp.status_code == 200
    assert authorized_impersonate_resp.json()["data"]["target_user"]["user_name"] == user_b_name


@pytest.mark.asyncio
async def test_embed_ticket_identity_jit_shadow_and_lock(client: AsyncClient, db_session):
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"ticket_id_adm_{suffix}"
    admin_key = await AuthService.generate_api_key(
        user_name=admin_name, role="admin", db=db_session
    )
    agent = AIAgent(
        id=str(uuid.uuid4()),
        name=f"embed-id-{suffix}",
        display_name="业务嵌入专家",
        description="test",
        is_system=True,
        is_enabled=True,
        engine_type="LOCAL",
        capabilities=["data_query"],
        created_by="admin",
    )
    db_session.add(agent)
    await db_session.commit()

    missing_agent = await client.post(
        "/api/v1/embed/tickets",
        json={
            "identity": {"subject": "crm:zhangsan", "display_name": "张三"},
        },
        headers={"X-API-Key": admin_key},
    )
    assert missing_agent.status_code == 400

    ticket_resp = await client.post(
        "/api/v1/embed/tickets",
        json={
            "agent_id": agent.id,
            "identity": {
                "subject": f"crm:zhangsan_{suffix}",
                "display_name": "张三",
                "dept_code": "SH01",
                "org_path": "yovole/sh/dc1",
                "tenant_id": "t_1001",
                "extra_data": {
                    "region_codes": ["310000"],
                    "role": "admin",
                    "is_admin": True,
                },
            },
        },
        headers={"X-API-Key": admin_key},
    )
    assert ticket_resp.status_code == 200
    data = ticket_resp.json()["data"]
    assert data["target_user"]["user_name"].startswith("ext:")
    assert data["target_user"]["subject"] == f"crm:zhangsan_{suffix}"

    exchange_resp = await client.post(
        "/api/v1/embed/tickets/exchange",
        json={"ticket": data["ticket"]},
    )
    assert exchange_resp.status_code == 200
    session = exchange_resp.json()["data"]
    assert session["agent_id"] == agent.id
    assert session["user_info"]["role"] == "user"
    assert session["user_info"]["subject"] == f"crm:zhangsan_{suffix}"
    session_token = session["session_token"]

    me_resp = await client.get(
        "/api/portal/auth/me",
        headers={"X-API-Key": session_token},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()["data"]
    assert me_data["role"] == "user"
    extra = me_data.get("extra_data") or ""
    if isinstance(extra, str) and extra:
        parsed = json.loads(extra)
        assert parsed.get("external_subject") == f"crm:zhangsan_{suffix}"
        assert parsed.get("tenant_id") == "t_1001"
        assert parsed.get("region_codes") == ["310000"]
        assert "role" not in parsed
        assert parsed.get("is_admin") is not True


@pytest.mark.asyncio
async def test_embed_app_policy_whitelist_lock_and_api_isolation(client: AsyncClient, db_session):
    from app.models.embed_app import SysEmbedApp
    from app.models.permission import ResourcePermission, Role

    suffix = uuid.uuid4().hex[:8]
    admin_name = f"ticket_app_adm_{suffix}"
    admin_key = await AuthService.generate_api_key(
        user_name=admin_name, role="admin", db=db_session
    )
    agent = AIAgent(
        id=str(uuid.uuid4()),
        name=f"embed-app-{suffix}",
        display_name="应用嵌入专家",
        description="test",
        is_system=True,
        is_enabled=True,
        engine_type="LOCAL",
        capabilities=["data_query"],
        created_by="admin",
    )
    other = AIAgent(
        id=str(uuid.uuid4()),
        name=f"embed-app-other-{suffix}",
        display_name="未授权专家",
        description="test",
        is_system=True,
        is_enabled=True,
        engine_type="LOCAL",
        capabilities=["data_query"],
        created_by="admin",
    )
    role = Role(code=f"emb_{suffix}"[:50], name=f"嵌入角色{suffix}"[:50])
    db_session.add_all([agent, other, role])
    await db_session.flush()
    db_session.add(
        ResourcePermission(
            role_id=role.id,
            resource_type="agent",
            resource_id=agent.id,
            enabled=True,
        )
    )
    app = SysEmbedApp(
        id=str(uuid.uuid4()),
        app_key=f"crm_{suffix}"[:32],
        name="CRM",
        role_id=role.id,
        lock_entry_agent=False,
        allowed_origins=json.dumps(["https://crm.example.com"]),
        require_identity=True,
        claim_keys=json.dumps(["subject", "display_name", "tenant_id", "extra_data.data_scope"]),
        data_permission_mode="mcp_only",
        is_active=True,
    )
    locked_app = SysEmbedApp(
        id=str(uuid.uuid4()),
        app_key=f"crml_{suffix}"[:32],
        name="CRM锁定",
        role_id=role.id,
        lock_entry_agent=True,
        allowed_origins=json.dumps(["https://crm.example.com"]),
        require_identity=True,
        claim_keys=json.dumps(["subject", "tenant_id"]),
        data_permission_mode="mcp_only",
        is_active=True,
    )
    db_session.add_all([app, locked_app])
    await db_session.commit()

    missing_identity = await client.post(
        "/api/v1/embed/tickets",
        json={"app_key": app.app_key, "agent_id": agent.id},
        headers={"X-API-Key": admin_key},
    )
    assert missing_identity.status_code == 400

    missing_locked_agent = await client.post(
        "/api/v1/embed/tickets",
        json={
            "app_key": locked_app.app_key,
            "identity": {"subject": f"crm:lock_{suffix}", "tenant_id": "t_1"},
        },
        headers={"X-API-Key": admin_key},
    )
    assert missing_locked_agent.status_code == 400

    other_agent = await client.post(
        "/api/v1/embed/tickets",
        json={
            "app_key": app.app_key,
            "agent_id": other.id,
            "identity": {"subject": f"crm:u_{suffix}", "tenant_id": "t_1"},
        },
        headers={"X-API-Key": admin_key},
    )
    assert other_agent.status_code == 400

    ticket_resp = await client.post(
        "/api/v1/embed/tickets",
        json={
            "app_key": app.app_key,
            "identity": {
                "subject": f"crm:u_{suffix}",
                "display_name": "用户",
                "dept_code": "SHOULD_DROP",
                "tenant_id": "t_1001",
                "extra_data": {"data_scope": "dept", "region": "sh"},
            },
        },
        headers={"X-API-Key": admin_key},
    )
    assert ticket_resp.status_code == 200
    data = ticket_resp.json()["data"]
    assert data["target_user"]["user_name"].startswith("ext:")
    assert data["target_user"].get("app_key") == app.app_key
    assert data["target_user"].get("session_owner", "").startswith("e:")

    exchange_resp = await client.post(
        "/api/v1/embed/tickets/exchange",
        json={"ticket": data["ticket"]},
        headers={"Origin": "https://crm.example.com"},
    )
    assert exchange_resp.status_code == 200
    session = exchange_resp.json()["data"]
    assert session.get("agent_id") in (None, "")
    assert session.get("lock_entry_agent") is False
    session_token = session["session_token"]

    blocked = await client.get(
        "/api/portal/management/users",
        headers={"X-API-Key": session_token},
    )
    assert blocked.status_code == 403

    allowed_me = await client.get(
        "/api/portal/auth/me",
        headers={"X-API-Key": session_token},
    )
    assert allowed_me.status_code == 200
    extra = allowed_me.json()["data"].get("extra_data") or ""
    if isinstance(extra, str) and extra:
        parsed = json.loads(extra)
        assert parsed.get("data_scope") == "dept"
        assert "region" not in parsed


@pytest.mark.asyncio
async def test_embed_ticket_identity_requires_impersonation(client: AsyncClient, db_session):
    suffix = uuid.uuid4().hex[:8]
    user_key = await AuthService.generate_api_key(
        user_name=f"ticket_id_user_{suffix}", role="user", db=db_session
    )
    agent = AIAgent(
        id=str(uuid.uuid4()),
        name=f"embed-id-deny-{suffix}",
        display_name="受限嵌入专家",
        description="test",
        is_system=True,
        is_enabled=True,
        engine_type="LOCAL",
        capabilities=["data_query"],
        created_by="admin",
    )
    db_session.add(agent)
    await db_session.commit()

    denied = await client.post(
        "/api/v1/embed/tickets",
        json={
            "agent_id": agent.id,
            "identity": {"subject": f"crm:other_{suffix}", "display_name": "李四"},
        },
        headers={"X-API-Key": user_key},
    )
    assert denied.status_code == 403


