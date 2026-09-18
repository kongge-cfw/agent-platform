from unittest.mock import PropertyMock, patch

import pytest


pytestmark = pytest.mark.no_infrastructure


def test_skill_discovery_tools_list_and_read_skill(tmp_path):
    from app.services.ai.tools.system_executive_tools import (
        list_available_skills,
        read_skill_instruction,
    )

    skill_dir = tmp_path / "ops-helper"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: 运维辅助技能\n"
        "description: 处理运维排障流程\n"
        "---\n\n"
        "# 操作守则\n"
        "先定位影响范围，再给出处置步骤。\n",
        encoding="utf-8",
    )
    (skill_dir / "tools.md").write_text("# 工具清单\n先调用 locate_scope。\n", encoding="utf-8")
    hidden_dir = tmp_path / ".draft"
    hidden_dir.mkdir()
    (hidden_dir / "SKILL.md").write_text("hidden", encoding="utf-8")

    with patch("app.core.config.Settings.SKILLS_DIR", new_callable=PropertyMock) as mock_skills_dir:
        mock_skills_dir.return_value = str(tmp_path)

        listing = list_available_skills.invoke({})
        assert "ops-helper" in listing
        assert "运维辅助技能" in listing
        assert "处理运维排障流程" in listing
        assert ".draft" not in listing

        instruction = read_skill_instruction.invoke({"skill_id": "ops-helper"})
        assert "操作守则" in instruction
        assert "先定位影响范围" in instruction
        assert "`tools.md`" in instruction
        assert "file=\"文件名\"" in instruction or "file=\"相对路径\"" in instruction
        assert "先调用 locate_scope" not in instruction

        sidecar = read_skill_instruction.invoke(
            {"skill_id": "ops-helper", "file": "tools.md"}
        )
        assert "先调用 locate_scope" in sidecar
        assert "ops-helper/tools.md" in sidecar

        missing = read_skill_instruction.invoke(
            {"skill_id": "ops-helper", "file": "missing.md"}
        )
        assert "不存在文件 missing.md" in missing
        assert "`tools.md`" in missing

        traversal = read_skill_instruction.invoke(
            {"skill_id": "ops-helper", "file": "../ops-helper/SKILL.md"}
        )
        assert "路径穿越" in traversal or "相对路径" in traversal

        bad = read_skill_instruction.invoke({"skill_id": "../ops-helper"})
        assert "非法技能 ID" in bad


def test_list_available_skills_respects_agent_custom_allowlist(tmp_path, monkeypatch):
    from app.core.context import AgentContext, agent_context, set_agent_context
    from app.services.ai.tools.system_executive_tools import (
        list_available_skills,
        read_skill_instruction,
    )
    from app.utils.context import current_user_info

    global_root = tmp_path / "global"
    personal = tmp_path / "personal"
    for skill_id, name in (("alpha", "Alpha"), ("beta", "Beta")):
        d = global_root / skill_id
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: desc-{skill_id}\nenabled: true\n---\n\n# {name}\n",
            encoding="utf-8",
        )

    mine = personal / "mine"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text(
        "---\nname: Mine\ndescription: personal\nenabled: true\n---\n\n# Mine\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.services.ai.skill_resolver.get_user_personal_skills_dir",
        lambda _user: str(personal),
    )

    user_token = current_user_info.set({"id": 1, "user_name": "u1"})
    set_agent_context(
        AgentContext(
            agent_id="a1",
            agent_name="agent",
            skills_custom=True,
            skills=["beta"],
        )
    )

    try:
        with patch("app.core.config.Settings.SKILLS_DIR", new_callable=PropertyMock) as mock_skills_dir:
            mock_skills_dir.return_value = str(global_root)
            listing = list_available_skills.invoke({})
            assert "beta" in listing
            assert "alpha" not in listing
            assert "mine" in listing

            ok = read_skill_instruction.invoke({"skill_id": "beta"})
            assert "Beta" in ok
            denied = read_skill_instruction.invoke({"skill_id": "alpha"})
            assert "不在当前智能体可用 Skills 范围内" in denied or "不存在" in denied
            personal_ok = read_skill_instruction.invoke({"skill_id": "mine"})
            assert "Mine" in personal_ok
    finally:
        current_user_info.reset(user_token)
        agent_context.set(None)


def test_general_chat_implicit_tools_include_safe_skill_lookup():
    from app.services.ai.tools.registry import ToolRegistry

    tool_names = {getattr(tool, "name", "") for tool in ToolRegistry.get_system_implicit_tools()}

    assert "list_available_skills" in tool_names
    assert "read_skill_instruction" in tool_names


def test_skill_relative_file_helpers_reject_escape(tmp_path):
    from app.services.ai.skill_resolver import (
        is_skill_md_relative_file,
        list_skill_dir_files,
        resolve_skill_relative_file,
    )

    skill_dir = tmp_path / "demo"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("# demo\n", encoding="utf-8")
    (skill_dir / "notes.md").write_text("note", encoding="utf-8")

    abs_path, error, rel = resolve_skill_relative_file(str(skill_md), "notes.md")
    assert error is None
    assert rel == "notes.md"
    assert abs_path == str((skill_dir / "notes.md").resolve())
    assert "notes.md" in list_skill_dir_files(str(skill_md))

    _, error, _ = resolve_skill_relative_file(str(skill_md), "../notes.md")
    assert error and "穿越" in error
    _, error, _ = resolve_skill_relative_file(str(skill_md), "/etc/passwd")
    assert error and "相对路径" in error
    assert is_skill_md_relative_file(None) is True
    assert is_skill_md_relative_file("tools.md") is False
