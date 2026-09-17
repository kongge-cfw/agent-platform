"""Contract: EmbedChat URL agent_id 深链锁定与引导页。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EMBED = ROOT / "frontend" / "src" / "views" / "EmbedChat.vue"
CHAT_INPUT = ROOT / "frontend" / "src" / "components" / "embed" / "ChatInput.vue"
AGENTS_API = ROOT / "app" / "api" / "portal" / "endpoints" / "agents.py"


def test_embed_access_api_endpoint_exists():
    text = AGENTS_API.read_text(encoding="utf-8")
    assert '/{agent_id}/embed-access' in text
    assert "AGENT_NOT_FOUND" in text
    assert "AGENT_FORBIDDEN" in text


def test_embed_chat_url_agent_lock_and_status_label():
    text = EMBED.read_text(encoding="utf-8")
    assert "isUrlAgentPinned" in text
    assert "urlAgentAccessError" in text
    assert "resolveUrlPinnedAgent" in text
    assert "embed-access" in text
    assert "headerExpertLabel" in text
    assert "准备就绪" in text
    assert "flex items-center gap-1.5 min-w-0 overflow-hidden" in text
    assert "isUrlAgentPinned && pinnedAgentLabel" not in text or "headerExpertLabel" in text
    assert "{{ pinnedAgentLabel }} 准备就绪" not in text
    assert ':lock-expert-agent="isRoutingSettingsLocked"' in text
    assert "lock-expert-agent" in text
    assert "effectiveSlashCommands" in text
    assert "无权使用该智能体" in text
    assert "智能体不存在" in text
    assert "返回全能助手" not in text
    assert "clearUrlAgentPinAndReload" not in text


def test_embed_chat_iframe_uses_app_shortcut_prompts_not_global_slash_commands():
    text = EMBED.read_text(encoding="utf-8")
    chat_input = CHAT_INPUT.read_text(encoding="utf-8")
    assert "embedAppShortcutPrompts" in text
    assert "applyEmbedShortcutPrompts" in text
    assert "isPersonalSlashCommand" in text
    assert "mergeVisibleSlashCommands" in text
    assert "resolveCurrentEmbedAppKey" in text
    assert "canManageEmbedPersonalShortcuts" in text
    assert "embed_app_key" in text
    assert 'axios.get("/api/portal/slash-commands/"' in text
    assert ':allow-manage-shortcuts="!isEmbeddedInIframe()"' not in text
    assert ':allow-manage-shortcuts="canManageEmbedPersonalShortcuts"' in text
    assert "allowManageShortcuts" in chat_input
    assert 'v-if="canManageShortcuts"' in chat_input
    assert 'id.startsWith("app_prompt_")' in chat_input


def test_embed_chat_pins_shortcut_bar_and_keeps_new_and_history_only():
    text = EMBED.read_text(encoding="utf-8")
    chat_input = CHAT_INPUT.read_text(encoding="utf-8")
    assert ':pin-shortcut-bar="true"' in text
    assert ':show-shortcuts="!isMobile"' in text
    assert "v-if=\"isMobile || !config.showShortcuts\"" not in text
    assert "pinShortcutBar" in chat_input
    assert 'ROW_SYSTEM_COMMAND_IDS' in chat_input
    assert 'sys_clear' in chat_input
    assert 'sys_history' in chat_input
    assert 'v-if="!pinShortcutBar"' in chat_input
    assert "System · 系统功能" in chat_input
    assert "快捷指令" in chat_input
    assert 'v-if="!pinShortcutBar"' in chat_input
    assert "cmd.id === 'sys_clear' && !pinShortcutBar" in chat_input
    assert "visibleRowPersonalCommands" in chat_input
    assert "visibleRowAppPromptCommands" in chat_input
    assert "bg-emerald-50" in chat_input
    assert "text-gray-700 dark:text-gray-200" in chat_input


def test_chat_input_hides_expert_and_at_when_locked():
    text = CHAT_INPUT.read_text(encoding="utf-8")
    assert "lockExpertAgent" in text
    assert "v-if=\"!lockExpertAgent\"" in text or "v-if='!lockExpertAgent'" in text
    assert "!isMobileViewport && !lockExpertAgent" in text
    assert "if (atMatch && !props.lockExpertAgent)" in text
    assert "sys_knowledge_portal" in text
