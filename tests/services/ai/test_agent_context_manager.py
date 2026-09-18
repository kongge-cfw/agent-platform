import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.context import get_current_agent_context
from app.schemas.agent import ChatConfig
from app.services.ai.context_manager import AgentContextManager
from app.services.ai.turn_decision import TurnDecision

pytestmark = pytest.mark.no_infrastructure

# 32-character hex strings matching RAGFlow dataset ID regex
ID_USER_CHECKED_1 = "11111111111111111111111111111111"
ID_USER_CHECKED_2 = "22222222222222222222222222222222"
ID_AGENT_BOUND_1 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
ID_USER_PERM_1 = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
ID_USER_PERM_2 = "cccccccccccccccccccccccccccccccc"
ID_DB_ALL_1 = "dddddddddddddddddddddddddddddddd"
ID_DB_ALL_2 = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"


@pytest.mark.asyncio
async def test_resolve_without_explicit_agent_uses_main_without_router():
    main_config = ChatConfig(
        agent_id="sys-agent-chat",
        agent_name="main",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="main prompt",
        tools=[],
        capabilities=["general_chat"],
    )
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=main_config,
    ) as get_config, patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "你好"}],
            user_info=None,
        )

    assert config is main_config
    assert decision.provenance == "automatic_delegation"
    assert decision.agent_id == "sys-agent-chat"
    get_config.assert_awaited_once()
    route_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_metadata_dataset_scope_also_starts_at_main_without_data_shortcut():
    main_config = ChatConfig(
        agent_id="sys-agent-chat",
        agent_name="main",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="main prompt",
        tools=[],
        capabilities=["general_chat"],
    )
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=main_config,
    ) as get_config, patch(
        "app.services.ai.context_manager.AgentManagerService.list_agents",
        new_callable=AsyncMock,
    ) as list_agents, patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "查询销售数据"}],
            force_data_query=True,
            user_info=None,
        )

    assert config is main_config
    assert decision.provenance == "automatic_delegation"
    get_config.assert_awaited_once()
    list_agents.assert_not_awaited()
    route_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_agent_id_keeps_direct_resolution_without_default_main():
    selected_config = ChatConfig(
        agent_id="agent-selected",
        agent_name="selected-agent",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="selected prompt",
        tools=[],
        capabilities=["general_chat"],
    )
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=selected_config,
    ) as get_config, patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "请使用指定专家"}],
            agent_id="agent-selected",
            user_info=None,
        )

    assert config is selected_config
    assert decision is None
    get_config.assert_awaited_once_with(
        session_context.__aenter__.return_value,
        agent_id="agent-selected",
    )
    route_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrich_for_knowledge_turn_does_not_merge_fallback_agent_tools():
    config = ChatConfig(
        agent_id="sys-agent-chat",
        agent_name="Main",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="prompt",
        tools=[],
        capabilities=["chat"],
        engine_config={},
    )
    fallback_config = ChatConfig(
        agent_id="knowledge-base",
        agent_name="KnowledgeBase",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="kb prompt",
        tools=["search_knowledge_base"],
        capabilities=["knowledge_base"],
        engine_config={"dataset_ids": [ID_AGENT_BOUND_1]},
    )

    mock_session = AsyncMock()
    mock_session_context = MagicMock()
    mock_session_context.__aenter__.return_value = mock_session

    with patch("app.services.ai.context_manager.AsyncSessionLocal", return_value=mock_session_context), \
         patch(
             "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
             new_callable=AsyncMock,
         ) as mock_get_config:
        mock_get_config.return_value = fallback_config

        enriched = await AgentContextManager.enrich_for_knowledge_turn(
            config,
            user_query="如何安装 skills 技能呢",
        )

    mock_get_config.assert_not_called()
    assert enriched.tools == []
    assert enriched.capabilities == ["chat"]
    assert enriched.engine_config == {}


@pytest.mark.asyncio
async def test_setup_context_frontend_specified():
    # 测试前端指定了知识库，只使用前端指定的
    config = ChatConfig(
        agent_id="test-agent",
        agent_name="Test Agent",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="prompt",
        tools=[],
        capabilities=[],
        engine_config={"dataset_ids": [ID_AGENT_BOUND_1]}
    )

    await AgentContextManager.setup_context(
        config=config,
        knowledge_dataset_ids=[ID_USER_CHECKED_1, ID_USER_CHECKED_2],
        user_info={"user_id": 1, "role": "user"}
    )

    ctx = get_current_agent_context()
    assert ctx is not None
    # 仅包含前端指定的，且覆盖了智能体绑定的
    assert set(ctx.dataset_ids) == {ID_USER_CHECKED_1, ID_USER_CHECKED_2}
    assert set(ctx.knowledge_dataset_ids) == {ID_USER_CHECKED_1, ID_USER_CHECKED_2}
    # 检查是否回写回 config.engine_config
    assert set(config.engine_config.get("dataset_ids")) == {ID_USER_CHECKED_1, ID_USER_CHECKED_2}


@pytest.mark.asyncio
async def test_setup_context_keeps_authorized_attachment_paths():
    config = ChatConfig(
        agent_id="test-agent",
        agent_name="Test Agent",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="prompt",
        tools=[],
        capabilities=[],
        engine_config={"dataset_ids": [ID_AGENT_BOUND_1]},
    )

    await AgentContextManager.setup_context(
        config=config,
        user_info={"user_id": 1, "role": "user"},
        knowledge_dataset_ids=[ID_USER_CHECKED_1],
        authorized_attachment_paths=["/app/data/uploads/report.xlsx"],
        current_turn_attachment_paths=["/app/data/uploads/current.xlsx"],
    )

    ctx = get_current_agent_context()
    assert ctx is not None
    assert ctx.authorized_attachment_paths == ["/app/data/uploads/report.xlsx"]
    assert ctx.current_turn_attachment_paths == ["/app/data/uploads/current.xlsx"]

@pytest.mark.asyncio
async def test_setup_context_merges_agent_binding_with_user_permissions():
    # 未显式选择时，智能体绑定知识库与用户可访问知识库合并为检索范围
    config = ChatConfig(
        agent_id="test-agent",
        agent_name="Test Agent",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="prompt",
        tools=[],
        capabilities=[],
        engine_config={"dataset_ids": [ID_AGENT_BOUND_1]}
    )

    # Mock PermissionService.get_knowledge_base_access
    mock_access = {"is_admin": False, "accessible_ids": {ID_USER_PERM_1, ID_USER_PERM_2}}

    with patch("app.services.permission_service.PermissionService.get_knowledge_base_access", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_access

        # Mock AsyncSessionLocal 的上下文管理器
        mock_session = AsyncMock()
        mock_session_context = MagicMock()
        mock_session_context.__aenter__.return_value = mock_session

        with patch("app.services.ai.context_manager.AsyncSessionLocal", return_value=mock_session_context):
            await AgentContextManager.setup_context(
                config=config,
                knowledge_dataset_ids=None,
                user_info={"user_id": 100, "user_name": "test_user", "role": "user"}
            )

    ctx = get_current_agent_context()
    assert ctx is not None
    assert set(ctx.dataset_ids) == {ID_AGENT_BOUND_1, ID_USER_PERM_1, ID_USER_PERM_2}
    assert ctx.agent_dataset_ids == [ID_AGENT_BOUND_1]
    assert ctx.knowledge_dataset_ids == []
    assert set(config.engine_config.get("dataset_ids")) == {
        ID_AGENT_BOUND_1,
        ID_USER_PERM_1,
        ID_USER_PERM_2,
    }
    mock_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_setup_context_uses_user_permissions_when_agent_has_no_bound_dataset():
    config = ChatConfig(
        agent_id="test-agent",
        agent_name="Test Agent",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="prompt",
        tools=[],
        capabilities=[],
        engine_config={}
    )

    mock_access = {"is_admin": False, "accessible_ids": {ID_USER_PERM_1, ID_USER_PERM_2}}
    with patch("app.services.permission_service.PermissionService.get_knowledge_base_access", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_access
        mock_session = AsyncMock()
        mock_session_context = MagicMock()
        mock_session_context.__aenter__.return_value = mock_session
        with patch("app.services.ai.context_manager.AsyncSessionLocal", return_value=mock_session_context):
            await AgentContextManager.setup_context(
                config=config,
                knowledge_dataset_ids=None,
                user_info={"user_id": 100, "user_name": "test_user", "role": "user"}
            )

    ctx = get_current_agent_context()
    assert ctx is not None
    assert set(ctx.dataset_ids) == {ID_USER_PERM_1, ID_USER_PERM_2}
    assert ctx.agent_dataset_ids == []


@pytest.mark.asyncio
async def test_setup_context_user_selection_strictly_overrides_agent_dataset():
    config = ChatConfig(
        agent_id="test-agent",
        agent_name="Test Agent",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="prompt",
        tools=["search_knowledge_base"],
        capabilities=["knowledge_base"],
        engine_config={"dataset_ids": [ID_AGENT_BOUND_1]},
    )

    await AgentContextManager.setup_context(
        config=config,
        knowledge_dataset_ids=[ID_USER_CHECKED_1],
        user_info={"user_id": 100, "user_name": "test_user", "role": "user"},
    )

    ctx = get_current_agent_context()
    assert ctx is not None
    assert ctx.dataset_ids == [ID_USER_CHECKED_1]
    assert ctx.knowledge_dataset_ids == [ID_USER_CHECKED_1]
    assert ctx.agent_dataset_ids == [ID_AGENT_BOUND_1]


@pytest.mark.asyncio
async def test_setup_context_preserves_agent_grant_across_reinitialization():
    config = ChatConfig(
        agent_id="test-agent",
        agent_name="Test Agent",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="prompt",
        tools=["search_knowledge_base"],
        capabilities=["knowledge_base"],
        engine_config={"dataset_ids": [ID_AGENT_BOUND_1]},
    )

    await AgentContextManager.setup_context(
        config=config,
        knowledge_dataset_ids=[ID_USER_CHECKED_1],
        user_info={"user_id": 100, "user_name": "test_user", "role": "user"},
    )
    await AgentContextManager.setup_context(
        config=config,
        knowledge_dataset_ids=[ID_USER_CHECKED_1],
        user_info={"user_id": 100, "user_name": "test_user", "role": "user"},
    )

    ctx = get_current_agent_context()
    assert ctx is not None
    assert ctx.agent_dataset_ids == [ID_AGENT_BOUND_1]

@pytest.mark.asyncio
async def test_setup_context_admin_user():
    # 测试前端未传，管理员用户：智能体绑定知识库与管理员可访问知识库合并
    config = ChatConfig(
        agent_id="test-agent",
        agent_name="Test Agent",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="prompt",
        tools=[],
        capabilities=[],
        engine_config={"dataset_ids": [ID_AGENT_BOUND_1]}
    )

    mock_access = {"is_admin": True}

    # Mock 数据库查询结果
    mock_rows = [ID_DB_ALL_1, ID_DB_ALL_2]
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = mock_rows
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    mock_session_context = MagicMock()
    mock_session_context.__aenter__.return_value = mock_session

    with patch("app.services.permission_service.PermissionService.get_knowledge_base_access", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_access
        with patch("app.services.ai.context_manager.AsyncSessionLocal", return_value=mock_session_context):
            await AgentContextManager.setup_context(
                config=config,
                knowledge_dataset_ids=None,
                user_info={"user_id": 1, "user_name": "admin_user", "role": "admin"}
            )

    ctx = get_current_agent_context()
    assert ctx is not None
    assert set(ctx.dataset_ids) == {ID_AGENT_BOUND_1, ID_DB_ALL_1, ID_DB_ALL_2}
    assert ctx.knowledge_dataset_ids == []
    assert set(config.engine_config.get("dataset_ids")) == {
        ID_AGENT_BOUND_1,
        ID_DB_ALL_1,
        ID_DB_ALL_2,
    }
    mock_get.assert_awaited_once()


def _embed_user_info():
    return {
        "session_type": "embed",
        "embed_role_id": 12,
        "lock_entry_agent": "0",
        "created_by_user_id": 1,
        "created_by_role": "admin",
        "user_id": 1,
    }


@pytest.mark.asyncio
async def test_unlocked_embed_with_main_in_catalog_but_no_host_does_not_auto_route():
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()
    catalog = [
        SimpleNamespace(id="sys-agent-chat", name="main", is_enabled=True),
        SimpleNamespace(id="sys-agent-chatbi", name="chat-bi", is_enabled=True),
    ]

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.list_allowed_agents",
        new_callable=AsyncMock,
        return_value=catalog,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=ChatConfig(
            agent_id="sys-agent-chat",
            agent_name="main",
            model_name="DeepSeek",
            temperature=0.7,
            system_prompt="main",
            tools=[],
            capabilities=["general_chat"],
        ),
    ) as get_config, patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "你好"}],
            user_info=_embed_user_info(),
        )

    assert config is None
    assert decision is None
    get_config.assert_not_awaited()
    route_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_unlocked_embed_explicit_main_host_uses_delegation():
    main_config = ChatConfig(
        agent_id="sys-agent-chat",
        agent_name="main",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="main prompt",
        tools=[],
        capabilities=["general_chat"],
    )
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()
    catalog = [
        SimpleNamespace(id="sys-agent-chat", name="main", is_enabled=True),
        SimpleNamespace(id="sys-agent-chatbi", name="chat-bi", is_enabled=True),
    ]
    user_info = {**_embed_user_info(), "default_entry_agent_id": "sys-agent-chat"}

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.list_allowed_agents",
        new_callable=AsyncMock,
        return_value=catalog,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=main_config,
    ), patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "你好"}],
            user_info=user_info,
        )

    assert config is main_config
    assert decision.provenance == "automatic_delegation"
    route_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_unlocked_embed_single_role_agent_skips_main():
    chatbi = ChatConfig(
        agent_id="sys-agent-chatbi",
        agent_name="chat-bi",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="bi",
        tools=[],
        capabilities=["data_query"],
    )
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()
    catalog = [
        SimpleNamespace(
            id="sys-agent-chatbi",
            name="chat-bi",
            display_name="数据分析",
            is_enabled=True,
        ),
    ]

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.list_allowed_agents",
        new_callable=AsyncMock,
        return_value=catalog,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=chatbi,
    ), patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "查销售额"}],
            user_info=_embed_user_info(),
        )

    assert config is chatbi
    assert decision.provenance == "direct_agent_selection"
    route_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_unlocked_embed_multiple_agents_without_main_does_not_auto_route():
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()
    catalog = [
        SimpleNamespace(id="sys-agent-chatbi", name="chat-bi", is_enabled=True),
        SimpleNamespace(id="sys-agent-knowledge", name="knowledge-base", is_enabled=True),
    ]

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.list_allowed_agents",
        new_callable=AsyncMock,
        return_value=catalog,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=ChatConfig(
            agent_id="sys-agent-chat",
            agent_name="main",
            model_name="DeepSeek",
            temperature=0.7,
            system_prompt="main",
            tools=[],
            capabilities=["general_chat"],
        ),
    ) as get_config, patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "请假流程怎么走"}],
            user_info=_embed_user_info(),
        )

    assert config is None
    assert decision is None
    get_config.assert_not_awaited()
    route_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_unlocked_embed_default_entry_without_main_uses_that_agent():
    knowledge = ChatConfig(
        agent_id="sys-agent-knowledge",
        agent_name="knowledge-base",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="kb",
        tools=[],
        capabilities=["knowledge"],
    )
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()
    catalog = [
        SimpleNamespace(id="sys-agent-chatbi", name="chat-bi", is_enabled=True),
        SimpleNamespace(id="sys-agent-knowledge", name="knowledge-base", is_enabled=True),
    ]
    user_info = {**_embed_user_info(), "default_entry_agent_id": "sys-agent-knowledge"}

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.list_allowed_agents",
        new_callable=AsyncMock,
        return_value=catalog,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=knowledge,
    ), patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "制度怎么查"}],
            user_info=user_info,
        )

    assert config is knowledge
    assert decision.provenance == "automatic_delegation"
    route_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_unlocked_embed_default_entry_hosts_smart_delegation_instead_of_platform_main():
    host_config = ChatConfig(
        agent_id="sys-agent-chatbi",
        agent_name="chat-bi",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="bi host",
        tools=[],
        capabilities=["data_query"],
    )
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()
    catalog = [
        SimpleNamespace(id="sys-agent-chat", name="main", is_enabled=True),
        SimpleNamespace(id="sys-agent-chatbi", name="chat-bi", is_enabled=True),
    ]
    user_info = {**_embed_user_info(), "default_entry_agent_id": "sys-agent-chatbi"}

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.list_allowed_agents",
        new_callable=AsyncMock,
        return_value=catalog,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=host_config,
    ), patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "你好"}],
            user_info=user_info,
        )

    assert config is host_config
    assert decision.provenance == "automatic_delegation"
    route_query.assert_not_awaited()


def test_can_host_embed_requires_explicit_host():
    from app.services.embed_identity import can_host_smart_delegation

    main = SimpleNamespace(agent_id="sys-agent-chat", agent_name="main")
    alt = SimpleNamespace(agent_id="custom-host", agent_name="主智能体dev")
    embed = _embed_user_info()
    assert can_host_smart_delegation(main, embed) is False
    assert can_host_smart_delegation(main, {**embed, "default_entry_agent_id": "sys-agent-chat"}) is True
    assert can_host_smart_delegation(alt, {**embed, "default_entry_agent_id": "custom-host"}) is True
    assert can_host_smart_delegation(main, {**embed, "default_entry_agent_id": "custom-host"}) is False


def test_can_host_non_embed_uses_platform_main():
    from app.services.embed_identity import can_host_smart_delegation

    main = SimpleNamespace(agent_id="sys-agent-chat", agent_name="main")
    expert = SimpleNamespace(agent_id="sys-agent-chatbi", agent_name="chat-bi")
    assert can_host_smart_delegation(main, {"role": "user"}) is True
    assert can_host_smart_delegation(expert, {"role": "user"}) is False


@pytest.mark.asyncio
async def test_locked_embed_loads_locked_agent_instead_of_platform_main():
    locked_config = ChatConfig(
        agent_id="sys-agent-chatbi",
        agent_name="chat-bi",
        model_name="DeepSeek",
        temperature=0.7,
        system_prompt="bi",
        tools=[],
        capabilities=["data_query"],
    )
    session_context = MagicMock()
    session_context.__aenter__.return_value = AsyncMock()
    catalog = [SimpleNamespace(id="sys-agent-chatbi", name="chat-bi", is_enabled=True)]
    user_info = {
        **_embed_user_info(),
        "lock_entry_agent": "1",
        "agent_id": "sys-agent-chatbi",
    }

    with patch(
        "app.services.ai.context_manager.AsyncSessionLocal",
        return_value=session_context,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.list_allowed_agents",
        new_callable=AsyncMock,
        return_value=catalog,
    ), patch(
        "app.services.ai.context_manager.AgentManagerService.get_active_agent_config",
        new_callable=AsyncMock,
        return_value=locked_config,
    ), patch(
        "app.services.ai.router_service.router_service.route_query",
        new_callable=AsyncMock,
    ) as route_query:
        config, decision = await AgentContextManager.resolve_agent_config(
            messages=[{"role": "user", "content": "你好"}],
            user_info=user_info,
        )

    assert config is locked_config
    assert decision.provenance == "direct_agent_selection"
    route_query.assert_not_awaited()
