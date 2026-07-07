"""Unit tests for agents/workers/calendar_worker.py — attendee-address
validation (H6 fix). No email/alias should ever be fabricated: bare tokens
without "@" must be rejected with a graceful structured error instead of
being silently turned into "<token>@amazon.com" and sent to the MCP server.
"""

import strands

from agents.workers import calendar_worker


def _build_and_get_tool(name):
    """Call calendar_worker.create() and pull a tool function out of the
    tools=[...] list passed to the (stubbed) strands.Agent constructor.
    """
    strands.Agent.reset_mock()
    calendar_worker.create()
    tools = strands.Agent.call_args.kwargs["tools"]
    for t in tools:
        if t.__name__ == name:
            return t
    raise AssertionError(f"tool {name!r} not found among {[t.__name__ for t in tools]}")


class TestCreateEventAttendeeValidation:
    def test_bare_alias_is_rejected_without_calling_mcp(self, monkeypatch):
        create_event = _build_and_get_tool("create_event")

        called = {}

        def _fake_outlook_tool(tool_name, args):
            called["invoked"] = True
            return "should not be reached"

        import tools as tools_mod
        monkeypatch.setattr(tools_mod, "_outlook_tool", _fake_outlook_tool)

        result = create_event(subject="Sync", start="2026-07-08T10:00:00",
                               end="2026-07-08T10:30:00", attendees="sarah")

        assert "invoked" not in called
        assert "Invalid attendee" in result
        assert "sarah" in result
        assert "amazon.com" not in result

    def test_bare_optional_attendee_is_rejected(self, monkeypatch):
        create_event = _build_and_get_tool("create_event")
        import tools as tools_mod
        monkeypatch.setattr(tools_mod, "_outlook_tool", lambda *a, **k: "unused")

        result = create_event(subject="Sync", start="2026-07-08T10:00:00",
                               end="2026-07-08T10:30:00",
                               attendees="alice@example.com",
                               optional_attendees="bob")

        assert "Invalid attendee" in result
        assert "bob" in result

    def test_full_email_addresses_pass_through(self, monkeypatch):
        create_event = _build_and_get_tool("create_event")

        seen_args = {}

        def _fake_outlook_tool(tool_name, args):
            seen_args.update(args)
            return "ok"

        import tools as tools_mod
        monkeypatch.setattr(tools_mod, "_outlook_tool", _fake_outlook_tool)

        result = create_event(subject="Sync", start="2026-07-08T10:00:00",
                               end="2026-07-08T10:30:00",
                               attendees="alice@example.com, bob@example.com",
                               optional_attendees="carol@example.com")

        assert result == "ok"
        assert seen_args["attendees"] == ["alice@example.com", "bob@example.com"]
        assert seen_args["optionalAttendees"] == ["carol@example.com"]


class TestUpdateEventAttendeeValidation:
    def test_bare_alias_is_rejected_without_calling_mcp(self, monkeypatch):
        update_event = _build_and_get_tool("update_event")

        called = {}

        def _fake_outlook_tool(tool_name, args):
            called["invoked"] = True
            return "should not be reached"

        import tools as tools_mod
        monkeypatch.setattr(tools_mod, "_outlook_tool", _fake_outlook_tool)

        result = update_event(meeting_id="abc123", attendees="dave")

        assert "invoked" not in called
        assert "Invalid attendee" in result
        assert "dave" in result


class TestAddAttendeeArgsHelper:
    """Exercise _add_attendee_args directly via the module-private closure,
    reached through create_event's ValueError message, to pin the exact
    fabrication-free behavior described in PROJECT-REVIEW H6."""

    def test_resources_are_untouched_by_validation(self, monkeypatch):
        create_event = _build_and_get_tool("create_event")

        seen_args = {}

        def _fake_outlook_tool(tool_name, args):
            seen_args.update(args)
            return "ok"

        import tools as tools_mod
        monkeypatch.setattr(tools_mod, "_outlook_tool", _fake_outlook_tool)

        result = create_event(subject="Sync", start="2026-07-08T10:00:00",
                               end="2026-07-08T10:30:00",
                               resources="room-a")

        assert result == "ok"
        assert seen_args["resources"] == ["room-a"]
        assert "attendees" not in seen_args
