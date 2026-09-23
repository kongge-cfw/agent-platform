"""Embed routing preference and integration lock source contracts."""

from pathlib import Path

import pytest


pytestmark = pytest.mark.no_infrastructure

ROOT = Path(__file__).resolve().parents[2]
EMBED = ROOT / "frontend/src/views/EmbedChat.vue"
SETTINGS = ROOT / "frontend/src/components/embed/ChatSettings.vue"


def test_embed_loads_and_saves_user_routing_preference_through_redis_api():
    source = EMBED.read_text(encoding="utf-8")

    assert "fetchUserPortalPreferences" in source
    assert "/api/portal/portal-prefs" in source
    assert "/api/portal/portal-prefs/routing" in source
    assert "routing_mode" in source
    assert "expert_agent_id" in source
    assert "routing_configured" in source
    assert 'localStorage.getItem("yovole_routing_mode")' not in source
    assert 'localStorage.getItem("yovole_expert_agent_id")' not in source


def test_settings_has_auto_and_default_agent_tabs():
    source = SETTINGS.read_text(encoding="utf-8")

    assert "主专家自动委派" in source
    assert "默认智能体" in source
    assert "routingLocked" in source
    assert "allowedAgents" in source
    assert "switch-to-auto" in source
    assert "switch-to-expert" in source


def test_clicking_default_agent_tab_waits_for_explicit_agent_selection():
    source = SETTINGS.read_text(encoding="utf-8")
    routing_handler = source.split("const handleSetRoutingMode", 1)[1].split(
        "const handleSetExpertAgent", 1
    )[0]

    assert "const routingMode = ref" in source
    assert "routingMode.value = 'expert'" in routing_handler
    assert "allowedAgents?.[0]?.id" not in routing_handler
    expert_branch = routing_handler.split("if (mode === 'auto')", 1)[1].split(
        "return;", 1
    )[1]
    assert "saveAndClose();" not in expert_branch
    assert 'v-if="routingMode === \'expert\' || !hasMainAgent"' in source


def test_clicking_auto_routing_keeps_settings_open_for_further_choice():
    source = SETTINGS.read_text(encoding="utf-8")
    routing_handler = source.split("const handleSetRoutingMode", 1)[1].split(
        "const handleSetExpertAgent", 1
    )[0]
    auto_branch = routing_handler.split("if (mode === 'auto')", 1)[1]
    assert "hasMainAgent.value" in auto_branch
    assert "routingMode.value = 'auto'" in auto_branch
    assert "emit('switch-to-auto')" in auto_branch
    assert "saveAndClose();" not in auto_branch


def test_setting_changes_save_without_closing_the_settings_modal():
    source = SETTINGS.read_text(encoding="utf-8")
    script = source.split("</script>", 1)[0]

    assert "const saveSettings = () =>" in script
    assert "const saveAndClose =" not in script
    assert "const close = () => emit('update:visible', false);" in script

    setting_handlers = script.split("const handleSetTheme", 1)[1].split(
        "const showConfirmModal", 1
    )[0]
    assert "saveAndClose" not in setting_handlers
    assert setting_handlers.count("saveSettings();") >= 10


def test_routing_mode_help_text_explains_latency_and_delegation():
    source = SETTINGS.read_text(encoding="utf-8")

    assert "主专家自动委派" in source
    assert "未指定专家时，默认由主专家直接回答，或按任务需要自动委派其他智能体" in source
    assert "先识别问题意图，再选择合适的主智能体" not in source
    assert "可能增加一次路由判断耗时" not in source
    assert "主专家仍可按任务需要调用其他智能体" in source


def test_unconfigured_routing_defaults_to_auto_only_when_role_has_main():
    source = EMBED.read_text(encoding="utf-8")

    assert "applyUnlockedRoutingFromCatalog" in source
    assert "roleHasMainAgent" in source
    assert "isMainGeneralAgent" in source
    assert "isEmbedDelegationSession" in source
    assert "strict-delegation-host" in source
    helper = source.split("const applyUnlockedRoutingFromCatalog", 1)[1].split(
        "const isGeneralAgentMessage",
        1,
    )[0]
    assert "saved.routing_configured" in helper
    assert "catalogHasDelegationHost" in helper
    assert "resolveDelegationHostAgent" in helper
    assert "defaultEntryAgentId" in helper
    assert "hostMode" in helper
    assert "canSmartDelegate" in source
    host_util = (ROOT / "frontend/src/utils/delegationHost.ts").read_text(encoding="utf-8")
    assert "mode?.strict" in host_util
    assert "不回落平台 Main" in host_util
    assert 'config.routingMode = "auto"' in helper
    assert 'config.routingMode = "expert"' in helper
    assert "experts.length === 1" in helper
    assert "当前嵌入应用未配置智能委派宿主，请选择一个专家" in source
    assert "请先选择一个专家再提问" in source


def test_integration_agent_lock_covers_all_host_entry_points():
    source = EMBED.read_text(encoding="utf-8")

    assert "integrationAgentLockId" in source
    assert "applyIntegrationAgentLock" in source
    assert "data.agent_id" in source
    assert "sessionData.agent_id" in source
    assert "isRoutingSettingsLocked" in source
    assert ':routing-locked="isRoutingSettingsLocked"' in source

    init_segment = source.split("const applyInitConfigPayload", 1)[1].split("if (data.conversation_id)", 1)[0]
    assert "applyIntegrationAgentLock(agentId)" in init_segment
    assert "switchToExpert(agentId)" not in init_segment

    ticket_segment = source.split("const exchangeTicketAndApply", 1)[1].split("const postInitSuccess", 1)[0]
    assert "lockEntryAgent" in ticket_segment
    assert "applyIntegrationAgentLock(sessionData.agent_id)" in ticket_segment


def test_locked_agent_does_not_persist_as_user_default():
    source = EMBED.read_text(encoding="utf-8")

    assert "if (isRoutingSettingsLocked.value) return" in source
    assert 'axios.put("/api/portal/portal-prefs/routing"' in source
    assert "config.expertAgentId = normalizedAgentId" in source
    lock_function = source.split("const applyIntegrationAgentLock", 1)[1].split("const pinnedAgentLabel", 1)[0]
    assert "saveRoutingSettings();" not in lock_function


def test_embed_apps_binds_role_instead_of_agent_whitelist():
    apps = ROOT / "frontend/src/views/EmbedApps.vue"
    api = ROOT / "frontend/src/api/embedApp.ts"
    view = apps.read_text(encoding="utf-8")
    source = api.read_text(encoding="utf-8")
    assert "allowed_agent_ids" not in view
    assert "allowed_agent_ids" not in source
    assert "lock_entry_agent" in view
    assert "关联角色" in view
    assert "请选择角色" in view
    assert "请选择关联角色" in view
    assert "关联角色" in view
    assert "请选择角色" in view
    assert "请选择关联角色" in view
    assert "智能委派宿主" in view
    assert "可作为替代主助手" in view
    assert "未指定（不启用智能委派）" in view
    assert "请在此选中它" in view
    assert "角色含平台主助手则由其委派" not in view
    assert "role-agent-options" in source
    assert "default_entry_agent_id" in view
    assert "default_entry_agent_id" in source
    assert "fetchRoleAgentOptions" in view
    assert "不绑定" not in view
    assert "签发人权限" not in view
    assert "role-options" in source
    assert "fetchAgents" not in view
    assert "toggleAgent" not in view
    assert "允许宿主声明的身份字段" not in view
    assert "toggleClaim" not in view
    assert "STANDARD_CLAIM_OPTIONS" not in view
    assert "按业务租户隔离" not in view
    assert "写入映射账号" not in view
    assert "create_shadow_user" not in view
    assert "isolate_datasets_by_tenant" not in view
    assert "常用提示词" in view
    assert "openPromptModal" in view
    assert "示例库" in view
    assert "openExampleModal" in view
    assert "savePrompts" in view
    assert "shortcut_prompts" in view
    assert "shortcut_prompts" in source
    assert "form.shortcut_prompts" not in view
    assert 'aria-label="示例库"' in view
    assert "onExampleFileDrop" in view
    assert "输入要发送给 AI 的文字，输入 / 选择技能" in view
    assert "显示名称" in view
    assert "使用场景" in view
    assert "指令内容" in view
    assert "openPromptEditor" in view
    assert "packShortcutSkill" in view
    assert "splitShortcutSkill" in view
    assert 'title="删除这条指令"' in view
