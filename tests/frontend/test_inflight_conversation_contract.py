from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.no_infrastructure


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _abort_error_block(source: str) -> str:
    for needle in ('if (e.name === "AbortError")', 'if (error.name === "AbortError")'):
        start = source.find(needle)
        if start >= 0:
            return source[start : start + 320]
    raise AssertionError("AbortError branch missing")


def _refresh_run_status_block(source: str) -> str:
    start = source.find("const refreshCurrentRunStatus")
    if start < 0:
        raise AssertionError("refreshCurrentRunStatus missing")
    return source[start : start + 280]


def test_both_chat_surfaces_stash_inflight_and_skip_history_replace():
    util = _read("frontend/src/utils/inflightConversation.ts")
    embed = _read("frontend/src/views/EmbedChat.vue")
    debug = _read("frontend/src/views/AgentDebug.vue")

    for name in (
        "stashInflightConversation",
        "peekInflightConversation",
        "shouldSkipHistoryReplace",
        "mergeCompletedRunIntoMessages",
        "needsGeneratingPlaceholder",
        "hasLiveGeneratingAgent",
    ):
        assert f"export const {name}" in util or f"export function {name}" in util

    for name in (
        "stashInflightConversation",
        "peekInflightConversation",
        "shouldSkipHistoryReplace",
        "mergeCompletedRunIntoMessages",
        "needsGeneratingPlaceholder",
        "ensureGeneratingPlaceholder",
        "hydrateCompletedConversationRun",
    ):
        assert name in embed
        assert name in debug

    assert "shouldStashInflight" not in util
    assert "ensureGeneratingView" not in embed
    assert "ensureGeneratingView" not in debug
    assert "Failed to sync in-progress conversation" not in embed
    assert "Failed to sync in-progress conversation" not in debug

    assert "stashCurrentInflightIfNeeded()" in embed
    assert "restoreInflightConversation(" in embed
    assert "hasLiveGeneratingAgent" in embed
    assert "hasKeepableSession" in embed

    assert "stashCurrentInflightIfNeeded()" in debug
    assert "restoreInflightConversation(" in debug
    assert "shouldSkipHistoryReplace(id)" in debug

    embed_placeholder = embed[embed.index("const ensureGeneratingPlaceholder") : embed.index("const messagesOwningAgent")]
    debug_placeholder = debug[debug.index("const ensureGeneratingPlaceholder") : debug.index("const messagesOwningAgent")]
    assert "stashInflightConversation" in embed_placeholder
    assert "stashInflightConversation" in debug_placeholder
    assert "scrollToBottom(true)" in embed_placeholder
    assert "scrollToBottom(true)" in debug_placeholder

    embed_hydrate = embed[embed.index("hydrateCompletedConversationRun = async (opts") : embed.index("const showQuotaStatusInChat")]
    debug_hydrate = debug[debug.index("hydrateCompletedConversationRun = async (opts") : debug.index("const getAgentDisplayName")]
    assert "mergeCompletedRunIntoMessages" in embed_hydrate
    assert "mergeCompletedRunIntoMessages" in debug_hydrate
    assert "fetchConversationHistory" not in embed_hydrate
    assert "loadSessionHistory" not in debug_hydrate
    assert "await loadGreeting()" in debug

    for source in (embed, debug):
        refresh_body = _refresh_run_status_block(source)
        assert "ensureGeneratingPlaceholder" not in refresh_body
        assert "/conversation/" not in refresh_body or "run-status" in refresh_body


def test_abort_error_does_not_cancel_open_todos():
    embed = _read("frontend/src/views/EmbedChat.vue")
    debug = _read("frontend/src/views/AgentDebug.vue")

    embed_abort = _abort_error_block(embed)
    debug_abort = _abort_error_block(debug)
    assert "cancelOpenTodosInMessages" not in embed_abort
    assert "cancelOpenTodosInMessages" not in debug_abort
    assert "用户终止" not in embed_abort

    embed_stop = embed[embed.index("const stopGeneration") : embed.index("abortController.abort()")]
    debug_stop = debug[debug.index("const stopGeneration") : debug.index("abortController.abort()")]
    assert "cancelOpenTodosInMessages" in embed_stop
    assert "cancelOpenTodosInMessages" in debug_stop


def test_visibility_does_not_poll_audit_history_while_generating():
    embed = _read("frontend/src/views/EmbedChat.vue")
    debug = _read("frontend/src/views/AgentDebug.vue")
    vis_start = embed.index("const onVisibilityChange")
    vis_end = embed.index("document.addEventListener(\"visibilitychange\"", vis_start)
    vis_body = embed[vis_start:vis_end]
    assert "ensureGeneratingPlaceholder" in vis_body
    assert "hydrateCompletedConversationRun" in vis_body
    assert "wasActive" in vis_body
    assert "/api/v1/chat/history" not in vis_body
    assert "maxAttempts = 15" not in embed
    assert "syncLatestSessionHistory" not in embed

    debug_vis_start = debug.index("const handleRunStatusVisibilityChange")
    debug_vis_end = debug.index('document.addEventListener("visibilitychange"', debug_vis_start)
    debug_vis = debug[debug_vis_start:debug_vis_end]
    assert "ensureGeneratingPlaceholder" in debug_vis
    assert "hydrateCompletedConversationRun" in debug_vis
    assert "wasActive" in debug_vis
    assert "/api/v1/chat/history" not in debug_vis


def test_embed_reinit_does_not_wipe_live_generating_session():
    embed = _read("frontend/src/views/EmbedChat.vue")
    init_config = embed[embed.index("const handleInitConfig") : embed.index("const handlePostMessage")]
    assert init_config.count("stashCurrentInflightIfNeeded()") >= 3

    payload = embed[embed.index("const applyInitConfigPayload") : embed.index("const exchangeTicketAndApply")]
    assert "hasKeepableSession()" in payload
    assert "generateNewConversation({ stash: false })" in payload

    init_chat = embed[embed.index("const initChat = async") : embed.index("// History State")]
    assert "hasLiveGeneratingAgent(messages.value)" in init_chat
    assert "!hasKeepableSession() && shouldUseServerActiveConversation()" in init_chat
    assert "if (!hasKeepableSession()) isInitialLoading.value = true;" in init_chat

    fetch_hist = embed[
        embed.index("const fetchConversationHistory") : embed.index("hydrateCompletedConversationRun = async (opts")
    ]
    assert "hasLiveGeneratingAgent(messages.value)" in fetch_hist
