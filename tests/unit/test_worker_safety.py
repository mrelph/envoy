"""Unit tests for the coding-worker safety changes and the destructive-action
confirmation gate wired into email_worker / comms_worker.

Worker `create()` functions build a strands Agent (stubbed as a MagicMock by
tests/conftest.py) and pass their @tool-decorated functions via `tools=[...]`.
Since the stub's @tool decorator is a no-op, those are plain callables we can
grab out of the captured `tools=` kwarg and invoke directly.
"""

import json

import pytest

import tools
from agents import confirm as confirm_mod


@pytest.fixture(autouse=True)
def _reset_confirm_state():
    confirm_mod.clear_pending()
    confirm_mod._state["user_turn"] = ""
    confirm_mod._state["user_turn_ts"] = 0.0
    yield
    confirm_mod.clear_pending()


def _patch_config_file(monkeypatch, envoy_home):
    """Redirect tools._CONFIG_FILE to live under the per-test envoy_home.

    tools._CONFIG_FILE is computed once at module import time from HOME, so
    the envoy_home fixture's HOME redirection alone doesn't affect an
    already-imported `tools` module — this mirrors test_tools.py's pattern.
    """
    fake_path = str(envoy_home / "config.json")
    monkeypatch.setattr(tools, "_CONFIG_FILE", fake_path)
    return fake_path


def _tools_by_name(agent_module, session_mgr=None):
    """Call a worker's create() and return {tool_name: callable}."""
    from strands import Agent
    agent_module.create(session_mgr=session_mgr)
    kwargs = Agent.call_args.kwargs
    tools = kwargs.get("tools") or (Agent.call_args.args[0] if Agent.call_args.args else [])
    return {t.__name__: t for t in tools}


# --- Coding worker: allow_edits default + working_directory allow-list ----
#
# coding_worker no longer wraps a Strands agent (see M8 in
# PROJECT-REVIEW-2026-07-06.md — the medium-tier agent whose only job was to
# re-prompt run_coding_agent was removed). run_coding_agent is now a plain
# module-level function called directly by tools.coding_worker, so these
# tests exercise it (and the tools.py tool) directly instead of pulling it
# out of a captured Agent(tools=[...]) kwarg.

class TestCodingWorkerSafety:
    def test_run_coding_agent_defaults_to_no_edits(self):
        import inspect
        from agents.workers import coding_worker
        sig = inspect.signature(coding_worker.run_coding_agent)
        assert sig.parameters["allow_edits"].default is False

    def test_no_allowed_dirs_configured_returns_graceful_error(self, envoy_home, monkeypatch):
        _patch_config_file(monkeypatch, envoy_home)
        from agents.workers import coding_worker
        result = coding_worker.run_coding_agent("do something", working_directory="")
        assert "allowed_dirs" in result

    def test_working_directory_outside_allow_list_rejected(self, envoy_home, monkeypatch, tmp_path):
        config_path = _patch_config_file(monkeypatch, envoy_home)
        allowed = tmp_path / "Documents"
        allowed.mkdir()
        with open(config_path, "w") as f:
            json.dump({"allowed_dirs": [str(allowed)]}, f)

        outside = tmp_path / "Documents-secret"
        outside.mkdir()

        from agents.workers import coding_worker
        result = coding_worker.run_coding_agent("do something", working_directory=str(outside))
        assert "not allowed" in result.lower()

    def test_working_directory_inside_allow_list_proceeds_past_validation(self, envoy_home, monkeypatch, tmp_path):
        config_path = _patch_config_file(monkeypatch, envoy_home)
        allowed = tmp_path / "Projects"
        allowed.mkdir()
        with open(config_path, "w") as f:
            json.dump({"allowed_dirs": [str(allowed)]}, f)

        from agents.workers import coding_worker
        monkeypatch.setattr(coding_worker, "_find_cli", lambda: ("", ""))
        result = coding_worker.run_coding_agent("do something", working_directory=str(allowed))
        # Passed the allow-list check and reached the "no CLI found" branch,
        # not the directory-rejection branch.
        assert "No coding CLI found" in result

    def test_empty_working_directory_still_validated(self, envoy_home, monkeypatch, tmp_path):
        """Even the default (cwd) must be checked against the allow-list."""
        config_path = _patch_config_file(monkeypatch, envoy_home)
        allowed = tmp_path / "Projects"
        allowed.mkdir()
        with open(config_path, "w") as f:
            json.dump({"allowed_dirs": [str(allowed)]}, f)

        # cwd (os.getcwd()) is very unlikely to be under tmp_path/Projects.
        from agents.workers import coding_worker
        result = coding_worker.run_coding_agent("do something", working_directory="")
        assert "not allowed" in result.lower()


# --- tools.coding_worker: direct call to run_coding_agent, no worker hop ---

class TestCodingWorkerToolDirectCall:
    def test_tool_calls_module_function_directly_no_agent_hop(self, monkeypatch):
        """tools.coding_worker must call run_coding_agent directly rather than
        going through _delegate/get_worker — the M8 double-hop this replaces.
        """
        import tools

        called = {}

        def _fake_run_coding_agent(task, working_directory="", allow_edits=False):
            called["args"] = (task, working_directory, allow_edits)
            return "✅ done"

        monkeypatch.setattr("agents.workers.coding_worker.run_coding_agent", _fake_run_coding_agent)

        def _fail_if_delegated(*a, **k):
            raise AssertionError("coding_worker tool should not call _delegate")
        monkeypatch.setattr(tools, "_delegate", _fail_if_delegated)

        result = tools.coding_worker("fix the bug", working_directory="/tmp/proj", allow_edits=True)

        assert result == "✅ done"
        assert called["args"] == ("fix the bug", "/tmp/proj", True)

    def test_tool_defaults_allow_edits_false(self, monkeypatch):
        import tools

        called = {}

        def _fake_run_coding_agent(task, working_directory="", allow_edits=False):
            called["allow_edits"] = allow_edits
            return "ok"

        monkeypatch.setattr("agents.workers.coding_worker.run_coding_agent", _fake_run_coding_agent)

        tools.coding_worker("look at this")

        assert called["allow_edits"] is False


# --- agents/workers/__init__.py: coding is deregistered as a worker --------

class TestCodingWorkerDeregistered:
    def test_coding_not_in_worker_names(self):
        from agents.workers import WORKER_NAMES
        assert "coding" not in WORKER_NAMES

    def test_get_worker_rejects_coding(self):
        from agents.workers import get_worker
        with pytest.raises(ValueError):
            get_worker("coding")


# --- Email worker: confirmation gate on send/reply/forward/delete ---------

class TestEmailWorkerConfirmation:
    def test_send_email_requires_confirmation_first_call(self, envoy_home):
        from agents.workers import email_worker
        tool_fns = _tools_by_name(email_worker)
        result = tool_fns["send_email"]("bob@example.com", "Hi", "body")
        assert "Confirmation required" in result

    def test_send_email_proceeds_after_affirmative_retry(self, envoy_home, monkeypatch):
        from agents.workers import email_worker
        tool_fns = _tools_by_name(email_worker)

        called = {}

        def _fake_outlook_tool(name, args):
            called["args"] = (name, args)
            return "sent"

        monkeypatch.setattr("tools._outlook_tool", _fake_outlook_tool)

        first = tool_fns["send_email"]("bob@example.com", "Hi", "body")
        assert "Confirmation required" in first

        confirm_mod.set_user_turn("yes")
        second = tool_fns["send_email"]("bob@example.com", "Hi", "body")
        assert second == "sent"
        assert called["args"][0] == "email_send"

    def test_delete_requires_confirmation(self, envoy_home):
        from agents.workers import email_worker
        tool_fns = _tools_by_name(email_worker)
        result = tool_fns["delete"]("conv-1,conv-2")
        assert "Confirmation required" in result


# --- Comms worker: confirmation gate on send_message -----------------------

class TestCommsWorkerConfirmation:
    def test_send_message_requires_confirmation_first_call(self, envoy_home):
        from agents.workers import comms_worker
        tools = _tools_by_name(comms_worker)
        result = tools["send_message"]("alice", "hello there")
        assert "Confirmation required" in result

    def test_send_message_proceeds_after_affirmative_retry(self, envoy_home, monkeypatch):
        from agents.workers import comms_worker
        tools = _tools_by_name(comms_worker)

        from agents import slack_agent as slack_mod
        async def _fake_send_dm(recipient, message, thread_ts=""):
            return "message sent"
        monkeypatch.setattr(slack_mod, "send_dm", _fake_send_dm)

        first = tools["send_message"]("alice", "hello there")
        assert "Confirmation required" in first

        confirm_mod.set_user_turn("go ahead")
        second = tools["send_message"]("alice", "hello there")
        assert second == "message sent"


# --- dispatch.py wiring: set_user_turn is called on every dispatch --------

class TestDispatchWiresConfirm:
    def test_dispatch_records_user_turn(self, envoy_home):
        import dispatch

        class FakeAgent:
            def __call__(self, prompt):
                return "ok"

        dispatch.dispatch("some freeform message", FakeAgent())
        assert confirm_mod._state["user_turn"] == "some freeform message"
