from types import SimpleNamespace
import pytest

from app.services.ai.agent_roster import (
    AGENT_ROSTER_PLACEHOLDER,
    format_agent_roster_markdown,
    inject_agent_roster,
)

pytestmark = pytest.mark.no_infrastructure


def _agent(name, display_name, description):
    return SimpleNamespace(
        name=name,
        display_name=display_name,
        description=description,
        capabilities=["cap1"],
    )


def test_format_agent_roster_includes_delegable_and_current():
    roster = format_agent_roster_markdown(
        [_agent("chat-bi", "数据智能助手", "专注 SQL 与报表")],
        current_display_name="主助手(Main)",
        current_description="通用问答兜底",
    )
    assert "**数据智能助手**（`chat-bi`）" in roster
    assert "专注 SQL 与报表" in roster
    assert "**主助手(Main)（当前）**" in roster
    assert "通用问答兜底" in roster


def test_inject_agent_roster_replaces_placeholder():
    prompt = f"欢迎。\n{AGENT_ROSTER_PLACEHOLDER}\n结束。"
    result = inject_agent_roster(prompt, "   - **A**：desc")
    assert AGENT_ROSTER_PLACEHOLDER not in result
    assert "**A**：desc" in result


def test_inject_agent_roster_noop_without_placeholder():
    prompt = "无占位符"
    assert inject_agent_roster(prompt, "x") == prompt


def test_delegation_source_splits_embed_catalog_from_platform_list():
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "app/services/ai/agent_roster.py"
    text = source.read_text(encoding="utf-8")
    assert "def list_delegation_source_agents" in text
    assert "is_embed_session(user_info)" in text
    assert "list_allowed_agents(session, user_info)" in text
    assert "return await AgentManagerService.list_agents(session)" in text
