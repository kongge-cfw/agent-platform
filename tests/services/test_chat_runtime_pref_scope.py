from pathlib import Path

import pytest

from app.services.chat_runtime_pref_service import (
    _sanitize_override_model,
    _sanitize_reasoning_effort,
    _sanitize_temperature,
    resolve_chat_runtime_pref_scope,
)


pytestmark = pytest.mark.no_infrastructure


def test_embed_pref_scope_requires_stable_session_owner():
    assert resolve_chat_runtime_pref_scope(
        {
            "session_type": "embed",
            "session_owner": "1",
            "embed_app_key": "traffic-app",
            "user_id": 1,
        }
    ) is None
    assert resolve_chat_runtime_pref_scope(
        {
            "session_type": "embed",
            "user_id": 1,
            "embed_app_key": "traffic-app",
        }
    ) is None
    assert resolve_chat_runtime_pref_scope(
        {
            "session_type": "embed",
            "session_owner": "e:abc123",
            "embed_app_key": "traffic-app",
            "user_id": 1,
        }
    ) == ("traffic-app", "e:abc123")


def test_platform_pref_scope_uses_empty_app_key():
    assert resolve_chat_runtime_pref_scope({"user_id": 7}) == ("", "7")
    assert resolve_chat_runtime_pref_scope({}) is None


def test_chat_runtime_pref_sanitizers():
    assert _sanitize_override_model("  qwen-plus  ") == "qwen-plus"
    assert _sanitize_override_model("   ") is None
    assert _sanitize_reasoning_effort("max") == "xhigh"
    assert _sanitize_reasoning_effort("") is None
    assert _sanitize_temperature(1.234) == 1.23
    assert _sanitize_temperature(-1) == 0.0
    assert _sanitize_temperature(9) == 2.0
    assert _sanitize_temperature("nope") is None
