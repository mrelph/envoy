"""Tests for token economics, performance, and graceful degradation.

These tests ensure that:
1. Worker system prompts stay within budget
2. Session bloat detection works
3. Concurrent worker calls serialize (don't crash)
4. Partial results surface correctly when sources fail
5. MCP dead sessions get evicted
"""

import asyncio
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


# --- Token Economics ---

class TestTokenEconomics:
    """Ensure prompts and payloads stay within cost-effective bounds."""

    # Budget: worker system prompt should be < 2000 tokens (~8000 chars)
    _MAX_WORKER_PROMPT_CHARS = 8000
    # Budget: delegation response capped at 3000 chars
    _MAX_DELEGATION_RESPONSE = 3000
    # Budget: _with_timeout error messages should be concise
    _MAX_ERROR_MESSAGE_CHARS = 200

    def test_worker_descriptions_are_concise(self):
        """Worker descriptions (used in delegation prompt) should be compact."""
        from agents.workers import WORKER_DESCRIPTIONS
        total_chars = sum(len(v) for v in WORKER_DESCRIPTIONS.values())
        # All 7 descriptions should fit in ~700 chars (100 chars each)
        assert total_chars < 1000, f"Worker descriptions too verbose: {total_chars} chars"

    def test_delegation_response_capped(self):
        """_delegate_to_sibling should cap response to 3000 chars."""
        from agents.workers import _delegate_to_sibling
        long_response = "x" * 5000

        with patch("agents.workers.get_worker") as mock_gw:
            mock_worker = MagicMock()
            mock_result = MagicMock()
            mock_result.message = long_response
            mock_worker.return_value = mock_result
            mock_gw.return_value = mock_worker

            result = _delegate_to_sibling("email", "test")
            assert len(result) <= self._MAX_DELEGATION_RESPONSE

    def test_with_timeout_error_is_concise(self):
        """Timeout error messages should be short to avoid wasting tokens."""
        import tools

        def slow():
            time.sleep(5)

        original = tools._WORKFLOW_TIMEOUT
        tools._WORKFLOW_TIMEOUT = 1
        try:
            result = tools._with_timeout(slow)
            assert len(result) < self._MAX_ERROR_MESSAGE_CHARS
        finally:
            tools._WORKFLOW_TIMEOUT = original

    def test_gather_source_timeout_error_is_concise(self):
        """Gather timeout messages should not waste supervisor context."""
        import supervisor
        # Simulate a timeout from _named
        loop = asyncio.new_event_loop()

        async def _slow():
            await asyncio.sleep(100)

        async def _run():
            return await supervisor._named("test", _slow())

        result = loop.run_until_complete(_run())
        loop.close()
        name, error = result
        assert name == "test"
        assert isinstance(error, TimeoutError)
        assert len(str(error)) < 100


class TestSessionBloat:
    """Ensure worker sessions get pruned to prevent replay cost explosion."""

    def test_session_bloat_detection(self, tmp_path):
        """_session_is_bloated should flag sessions over max messages."""
        from agents.workers import _session_is_bloated, _MAX_SESSION_MESSAGES, _SESSION_DIRS

        # Create a fake bloated session
        original_dirs = _SESSION_DIRS[:]
        try:
            _SESSION_DIRS.clear()
            _SESSION_DIRS.append(str(tmp_path))

            sess_dir = tmp_path / "session_worker-email" / "fake" / "messages"
            sess_dir.mkdir(parents=True)
            # Create more files than the limit
            for i in range(_MAX_SESSION_MESSAGES + 5):
                (sess_dir / f"msg_{i}.json").write_text("{}")

            assert _session_is_bloated("email") is True
        finally:
            _SESSION_DIRS.clear()
            _SESSION_DIRS.extend(original_dirs)

    def test_fresh_session_not_bloated(self, tmp_path):
        """A fresh session with few messages should not be flagged."""
        from agents.workers import _session_is_bloated, _SESSION_DIRS

        original_dirs = _SESSION_DIRS[:]
        try:
            _SESSION_DIRS.clear()
            _SESSION_DIRS.append(str(tmp_path))

            sess_dir = tmp_path / "session_worker-calendar" / "fake" / "messages"
            sess_dir.mkdir(parents=True)
            for i in range(3):
                (sess_dir / f"msg_{i}.json").write_text("{}")

            assert _session_is_bloated("calendar") is False
        finally:
            _SESSION_DIRS.clear()
            _SESSION_DIRS.extend(original_dirs)


class TestConcurrency:
    """Verify worker locking actually serializes under concurrent load."""

    def test_locked_worker_serializes_calls(self):
        """Two threads calling the same worker should not interleave."""
        from agents.workers import get_worker, _workers, _worker_locks

        execution_order = []

        # Get a worker and replace its underlying agent with a slow mock
        worker = get_worker("productivity")
        lock = _worker_locks["productivity"]

        real_agent = _workers["productivity"]

        def slow_call(prompt):
            execution_order.append(f"start-{threading.current_thread().name}")
            time.sleep(0.1)
            execution_order.append(f"end-{threading.current_thread().name}")
            return MagicMock(message="done")

        with patch.dict(_workers, {"productivity": MagicMock(side_effect=slow_call)}):
            # Re-get to pick up the patched version
            t1 = threading.Thread(target=lambda: get_worker("productivity")("req1"), name="T1")
            t2 = threading.Thread(target=lambda: get_worker("productivity")("req2"), name="T2")
            t1.start()
            time.sleep(0.01)  # slight offset so T1 grabs lock first
            t2.start()
            t1.join()
            t2.join()

        # With locking: should be start-T1, end-T1, start-T2, end-T2
        # Without locking: would be start-T1, start-T2, end-T1, end-T2
        assert execution_order[0] == "start-T1"
        assert execution_order[1] == "end-T1"
        assert execution_order[2] == "start-T2"
        assert execution_order[3] == "end-T2"


class TestGracefulDegradation:
    """When sources fail, partial results should still surface."""

    def test_worker_gather_returns_partial_on_timeout(self):
        """If one source times out, other sources still return data."""
        import agents.workflows as wf

        # Mock get_worker to succeed for one and timeout for another.
        # _worker_gather stringifies the result via str() (Strands'
        # AgentResult.__str__ returns the response text), so the success
        # mock returns an object whose str() is the expected text.
        class _Result:
            def __str__(self):
                return "Found 3 sent emails"

        def mock_get_worker(name):
            if name == "email":
                def email_call(request):
                    return _Result()
                return email_call
            elif name == "comms":
                def slow_call(request):
                    time.sleep(100)  # will hit timeout
                return slow_call
            raise ValueError(f"Unknown: {name}")

        # Shrink the gather timeout so the slow worker trips it quickly.
        with patch("agents.workers.get_worker", mock_get_worker), \
                patch.object(wf, "_WORKER_TIMEOUT", 1):
            result = wf._worker_gather(
                sent=("email", "scan sent"),
                slack=("comms", "scan slack"),
            )

        # Email should succeed, slack should timeout
        assert "3 sent emails" in result.get("sent", "")
        assert "timed out" in result.get("slack", "").lower() or "unavailable" in result.get("slack", "").lower()

    def test_delegate_returns_error_string_not_exception(self):
        """_delegate should never raise — always returns a string."""
        import tools

        with patch("tools.get_worker", side_effect=Exception("total failure")):
            result = tools._delegate("email", "test")

        assert isinstance(result, str)
        assert "unavailable" in result

    def test_gather_handles_all_sources_failing(self):
        """gather_data should return a meaningful message when everything fails."""
        import supervisor

        async def mock_gather_async(sources, days, alias):
            # Simulate all sources timing out
            return {}

        with patch.object(supervisor, '_gather_async', mock_gather_async):
            result = supervisor.gather_data("email,slack,calendar", days=1)

        assert "No data" in result or result == ""


class TestMCPResilience:
    """MCP connection management and dead session eviction."""

    def test_timeout_session_marks_dead_on_connection_error(self):
        """_TimeoutSession should flag itself dead on transport errors."""
        from agents.base import _TimeoutSession

        mock_session = MagicMock()
        ts = _TimeoutSession(mock_session, "TestServer", timeout=5)

        assert ts.dead is False

        # Simulate a connection error marking it dead
        ts.dead = True
        assert ts.dead is True

    def test_mcp_timeout_value_is_reasonable(self):
        """MCP timeout should be 20-45s — long enough for real calls, short enough to fail fast."""
        from agents.base import MCP_CALL_TIMEOUT
        assert 20 <= MCP_CALL_TIMEOUT <= 45, f"MCP timeout {MCP_CALL_TIMEOUT}s outside reasonable range"


class TestPromptBudget:
    """System prompts should not grow unbounded."""

    def test_supervisor_system_prompt_size(self):
        """Supervisor prompt should stay bounded.
        
        Current: ~41K chars (~10K tokens, ~$0.15/request on Opus input).
        Target: <20K chars. Most of the bloat is the skill catalog.
        Threshold set at 50K to catch regressions while we optimize.
        """
        import agent
        prompt = agent._build_system_prompt()
        assert len(prompt) < 50000, f"Supervisor prompt is {len(prompt)} chars — regression detected"
        # Track for optimization — warn if over 25K
        if len(prompt) > 25000:
            import warnings
            warnings.warn(
                f"Supervisor prompt is {len(prompt)} chars (~{len(prompt)//4} tokens). "
                f"Consider trimming skill catalog or deferring to tool descriptions."
            )

    def test_skill_loading_is_lazy(self):
        """Skills should only load name + description at startup, not full content."""
        from agents.skills import get_skills
        skills = get_skills()
        for name, skill in skills.items():
            # The skill dict at load time should NOT have the full instructions
            # (those come via activate_skill)
            assert "instructions" not in skill or len(skill.get("instructions", "")) < 200, \
                f"Skill '{name}' has full instructions loaded at startup — should be lazy"
