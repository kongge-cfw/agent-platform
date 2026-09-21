from pathlib import Path

import pytest


pytestmark = pytest.mark.no_infrastructure

ROOT = Path(__file__).resolve().parents[2]
EMBED = ROOT / "frontend/src/views/EmbedChat.vue"
DEBUG = ROOT / "frontend/src/views/AgentDebug.vue"
CHAT_INPUT = ROOT / "frontend/src/components/embed/ChatInput.vue"
TASK_COMPOSER = ROOT / "frontend/src/components/task/TaskPromptComposer.vue"
UTIL = ROOT / "frontend/src/utils/chatRuntimePrefs.ts"
API = ROOT / "app/api/portal/api.py"
GUARD = ROOT / "app/services/embed_api_guard.py"
REASONING = ROOT / "app/services/ai/reasoning.py"


def test_chat_runtime_prefs_api_and_embed_guard_are_wired():
    api = API.read_text(encoding="utf-8")
    guard = GUARD.read_text(encoding="utf-8")
    util = UTIL.read_text(encoding="utf-8")

    assert "chat_runtime_prefs.router" in api
    assert 'prefix="/chat-runtime-prefs"' in api
    assert '("GET", "/api/portal/chat-runtime-prefs")' in guard
    assert '("PUT", "/api/portal/chat-runtime-prefs")' in guard
    assert 'CHAT_RUNTIME_PREFS_PATH = "/api/portal/chat-runtime-prefs"' in util


def test_embed_and_debug_persist_runtime_prefs_to_database():
    embed = EMBED.read_text(encoding="utf-8")
    debug = DEBUG.read_text(encoding="utf-8")

    assert "loadChatRuntimePrefs" in embed
    assert "saveChatRuntimePrefs" in embed
    assert "chatRuntimePrefsHydrated" in embed
    assert "loadChatRuntimePrefs" in debug
    assert "saveChatRuntimePrefs" in debug
    new_chat = embed.split("const generateNewConversation", 1)[1].split(
        "const fetchUserPortalPreferences", 1
    )[0]
    assert "resetEmbedThinkingOverrides" not in new_chat
    history = embed.split("const handleHistoryClick", 1)[1].split(
        "const handleDeleteSingleHistory", 1
    )[0]
    assert "resetEmbedThinkingOverrides" not in history
    model_handler = embed.split("const handleEmbedModelSelection", 1)[1].split(
        "const persistChatRuntimePrefsNow", 1
    )[0]
    assert "thinkingEnableOverride.value = null" not in model_handler


def test_thinking_default_follows_model_capability():
    chat_input = CHAT_INPUT.read_text(encoding="utf-8")
    composer = TASK_COMPOSER.read_text(encoding="utf-8")
    reasoning = REASONING.read_text(encoding="utf-8")

    assert (
        "props.thinkingEnableOverride ?? Boolean(selectedModelConfig.value.thinking_enable)"
        in chat_input
    )
    assert (
        "props.thinkingEnableOverride ?? Boolean(selectedModelConfig.value.thinking_only)"
        not in chat_input
    )
    assert (
        "props.thinkingEnableOverride ?? Boolean(selectedModelConfig.value.thinking_enable)"
        in composer
    )
    assert "effective_thinking = bool(thinking_enable and thinking_only)" not in reasoning
    assert "effective_thinking = bool(thinking_enable)" in reasoning
    assert "个人偏好思考" in chat_input
