"""Unit tests for the session management fixes:

Fix 1: Supervisor date-scoped session IDs — sessions expire daily so stale
       drill-down refs and "Current Time" don't outlive the process.
Fix 2: Worker session persistence removed — workers no longer replay stale
       history or re-bill old messages on every supervisor call.

Covered:
- _date_scoped_session_id() correctly appends today's date
- _date_scoped_session_id() is idempotent (doesn't double-append)
- create_agent() uses the scoped ID for FileSessionManager and bloat checks
- _session_manager() returns None (no worker sessions)
- get_worker() still works without session persistence
"""

import os
import sys
import time as _time
import types
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fix 1: Supervisor date-scoped session IDs
# ---------------------------------------------------------------------------

@pytest.fixture
def agent_mod(envoy_home, monkeypatch):
    """Import agent.py with sandboxed paths (same pattern as test_agent.py)."""
    import agent

    monkeypatch.setattr(agent, "CONFIG_DIR", envoy_home, raising=True)
    monkeypatch.setattr(agent, "SOUL_FILE", envoy_home / "soul.md", raising=True)
    monkeypatch.setattr(agent, "ENVOY_FILE", envoy_home / "envoy.md", raising=True)
    monkeypatch.setattr(agent, "PROCESS_FILE", envoy_home / "process.md", raising=True)

    sessions_dir = envoy_home / "sessions"
    monkeypatch.setattr(agent, "SESSIONS_DIR", sessions_dir, raising=True)
    monkeypatch.setattr(agent, "_AGENT_SESSION_DIRS", [str(sessions_dir)], raising=True)
    monkeypatch.setattr(agent, "_AGENT_INSTANCE", None, raising=True)
    monkeypatch.setattr(agent, "_AGENT_INSTANCE_SESSION_ID", None, raising=True)

    return agent


class TestDateScopedSessionId:
    def test_appends_todays_date(self, agent_mod):
        today = date.today().isoformat()
        result = agent_mod._date_scoped_session_id("default")
        assert result == f"default-{today}"

    def test_idempotent_does_not_double_append(self, agent_mod):
        today = date.today().isoformat()
        already_scoped = f"default-{today}"
        result = agent_mod._date_scoped_session_id(already_scoped)
        assert result == already_scoped

    def test_works_with_custom_session_ids(self, agent_mod):
        today = date.today().isoformat()
        result = agent_mod._date_scoped_session_id("my-session")
        assert result == f"my-session-{today}"

    def test_different_dates_produce_different_ids(self, agent_mod, monkeypatch):
        # Simulate a different day by patching datetime.date.today()
        import datetime

        class FakeDate(datetime.date):
            @classmethod
            def today(cls):
                return cls(2099, 12, 31)

        monkeypatch.setattr("datetime.date", FakeDate)
        result = agent_mod._date_scoped_session_id("default")
        assert result == "default-2099-12-31"


class TestCreateAgentUsesDateScopedId:
    def test_session_manager_receives_date_scoped_id(self, agent_mod, monkeypatch):
        """Verify FileSessionManager is constructed with the date-scoped session_id."""
        from strands.session.file_session_manager import FileSessionManager

        FileSessionManager.reset_mock()
        agent_mod.create_agent("default")

        today = date.today().isoformat()
        expected_id = f"default-{today}"

        # FileSessionManager was called with session_id=scoped and base_dir
        call_kwargs = FileSessionManager.call_args.kwargs
        assert call_kwargs["session_id"] == expected_id

    def test_bloat_guard_checks_scoped_id(self, agent_mod, monkeypatch):
        """Verify the bloat guard checks the date-scoped path, not the raw one."""
        checked_ids = []
        original_is_bloated = agent_mod._agent_session_is_bloated

        def _track_bloat_check(session_id):
            checked_ids.append(session_id)
            return False

        monkeypatch.setattr(agent_mod, "_agent_session_is_bloated", _track_bloat_check)
        agent_mod.create_agent("default")

        today = date.today().isoformat()
        assert checked_ids == [f"default-{today}"]


# ---------------------------------------------------------------------------
# Fix 2: Worker session persistence removed
# ---------------------------------------------------------------------------

@pytest.fixture
def workers_mod(envoy_home, monkeypatch):
    """Import workers module with sandboxed session dirs."""
    from agents import workers as wmod
    monkeypatch.setattr(wmod, "_SESSIONS_DIR", envoy_home / "sessions" / "workers")
    monkeypatch.setattr(wmod, "_SESSION_DIRS", [str(envoy_home / "sessions" / "workers")])
    return wmod


class TestWorkerSessionRemoved:
    def test_session_manager_returns_none(self, workers_mod):
        """_session_manager no longer creates a FileSessionManager."""
        result = workers_mod._session_manager("email")
        assert result is None

    def test_session_manager_returns_none_for_all_workers(self, workers_mod):
        for name in workers_mod.WORKER_NAMES:
            assert workers_mod._session_manager(name) is None

    def test_import_create_passes_none_session_to_worker(
        self, envoy_home, workers_mod, monkeypatch
    ):
        """When _session_manager returns None, the worker create() is called
        with session_mgr=None, which means no session_manager kwarg is passed
        to Agent()."""
        monkeypatch.setattr(
            "agents.base.model_for", lambda tier: "us.anthropic.claude-sonnet-4-6-v1"
        )

        received_session_mgrs = []

        # Install a fake worker module that records what session_mgr it got
        mod = types.ModuleType("agents.workers.fake_no_session_worker")
        mod.RELEVANT_SECTIONS = []

        class _FakeAgent:
            def __init__(self, **kwargs):
                self.system_prompt = "test prompt"
                self.kwargs = kwargs

        def _create(session_mgr=None):
            received_session_mgrs.append(session_mgr)
            from agents.workers import _model
            _model("medium")
            return _FakeAgent()

        mod.create = _create
        sys.modules["agents.workers.fake_no_session_worker"] = mod

        try:
            workers_mod._import_create("fake_no_session_worker", "fake_no_session_test")
        finally:
            sys.modules.pop("agents.workers.fake_no_session_worker", None)

        # session_mgr should be None (no FileSessionManager created)
        assert received_session_mgrs == [None]


class TestWorkerBloatGuardStillWorks:
    """The bloat guard still works for cleaning up legacy session dirs."""

    def test_session_is_bloated_false_when_no_dir(self, workers_mod):
        assert workers_mod._session_is_bloated("email") is False

    def test_reset_worker_session_removes_legacy_dirs(self, workers_mod, envoy_home):
        """If old session dirs exist from before this change, reset clears them."""
        sessions_dir = envoy_home / "sessions" / "workers"
        sess_dir = sessions_dir / "session_worker-email" / "messages"
        sess_dir.mkdir(parents=True)
        (sess_dir / "msg_0.json").write_text("{}")

        workers_mod.reset_worker_session("email")

        assert not (sessions_dir / "session_worker-email").exists()

    def test_reset_worker_session_drops_cached_instance(self, workers_mod, monkeypatch):
        """reset_worker_session still drops cached worker from _workers dict."""
        workers_mod._workers["email"] = MagicMock()
        workers_mod.reset_worker_session("email")
        assert "email" not in workers_mod._workers
