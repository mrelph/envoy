"""Unit tests for agents/todo.py — parallelized per-list fetch (item 12).

fetch_todos() used to call todo_tasks once per list *sequentially*; it now
gathers all lists concurrently behind a semaphore. These tests verify the
gather preserves list ordering (regardless of which call resolves first)
and that a single failing list degrades gracefully instead of failing the
whole fetch.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _mcp_result(payload):
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload))])


def _make_mock_session(call_tool_impl):
    session = AsyncMock()
    session.call_tool = AsyncMock(side_effect=call_tool_impl)

    @asynccontextmanager
    async def _ctx():
        yield session

    return session, _ctx


class TestFetchTodosParallel:
    def test_fetches_all_lists_and_filters_completed(self):
        async def _call_tool(tool_name, arguments=None, **kwargs):
            arguments = arguments or {}
            if tool_name == "todo_lists":
                return _mcp_result({"value": [
                    {"id": "list-1", "displayName": "Work"},
                    {"id": "list-2", "displayName": "Personal"},
                ]})
            if tool_name == "todo_tasks":
                list_id = arguments.get("listId")
                if list_id == "list-1":
                    return _mcp_result({"value": [
                        {"id": "t1", "title": "Ship feature", "status": "notStarted"},
                        {"id": "t2", "title": "Old thing", "status": "completed"},
                    ]})
                if list_id == "list-2":
                    return _mcp_result({"value": [
                        {"id": "t3", "title": "Buy milk", "status": "notStarted"},
                    ]})
            raise AssertionError(f"unexpected call: {tool_name} {arguments}")

        session, ctx = _make_mock_session(_call_tool)
        with patch("agents.todo.outlook", ctx):
            from agents.base import run
            from agents.todo import fetch_todos
            out = run(fetch_todos())

        assert "## Work (1 open)" in out
        assert "Ship feature" in out
        assert "Old thing" not in out  # completed task filtered out
        assert "## Personal (1 open)" in out
        assert "Buy milk" in out

        # One todo_tasks call per list.
        list_id_calls = sorted(
            c.kwargs.get("arguments", {}).get("listId")
            for c in session.call_tool.call_args_list
            if c.args and c.args[0] == "todo_tasks"
        )
        assert list_id_calls == ["list-1", "list-2"]

    def test_output_order_follows_list_order_not_completion_order(self):
        """The second list's MCP call resolves first; output must still list
        'Work' before 'Personal' because results are zipped back against the
        original list order, not gather() completion order."""
        async def _call_tool(tool_name, arguments=None, **kwargs):
            arguments = arguments or {}
            if tool_name == "todo_lists":
                return _mcp_result({"value": [
                    {"id": "list-1", "displayName": "Work"},
                    {"id": "list-2", "displayName": "Personal"},
                ]})
            if tool_name == "todo_tasks":
                list_id = arguments.get("listId")
                if list_id == "list-1":
                    await asyncio.sleep(0.02)  # resolves after list-2
                    return _mcp_result({"value": [
                        {"id": "t1", "title": "Ship feature", "status": "notStarted"},
                    ]})
                if list_id == "list-2":
                    return _mcp_result({"value": [
                        {"id": "t3", "title": "Buy milk", "status": "notStarted"},
                    ]})
            raise AssertionError(f"unexpected call: {tool_name} {arguments}")

        session, ctx = _make_mock_session(_call_tool)
        with patch("agents.todo.outlook", ctx):
            from agents.base import run
            from agents.todo import fetch_todos
            out = run(fetch_todos())

        assert out.index("## Work") < out.index("## Personal")

    def test_one_failing_list_degrades_gracefully(self):
        """A single list's todo_tasks call raising must not fail the whole
        fetch — it should just contribute nothing, per-item error handling."""
        async def _call_tool(tool_name, arguments=None, **kwargs):
            arguments = arguments or {}
            if tool_name == "todo_lists":
                return _mcp_result({"value": [
                    {"id": "list-1", "displayName": "Work"},
                    {"id": "list-2", "displayName": "Broken"},
                ]})
            if tool_name == "todo_tasks":
                list_id = arguments.get("listId")
                if list_id == "list-1":
                    return _mcp_result({"value": [
                        {"id": "t1", "title": "Ship feature", "status": "notStarted"},
                    ]})
                if list_id == "list-2":
                    raise RuntimeError("MCP timeout")
            raise AssertionError(f"unexpected call: {tool_name} {arguments}")

        session, ctx = _make_mock_session(_call_tool)
        with patch("agents.todo.outlook", ctx):
            from agents.base import run
            from agents.todo import fetch_todos
            out = run(fetch_todos())

        assert "## Work (1 open)" in out
        assert "Ship feature" in out
        assert "Broken" not in out
