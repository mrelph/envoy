"""Tests for Phase 4: Shared Workspace."""

from unittest.mock import patch, MagicMock

import pytest


class TestWorkspaceDataModel:
    """Workspace append, read, and formatting."""

    def test_create_workspace(self):
        from agents.workspace import create, get, clear
        ws = create("what to work on")
        assert ws.query == "what to work on"
        assert ws.is_empty
        assert get() is ws
        clear()
        assert get() is None

    def test_append_findings(self):
        from agents.workspace import create, clear
        ws = create("test")
        ws.append("findings", "Email from Alice about deadline", source="email")
        ws.append("findings", "Meeting with Bob tomorrow", source="calendar")
        assert len(ws.findings) == 2
        assert "Alice" in ws.findings[0].content
        clear()

    def test_append_action_items_with_priority(self):
        from agents.workspace import create, clear
        ws = create("test")
        ws.append("action_items", "Reply to VP", priority="high")
        ws.append("action_items", "Update docs", priority="low")
        formatted = ws.read("action_items")
        # High priority should come first
        assert formatted.index("Reply to VP") < formatted.index("Update docs")
        clear()

    def test_append_draft_sections(self):
        from agents.workspace import create, clear
        ws = create("test")
        ws.append("draft:calendar", "Monday: 3 meetings")
        ws.append("draft:calendar", "Tuesday: focus day")
        ws.append("draft:priorities", "Ship the feature")
        assert "Monday" in ws.read("draft:calendar")
        assert "Tuesday" in ws.read("draft:calendar")
        assert "Ship" in ws.read("draft:priorities")
        clear()

    def test_read_all(self):
        from agents.workspace import create, clear
        ws = create("test")
        ws.append("findings", "Fact A")
        ws.append("action_items", "Do B")
        ws.append("open_questions", "Should we C?")
        full = ws.read()
        assert "Findings" in full
        assert "Action Items" in full
        assert "Open Questions" in full
        clear()

    def test_empty_workspace(self):
        from agents.workspace import create, clear
        ws = create("test")
        assert ws.is_empty
        assert "empty" in ws.read().lower()
        clear()


class TestWorkspaceTools:
    """workspace_append and workspace_read tools."""

    def test_tools_created(self):
        from agents.workspace import make_workspace_tools
        tools = make_workspace_tools()
        assert len(tools) == 2
        names = [getattr(t, '__name__', getattr(t, 'tool_name', '')) for t in tools]
        assert "workspace_append" in names
        assert "workspace_read" in names

    def test_append_tool_posts_to_workspace(self):
        from agents.workspace import create, get, clear, make_workspace_tools
        ws = create("test")
        tools = make_workspace_tools()
        append_fn = tools[0]  # workspace_append
        result = append_fn("findings", "test finding")
        assert "Posted" in result
        assert len(ws.findings) == 1
        clear()

    def test_append_tool_without_workspace(self):
        from agents.workspace import clear, make_workspace_tools
        clear()
        tools = make_workspace_tools()
        append_fn = tools[0]
        result = append_fn("findings", "orphan")
        assert "No active workspace" in result

    def test_read_tool(self):
        from agents.workspace import create, clear, make_workspace_tools
        ws = create("test")
        ws.append("findings", "important fact")
        tools = make_workspace_tools()
        read_fn = tools[1]  # workspace_read
        result = read_fn("")
        assert "important fact" in result
        clear()


class TestSynthesizer:
    """Synthesizer assembles workspace into polished output."""

    def test_small_workspace_returned_directly(self):
        from agents.workspace import create, synthesize, clear
        ws = create("test")
        ws.append("action_items", "Reply to Alice", priority="high")
        ws.append("findings", "No urgent emails")
        # Small workspace (<2000 chars) returns formatted directly, no LLM call
        result = synthesize(ws)
        assert "Reply to Alice" in result
        clear()

    def test_large_workspace_calls_llm(self):
        from agents.workspace import create, synthesize, clear
        ws = create("test")
        # Fill with enough content to trigger LLM synthesis
        for i in range(30):
            ws.append("findings", f"Finding number {i} with some detail about what happened " * 3)

        with patch("agents.workspace.invoke_ai", return_value="Synthesized output") as mock_ai:
            result = synthesize(ws)

        assert result == "Synthesized output"
        mock_ai.assert_called_once()
        clear()

    def test_empty_workspace_returns_empty(self):
        from agents.workspace import create, synthesize, clear
        ws = create("test")
        result = synthesize(ws)
        assert result == ""
        clear()

    def test_synthesize_fallback_on_llm_failure(self):
        from agents.workspace import create, synthesize, clear
        ws = create("test")
        for i in range(30):
            ws.append("findings", f"Finding {i} " * 20)

        with patch("agents.workspace.invoke_ai", side_effect=Exception("timeout")):
            result = synthesize(ws)

        # Should return raw formatted workspace as fallback
        assert "Finding 0" in result
        clear()


class TestWorkspaceInPlanner:
    """Workspace integrates with the planner execution path."""

    def test_planner_creates_and_clears_workspace(self):
        from agents.planner import plan_and_execute
        from agents.workspace import get as get_ws
        import json

        mock_plan = [{"id": "1", "tool": "email", "request": "scan", "depends_on": []}]

        with patch("agents.planner.generate_plan", return_value=mock_plan):
            with patch("agents.planner.get_worker") as mock_gw:
                mock_gw.return_value = MagicMock(return_value=MagicMock(message="3 emails found"))
                plan_and_execute("what to work on")

        # Workspace should be cleared after execution
        assert get_ws() is None

    def test_planner_uses_synthesizer_when_workspace_populated(self):
        from agents.planner import plan_and_execute
        from agents import workspace as ws_mod

        mock_plan = [{"id": "1", "tool": "email", "request": "scan", "depends_on": []}]

        def mock_worker(name):
            def call(request):
                # Worker posts to workspace
                w = ws_mod.get()
                if w:
                    w.append("action_items", "Reply to boss", priority="high")
                return MagicMock(message="done")
            return call

        with patch("agents.planner.generate_plan", return_value=mock_plan):
            with patch("agents.planner.get_worker", side_effect=mock_worker):
                with patch("agents.workspace.invoke_ai", return_value="Synthesized: Reply to boss") as mock_ai:
                    result = plan_and_execute("priorities")

        # Small workspace returns directly without LLM
        assert "Reply to boss" in result


class TestWorkspaceInWorkers:
    """Workers get workspace tools injected."""

    def test_worker_gets_workspace_tools_injected(self):
        from agents.workers import _import_create, _workers
        _workers.clear()
        agent = _import_create("email_worker", "email")
        # In test env, agent is MagicMock. Verify process_tools was called
        # (once for delegate, once for workspace tools)
        assert agent.tool_registry.process_tools.call_count >= 2
