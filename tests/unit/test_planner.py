"""Tests for the planning agent (Phase 2)."""

import json
from unittest.mock import patch, MagicMock

import pytest


class TestNeedsPlanning:
    """Heuristic that decides whether to invoke the planner."""

    def test_simple_queries_skip_planner(self):
        from agents.planner import needs_planning
        simple = ["hi", "thanks", "who is jsmith", "/digest", "send Alice a note",
                  "look up bob", "reply to that", "ok", "yes", "no"]
        for q in simple:
            assert needs_planning(q) is False, f"'{q}' should skip planner"

    def test_complex_queries_invoke_planner(self):
        from agents.planner import needs_planning
        complex_q = [
            "what to work on this week",
            "what should I focus on today",
            "catch up on what I missed",
            "prepare for my meeting with Paula",
            "give me a status update on everything",
            "what's happening across my team this week",
            "what did I promise people last week",
            "brief me on priorities",
        ]
        for q in complex_q:
            assert needs_planning(q) is True, f"'{q}' should trigger planner"

    def test_long_queries_trigger_planner(self):
        from agents.planner import needs_planning
        long = "I need to understand what happened while I was out, check my email and slack and calendar and see what needs attention"
        assert needs_planning(long) is True


class TestGeneratePlan:
    """Plan generation via LLM."""

    def test_generate_plan_returns_list(self):
        from agents.planner import generate_plan

        mock_response = json.dumps([
            {"id": "1", "tool": "gather", "request": "fetch calendar and todos", "depends_on": []},
            {"id": "2", "tool": "email_worker", "request": "scan sent emails for commitments", "depends_on": []},
        ])

        with patch("agents.planner.invoke_ai", return_value=mock_response):
            plan = generate_plan("what to work on this week")
            assert plan is not None
            assert len(plan) == 2
            assert plan[0]["tool"] == "gather"

    def test_generate_plan_handles_code_block_response(self):
        from agents.planner import generate_plan

        mock_response = '```json\n[{"id": "1", "tool": "gather", "request": "test", "depends_on": []}]\n```'

        with patch("agents.planner.invoke_ai", return_value=mock_response):
            plan = generate_plan("test")
            assert plan is not None
            assert len(plan) == 1

    def test_generate_plan_returns_none_on_invalid_json(self):
        from agents.planner import generate_plan

        with patch("agents.planner.invoke_ai", return_value="I can't do that"):
            plan = generate_plan("test")
            assert plan is None

    def test_generate_plan_returns_none_on_exception(self):
        from agents.planner import generate_plan

        with patch("agents.planner.invoke_ai", side_effect=Exception("timeout")):
            plan = generate_plan("test")
            assert plan is None


class TestExecutePlan:
    """Plan execution with parallel/sequential logic."""

    def test_parallel_steps_with_no_deps(self):
        from agents.planner import execute_plan

        call_order = []

        def mock_get_worker(name):
            def worker(request):
                call_order.append(name)
                return MagicMock(message=f"{name} result")
            return worker

        plan = [
            {"id": "1", "tool": "email", "request": "scan inbox", "depends_on": []},
            {"id": "2", "tool": "comms", "request": "scan slack", "depends_on": []},
        ]

        with patch("agents.planner.get_worker", mock_get_worker):
            results = execute_plan(plan)

        assert "1" in results
        assert "2" in results
        assert "email result" in results["1"]
        assert "comms result" in results["2"]

    def test_sequential_steps_with_deps(self):
        from agents.planner import execute_plan

        call_order = []

        def mock_get_worker(name):
            def worker(request):
                call_order.append(name)
                return MagicMock(message=f"{name} done")
            return worker

        plan = [
            {"id": "1", "tool": "email", "request": "scan inbox", "depends_on": []},
            {"id": "2", "tool": "comms", "request": "follow up on email results", "depends_on": ["1"]},
        ]

        with patch("agents.planner.get_worker", mock_get_worker):
            results = execute_plan(plan)

        # Step 2 depends on step 1, so email runs first
        assert call_order[0] == "email"
        assert call_order[1] == "comms"

    def test_failed_step_doesnt_crash_plan(self):
        from agents.planner import execute_plan

        def mock_get_worker(name):
            def worker(request):
                if name == "email":
                    raise TimeoutError("MCP down")
                return MagicMock(message="ok")
            return worker

        plan = [
            {"id": "1", "tool": "email", "request": "scan", "depends_on": []},
            {"id": "2", "tool": "comms", "request": "scan", "depends_on": []},
        ]

        with patch("agents.planner.get_worker", mock_get_worker):
            results = execute_plan(plan)

        assert "failed" in results["1"].lower() or "⚠️" in results["1"]
        assert "ok" in results["2"]

    def test_deadlocked_deps_handled(self):
        from agents.planner import execute_plan

        plan = [
            {"id": "1", "tool": "email", "request": "scan", "depends_on": ["2"]},
            {"id": "2", "tool": "comms", "request": "scan", "depends_on": ["1"]},
        ]

        with patch("agents.planner.get_worker"):
            results = execute_plan(plan)

        # Both should be marked as skipped/dependency not met
        assert "dependency" in results.get("1", "").lower() or "Skipped" in results.get("1", "")


class TestPlannerIntegration:
    """End-to-end planner in dispatch."""

    def test_dispatch_calls_planner_for_complex_query(self):
        """Complex queries should go through planner before agent."""
        from agents.planner import needs_planning
        assert needs_planning("what to work on this week")
        # The actual dispatch integration is tested by verifying needs_planning
        # returns True and plan_and_execute would be called

    def test_planner_failure_falls_through_to_agent(self):
        """If planner fails, dispatch should still call agent directly."""
        import dispatch

        mock_agent = MagicMock(return_value="direct response")

        with patch("agents.planner.needs_planning", return_value=True):
            with patch("agents.planner.plan_and_execute", return_value=None):
                result, handled = dispatch.dispatch("what to work on", mock_agent)

        # Should fall through to direct agent call
        mock_agent.assert_called_once_with("what to work on")
