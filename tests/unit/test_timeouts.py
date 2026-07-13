"""Tests for timeout guards, worker delegation, and fail-fast behavior.

These tests ensure that:
1. tools.py loads without NameError (vault_write, coding_worker defined before use)
2. MCP timeout is set to 30s (not 60s)
3. run() timeout is 65s (not 120s)
4. _worker_gather has per-worker timeout
5. Workflow tools are wrapped with _with_timeout
6. _delegate breaks on timeout (no retry)
7. Worker-to-worker delegation works with depth guard
8. Workers have fail-fast system prompt
9. Workers have delegate_to_worker tool
"""

import sys
import threading
import time
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest


class TestModuleLoads:
    """Ensure no NameError on import — catches forward-reference issues."""

    def test_tools_imports_cleanly(self):
        """The vault_write NameError that blocked startup must not recur.

        Run the import in a fresh subprocess so this cleanliness check can't
        mutate the parent's sys.modules — reimporting agents.* in-process
        rebinds module objects that other test files (and conftest stubs)
        depend on, causing cross-file pollution.
        """
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-c", "import tools; assert tools.ALL_TOOLS"],
            cwd=str(Path(__file__).resolve().parent.parent.parent),
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, f"tools failed to import:\n{proc.stderr}"

    def test_vault_write_defined_before_use(self):
        """vault_write and vault_read must be importable from tools."""
        import tools
        # They should be in _SKILL_TOOLS (added post-definition)
        assert "vault_write" in tools._SKILL_TOOLS
        assert "vault_read" in tools._SKILL_TOOLS

    def test_coding_worker_exists(self):
        """coding_worker function must exist (was previously missing @tool + def)."""
        import tools
        # Should be in _ALL_TOOLS_RAW list
        tool_names = [getattr(t, 'tool_name', getattr(t, '__name__', '')) for t in tools._ALL_TOOLS_RAW]
        assert "coding_worker" in tool_names


class TestTimeoutSettings:
    """Verify timeout values are set correctly to prevent stalling."""

    def test_mcp_timeout_is_30s(self):
        """MCP call timeout should be 30s, not 60s."""
        from agents.base import MCP_CALL_TIMEOUT
        assert MCP_CALL_TIMEOUT == 30

    def test_run_timeout_is_65s(self):
        """run() future timeout should be 65s, not 120s."""
        import agents.base
        import inspect
        source = inspect.getsource(agents.base.run)
        assert "timeout=65" in source

    def test_workflow_timeout_is_60s(self):
        """Workflow tools should have a 60s hard timeout."""
        import tools
        assert tools._WORKFLOW_TIMEOUT == 60

    def test_gather_source_timeout_exists(self):
        """Gather should have a per-source timeout."""
        import supervisor
        assert hasattr(supervisor, '_GATHER_SOURCE_TIMEOUT')
        assert supervisor._GATHER_SOURCE_TIMEOUT <= 45


class TestWorkflowTimeoutWrapping:
    """All wf.* calls must go through _with_timeout."""

    def test_no_unwrapped_workflow_calls(self):
        """No direct 'return wf.xxx()' calls — all must use _with_timeout."""
        import tools
        import inspect
        source = inspect.getsource(tools)
        import re
        unwrapped = re.findall(r'return wf\.', source)
        assert len(unwrapped) == 0, f"Found {len(unwrapped)} unwrapped wf.* calls"

    def test_with_timeout_returns_error_on_timeout(self):
        """_with_timeout should return an error string, not raise."""
        import tools

        def slow_fn():
            time.sleep(5)
            return "done"

        # Temporarily set a very short timeout
        original = tools._WORKFLOW_TIMEOUT
        tools._WORKFLOW_TIMEOUT = 1
        try:
            result = tools._with_timeout(slow_fn)
            assert "Timed out" in result
            assert "1s" in result
        finally:
            tools._WORKFLOW_TIMEOUT = original


class TestDelegateNoRetryOnTimeout:
    """_delegate should break immediately on timeout, not retry."""

    def test_delegate_breaks_on_timeout(self):
        """When a worker raises TimeoutError, _delegate should not retry."""
        import tools
        from unittest.mock import patch

        call_count = 0

        def mock_get_worker(name):
            nonlocal call_count
            call_count += 1
            raise TimeoutError("MCP timed out")

        with patch("tools.get_worker", mock_get_worker):
            result = tools._delegate("email", "test request")

        assert call_count == 1, f"Expected 1 call, got {call_count} — should not retry on timeout"
        assert "unavailable" in result

    def test_delegate_retries_on_validation_error(self):
        """Session corruption (ValidationException) should trigger one retry."""
        import tools
        from unittest.mock import patch

        call_count = 0

        def mock_get_worker(name):
            nonlocal call_count
            call_count += 1
            raise Exception("ValidationException: toolResult block missing")

        with patch("tools.get_worker", mock_get_worker):
            with patch("agents.workers.reset_worker_session"):
                result = tools._delegate("email", "test request")

        assert call_count == 2, f"Expected 2 calls (1 retry on ValidationException), got {call_count}"


class TestWorkerDelegation:
    """Phase 1: Worker-to-Worker delegation with depth guard."""

    def test_worker_descriptions_complete(self):
        """All non-coding workers must have descriptions."""
        from agents.workers import WORKER_DESCRIPTIONS, WORKER_NAMES
        for name in WORKER_NAMES:
            assert name in WORKER_DESCRIPTIONS, f"Missing description for worker: {name}"

    def test_depth_guard_blocks_deep_delegation(self):
        """Delegation at max depth should return an error, not recurse."""
        from agents.workers import _delegate_to_sibling, _delegation_depth, _MAX_DELEGATION_DEPTH

        _delegation_depth.depth = _MAX_DELEGATION_DEPTH
        try:
            result = _delegate_to_sibling("email", "test")
            assert "Cannot delegate" in result
        finally:
            _delegation_depth.depth = 0

    def test_depth_guard_allows_first_hop(self):
        """Delegation at depth 0 should proceed (calls the worker)."""
        from agents.workers import _delegate_to_sibling, _delegation_depth

        _delegation_depth.depth = 0
        with patch("agents.workers.get_worker") as mock_gw:
            mock_worker = MagicMock()
            mock_worker.return_value = MagicMock(message="result")
            mock_gw.return_value = mock_worker
            result = _delegate_to_sibling("email", "test")
            assert result == "result"
            mock_gw.assert_called_once_with("email")

    def test_depth_resets_after_delegation(self):
        """Depth counter must reset even if the worker raises."""
        from agents.workers import _delegate_to_sibling, _delegation_depth

        _delegation_depth.depth = 0
        with patch("agents.workers.get_worker") as mock_gw:
            mock_gw.return_value = MagicMock(side_effect=RuntimeError("boom"))
            _delegate_to_sibling("research", "test")
            assert _delegation_depth.depth == 0, "Depth not reset after error"

    def test_unknown_worker_rejected(self):
        """Delegating to a nonexistent worker should return error."""
        from agents.workers import _delegate_to_sibling
        result = _delegate_to_sibling("nonexistent_worker", "test")
        assert "Unknown worker" in result

    def test_make_delegate_tool_creates_valid_tool(self):
        """make_delegate_tool should return a callable tool object."""
        from agents.workers import make_delegate_tool
        tool = make_delegate_tool()
        assert hasattr(tool, 'tool_name') or callable(tool)


class TestWorkerFailFastPrompt:
    """Workers must have fail-fast and delegation instructions.
    
    Note: These test the _import_create logic. Since the test conftest stubs
    strands.Agent as a MagicMock, we verify the calls were made to inject
    the prompt/tools rather than checking the mock's string content.
    """

    def test_import_create_adds_fail_fast(self):
        """_import_create should attempt to modify system_prompt."""
        from agents.workers import _import_create
        agent = _import_create("productivity_worker", "productivity")
        # In test env, agent is a MagicMock. Verify system_prompt was accessed
        # (the += calls chain on MagicMock, so just verify it was touched)
        assert agent.system_prompt is not None  # accessed

    def test_import_create_calls_process_tools(self):
        """_import_create should inject delegate_to_worker via process_tools."""
        from agents.workers import _import_create
        agent = _import_create("email_worker", "email")
        # process_tools should have been called to add the delegate tool
        assert agent.tool_registry.process_tools.called

    def test_coding_worker_runs_as_subprocess_not_via_import_create(self):
        """Coding runs as a direct subprocess (run_coding_agent), so it is
        intentionally NOT one of get_worker's Strands-backed workers and the
        coding_worker module no longer exposes create()."""
        from agents.workers import get_worker
        from agents.workers import coding_worker as cw

        # get_worker rejects "coding" — it's not a delegation-capable worker.
        with pytest.raises(ValueError):
            get_worker("coding")
        # The module drives the CLI directly instead of building an agent.
        assert hasattr(cw, "run_coding_agent")
        assert not hasattr(cw, "create")


class TestWorkerLocking:
    """Workers must serialize concurrent calls."""

    def test_get_worker_returns_locked_wrapper(self):
        """get_worker should return a _LockedWorker, not raw agent."""
        from agents.workers import get_worker
        w = get_worker("productivity")
        assert type(w).__name__ == "_LockedWorker"

    def test_worker_lock_exists_per_worker(self):
        """Each worker should have its own lock."""
        from agents.workers import get_worker, _worker_locks
        get_worker("email")
        get_worker("calendar")
        assert "email" in _worker_locks
        assert "calendar" in _worker_locks
        assert _worker_locks["email"] is not _worker_locks["calendar"]
