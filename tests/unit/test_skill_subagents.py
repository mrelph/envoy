"""Tests for Phase 3: Skills as Subagents."""

import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def skill_dir(tmp_path):
    """Create a temp directory with test skills."""
    # Subagent skill
    sub_dir = tmp_path / "deal-tracker"
    sub_dir.mkdir()
    (sub_dir / "SKILL.md").write_text("""---
name: deal-tracker
description: Track active deals by scanning email
tools:
  - email
  - research
  - vault_write
model: light
memory_namespace: deals
---

# Deal Tracker
Scan emails for deal-related activity.
""")
    # Legacy skill (no tools field)
    legacy_dir = tmp_path / "old-skill"
    legacy_dir.mkdir()
    (legacy_dir / "SKILL.md").write_text("""---
name: old-skill
description: A legacy skill with no tools
---

# Old Skill
Just instructions.
""")
    return tmp_path


class TestSkillParsing:
    """Skills with tools: become subagents; without remain legacy."""

    def test_subagent_skill_parsed(self, skill_dir):
        from agents.skills import _parse_skill_md
        skill = _parse_skill_md(skill_dir / "deal-tracker" / "SKILL.md")
        assert skill["is_subagent"] is True
        assert skill["tools"] == ["email", "research", "vault_write"]
        assert skill["model"] == "light"
        assert skill["memory_namespace"] == "deals"

    def test_legacy_skill_not_subagent(self, skill_dir):
        from agents.skills import _parse_skill_md
        skill = _parse_skill_md(skill_dir / "old-skill" / "SKILL.md")
        assert skill["is_subagent"] is False
        assert skill["tools"] is None

    def test_default_memory_namespace_is_skill_name(self):
        from agents.skills import _parse_skill_md
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "SKILL.md").write_text("""---
name: my-skill
description: test
tools: [email]
---
body
""")
        skill = _parse_skill_md(d / "SKILL.md")
        assert skill["memory_namespace"] == "my-skill"
        shutil.rmtree(d)


class TestNamespacedMemory:
    """Skill memory is isolated per namespace."""

    def test_remember_and_recall(self, tmp_path):
        from agents.skills import _get_namespaced_memory_tools, _MEMORY_BASE

        # Patch memory base to use tmp
        with patch("agents.skills._MEMORY_BASE", tmp_path):
            tools = _get_namespaced_memory_tools("test-skill")
            remember_fn = tools[0]
            recall_fn = tools[1]

            # Remember something
            result = remember_fn("deal with Acme is progressing")
            assert "Remembered" in result

            # Recall it
            result = recall_fn("")
            assert "Acme" in result

            # Recall with filter
            result = recall_fn("Acme")
            assert "Acme" in result

            # Filter that matches nothing
            result = recall_fn("nonexistent")
            assert "No matching" in result

    def test_namespaces_are_isolated(self, tmp_path):
        from agents.skills import _get_namespaced_memory_tools

        with patch("agents.skills._MEMORY_BASE", tmp_path):
            tools_a = _get_namespaced_memory_tools("skill-a")
            tools_b = _get_namespaced_memory_tools("skill-b")

            tools_a[0]("only in A")
            tools_b[0]("only in B")

            assert "only in A" in tools_a[1]("")
            assert "only in A" not in tools_b[1]("")
            assert "only in B" in tools_b[1]("")


class TestRunSkill:
    """run_skill routes subagents vs legacy correctly."""

    def test_legacy_skill_returns_activation_text(self, skill_dir):
        from agents.skills import run_skill, _skills_cache, reload_skills, SKILL_PATHS

        # Inject test path
        reload_skills()
        with patch("agents.skills.SKILL_PATHS", [skill_dir]):
            from agents.skills import discover_skills
            skills = discover_skills()
            with patch("agents.skills.get_skills", return_value=skills):
                result = run_skill("old-skill", "do something")
                # Legacy returns skill_content XML
                assert "skill_content" in result or "Old Skill" in result

    def test_unknown_skill_returns_error(self):
        from agents.skills import run_skill
        with patch("agents.skills.get_skills", return_value={}):
            result = run_skill("nonexistent", "test")
            assert "not found" in result

    def test_subagent_skill_calls_spawn(self, skill_dir):
        from agents.skills import run_skill

        with patch("agents.skills.SKILL_PATHS", [skill_dir]):
            from agents.skills import discover_skills
            skills = discover_skills()

            mock_agent = MagicMock()
            mock_agent.return_value = MagicMock(message="Found 3 deals")

            with patch("agents.skills.get_skills", return_value=skills):
                with patch("agents.skills.spawn_skill_agent", return_value=mock_agent):
                    result = run_skill("deal-tracker", "scan last week")

            assert "3 deals" in result
            mock_agent.assert_called_once_with("scan last week")

    def test_subagent_failure_falls_back_to_instructions(self, skill_dir):
        from agents.skills import run_skill

        with patch("agents.skills.SKILL_PATHS", [skill_dir]):
            from agents.skills import discover_skills
            skills = discover_skills()

            with patch("agents.skills.get_skills", return_value=skills):
                with patch("agents.skills.spawn_skill_agent", side_effect=RuntimeError("model error")):
                    result = run_skill("deal-tracker", "scan")

            assert "failed" in result.lower()
            # Should include fallback instructions
            assert "Deal Tracker" in result


class TestActivateSkillTool:
    """The activate_skill tool routes correctly based on skill type."""

    def test_subagent_skill_requires_request(self):
        import tools
        skills = {"sub": {"name": "sub", "is_subagent": True, "description": "test"}}
        with patch("tools.get_skills", return_value=skills):
            result = tools.activate_skill("sub")
            assert "provide a request" in result

    def test_subagent_skill_with_request_runs(self):
        import tools
        skills = {"sub": {"name": "sub", "is_subagent": True, "description": "test"}}
        with patch("tools.get_skills", return_value=skills):
            with patch("agents.skills.run_skill", return_value="subagent result") as mock_run:
                result = tools.activate_skill("sub", request="do the thing")
        assert result == "subagent result"
        mock_run.assert_called_once_with("sub", "do the thing")
