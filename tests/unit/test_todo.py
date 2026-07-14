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


class TestAddTasksParallel:
    """add_tasks() creates tasks concurrently with a semaphore."""

    def test_creates_multiple_tasks_in_parallel(self):
        created = []

        async def _call_tool(tool_name, arguments=None, **kwargs):
            arguments = arguments or {}
            if tool_name == "todo_lists":
                op = arguments.get("operation", "")
                if op == "list":
                    return _mcp_result({"value": [
                        {"id": "list-1", "displayName": "Envoy Action Items"},
                    ]})
            if tool_name == "todo_tasks":
                op = arguments.get("operation", "")
                if op == "create":
                    created.append(arguments.get("title", ""))
                    return _mcp_result({"id": f"task-{len(created)}"})
            raise AssertionError(f"unexpected: {tool_name} {arguments}")

        session, ctx = _make_mock_session(_call_tool)
        with patch("agents.todo.outlook", ctx):
            from agents.base import run
            from agents.todo import add_tasks
            items = [
                {"title": "Task A"},
                {"title": "Task B"},
                {"title": "Task C"},
            ]
            result = run(add_tasks(items))

        assert result is True
        assert sorted(created) == ["Task A", "Task B", "Task C"]

    def test_one_failing_task_does_not_sink_batch(self):
        async def _call_tool(tool_name, arguments=None, **kwargs):
            arguments = arguments or {}
            if tool_name == "todo_lists":
                return _mcp_result({"value": [
                    {"id": "list-1", "displayName": "Envoy Action Items"},
                ]})
            if tool_name == "todo_tasks":
                if arguments.get("title") == "Bad":
                    raise RuntimeError("MCP error")
                return _mcp_result({"id": "ok"})
            raise AssertionError(f"unexpected: {tool_name}")

        session, ctx = _make_mock_session(_call_tool)
        with patch("agents.todo.outlook", ctx):
            from agents.base import run
            from agents.todo import add_tasks
            items = [{"title": "Good"}, {"title": "Bad"}, {"title": "Also Good"}]
            result = run(add_tasks(items))

        # At least one succeeded, so returns True
        assert result is True


class TestAddSubtasksParallel:
    """add_subtasks() creates checklist items concurrently."""

    def test_creates_subtasks_in_parallel(self):
        created = []

        async def _call_tool(tool_name, arguments=None, **kwargs):
            arguments = arguments or {}
            if tool_name == "todo_lists":
                return _mcp_result({"value": [
                    {"id": "list-1", "displayName": "Work"},
                ]})
            if tool_name == "todo_tasks":
                return _mcp_result({"value": [
                    {"id": "task-1", "title": "Parent Task", "status": "notStarted"},
                ]})
            if tool_name == "todo_checklist":
                created.append(arguments.get("displayName", ""))
                return _mcp_result({"id": f"sub-{len(created)}"})
            raise AssertionError(f"unexpected: {tool_name}")

        session, ctx = _make_mock_session(_call_tool)
        with patch("agents.todo.outlook", ctx):
            from agents.base import run
            from agents.todo import add_subtasks
            result = run(add_subtasks("Work", "Parent Task", ["Sub A", "Sub B", "Sub C"]))

        assert "3 subtasks" in result
        assert sorted(created) == ["Sub A", "Sub B", "Sub C"]

    def test_partial_failure_reports_count(self):
        async def _call_tool(tool_name, arguments=None, **kwargs):
            arguments = arguments or {}
            if tool_name == "todo_lists":
                return _mcp_result({"value": [
                    {"id": "list-1", "displayName": "Work"},
                ]})
            if tool_name == "todo_tasks":
                return _mcp_result({"value": [
                    {"id": "task-1", "title": "Parent Task", "status": "notStarted"},
                ]})
            if tool_name == "todo_checklist":
                if arguments.get("displayName") == "Fail":
                    raise RuntimeError("nope")
                return _mcp_result({"id": "ok"})
            raise AssertionError(f"unexpected: {tool_name}")

        session, ctx = _make_mock_session(_call_tool)
        with patch("agents.todo.outlook", ctx):
            from agents.base import run
            from agents.todo import add_subtasks
            result = run(add_subtasks("Work", "Parent Task", ["OK1", "Fail", "OK2"]))

        assert "2/3" in result
        assert "1 failed" in result
