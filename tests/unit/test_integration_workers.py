"""Integration tests for worker tool calling.

These tests mock the MCP layer and verify that worker tool functions
produce correct MCP calls with the right parameters. They catch the
class of bug where a worker tool's parameters don't match what the
underlying MCP/fetch function expects (the calendar start_date bug).
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from types import SimpleNamespace
from datetime import datetime


# --- Calendar worker tests ---

class TestCalendarWorkerTools:
    """Verify calendar worker tools produce correct MCP calls."""

    def _make_mcp_result(self, text="# Calendar\n| 9:00 | Meeting | Room 1 |"):
        content = SimpleNamespace(text=text)
        return SimpleNamespace(content=[content])

    @pytest.fixture
    def mock_outlook(self):
        """Mock the outlook MCP session."""
        session = AsyncMock()
        session.call_tool = AsyncMock(return_value=self._make_mcp_result())
        session.dead = False

        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def _ctx():
            yield session
        
        with patch("agents.base._mcp_session") as mock_fn:
            mock_fn.return_value = _ctx
            with patch("agents.calendar.outlook", _ctx):
                yield session

    def test_view_calendar_today_uses_correct_date_format(self, mock_outlook):
        """view_calendar with no start_date should use today in MM-DD-YYYY format."""
        from agents.base import run
        from agents.fetch import fetch_calendar

        run(fetch_calendar(days=1))

        # First call is calendar_view, subsequent calls may be email_search (xref)
        first_call = mock_outlook.call_tool.call_args_list[0]
        tool_name = first_call[0][0]
        args = first_call[0][1] if len(first_call[0]) > 1 else first_call[1].get("arguments", {})
        assert tool_name == "calendar_view"
        assert "start_date" in args
        start = args["start_date"]
        assert len(start) == 10
        assert start[2] == "-" and start[5] == "-"

    def test_view_calendar_specific_date_passes_through(self, mock_outlook):
        """view_calendar with explicit start_date should pass it to MCP."""
        from agents.base import run
        from agents.fetch import fetch_calendar

        run(fetch_calendar(days=1, start_date="05-20-2026"))

        first_call = mock_outlook.call_tool.call_args_list[0]
        args = first_call[0][1] if len(first_call[0]) > 1 else first_call[1].get("arguments", {})
        assert args["start_date"] == "05-20-2026"

    def test_view_calendar_week_sets_end_date_relative_to_start(self, mock_outlook):
        """Week view should calculate end_date relative to start_date, not now()."""
        from agents.base import run
        from agents.fetch import fetch_calendar

        run(fetch_calendar(days=5, start_date="05-20-2026"))

        first_call = mock_outlook.call_tool.call_args_list[0]
        args = first_call[0][1] if len(first_call[0]) > 1 else first_call[1].get("arguments", {})
        assert args["start_date"] == "05-20-2026"
        assert args["view"] == "week"
        assert args["end_date"] == "05-25-2026"

    def test_view_calendar_week_end_date_not_relative_to_now(self, mock_outlook):
        """Regression test: end_date must NOT use datetime.now() as base."""
        from agents.base import run
        from agents.fetch import fetch_calendar

        run(fetch_calendar(days=7, start_date="12-01-2026"))

        first_call = mock_outlook.call_tool.call_args_list[0]
        args = first_call[0][1] if len(first_call[0]) > 1 else first_call[1].get("arguments", {})
        assert args["end_date"] == "12-08-2026"


# --- Shared fetch module tests ---

class TestFetchModule:
    """Verify the shared fetch module is the single source of truth."""

    def test_fetch_calendar_calls_get_events_raw(self):
        """fetch_calendar should delegate to calendar.get_events_raw."""
        with patch("agents.calendar.get_events_raw", new_callable=AsyncMock) as mock:
            mock.return_value = ("events text", "xref")
            from agents.base import run
            from agents.fetch import fetch_calendar

            result = run(fetch_calendar(days=3, start_date="06-01-2026"))

            mock.assert_called_once_with(view="week", start_date="06-01-2026", days_ahead=3)
            assert result == ("events text", "xref")

    def test_fetch_calendar_day_view_for_single_day(self):
        """days=1 should use 'day' view."""
        with patch("agents.calendar.get_events_raw", new_callable=AsyncMock) as mock:
            mock.return_value = ("events", "")
            from agents.base import run
            from agents.fetch import fetch_calendar

            run(fetch_calendar(days=1))

            args = mock.call_args
            assert args[1]["view"] == "day"


# --- Budget integration tests ---

class TestBudgetIntegration:
    """Verify budget tracking works end-to-end."""

    def test_budget_starts_fresh_per_request(self):
        from agents.budget import start_request, get_budget
        b = start_request()
        assert b._ai_calls == 0
        assert b.elapsed < 1.0

    def test_budget_records_ai_calls(self):
        from agents.budget import start_request, get_budget
        b = start_request()
        b.record_ai_call(input_tokens=1000, output_tokens=500, tier="medium")
        assert b._ai_calls == 1
        assert b._input_tokens == 1000
        assert b._est_cost_usd > 0

    def test_budget_warns_at_threshold(self):
        from agents.budget import start_request, WARN_AI_CALLS
        b = start_request()
        for _ in range(WARN_AI_CALLS + 1):
            b.record_ai_call(100, 50, "medium")
        assert b.should_warn
        msg = b.warning_message()
        assert "AI calls" in msg
        # After warning, should_warn returns False
        assert not b.should_warn

    def test_budget_exceeded_blocks(self):
        from agents.budget import start_request, MAX_AI_CALLS
        b = start_request()
        for _ in range(MAX_AI_CALLS + 1):
            b.record_ai_call(100, 50, "medium")
        assert b.exceeded
