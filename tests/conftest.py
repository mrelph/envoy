"""Shared pytest fixtures for the Envoy test suite.

Heavy modules (mcp, boto3, strands) are stubbed out at import time so unit
tests don't need MCP servers, AWS creds, or network access. Tests that
genuinely need those modules can opt back in by importing them directly
inside the test (after the stub is removed) — but the default is "no I/O".
"""

import json
import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# --- Make the project root importable as the top-level package ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# --- Auto-stub heavy optional deps so importing agents.* never tries to spawn
#     MCP subprocesses or talk to Bedrock. Individual tests can monkeypatch
#     more specifically as needed. ---

def _install_strands_stub():
    if "strands" in sys.modules:
        return
    strands = types.ModuleType("strands")

    def _tool_decorator(*dargs, **dkwargs):
        # Supports both @tool and @tool(...)
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return dargs[0]
        def _wrap(fn):
            return fn
        return _wrap

    strands.tool = _tool_decorator
    strands.Agent = MagicMock(name="Agent")

    models_mod = types.ModuleType("strands.models")
    models_mod.BedrockModel = MagicMock(name="BedrockModel")

    session_mod = types.ModuleType("strands.session")
    fsm_mod = types.ModuleType("strands.session.file_session_manager")
    fsm_mod.FileSessionManager = MagicMock(name="FileSessionManager")
    session_mod.file_session_manager = fsm_mod

    types_mod = types.ModuleType("strands.types")
    content_mod = types.ModuleType("strands.types.content")
    content_mod.SystemContentBlock = MagicMock(name="SystemContentBlock")
    types_mod.content = content_mod

    sys.modules["strands"] = strands
    sys.modules["strands.models"] = models_mod
    sys.modules["strands.session"] = session_mod
    sys.modules["strands.session.file_session_manager"] = fsm_mod
    sys.modules["strands.types"] = types_mod
    sys.modules["strands.types.content"] = content_mod


def _install_mcp_stub():
    if "mcp" in sys.modules:
        return
    mcp = types.ModuleType("mcp")
    mcp.ClientSession = MagicMock(name="ClientSession")
    mcp.StdioServerParameters = MagicMock(name="StdioServerParameters")

    client_mod = types.ModuleType("mcp.client")
    stdio_mod = types.ModuleType("mcp.client.stdio")
    stdio_mod.stdio_client = MagicMock(name="stdio_client")
    client_mod.stdio = stdio_mod

    sys.modules["mcp"] = mcp
    sys.modules["mcp.client"] = client_mod
    sys.modules["mcp.client.stdio"] = stdio_mod


_install_strands_stub()
_install_mcp_stub()


# --- Per-test sandboxing: redirect ~/.envoy and CWD to a tmpdir ---

@pytest.fixture
def envoy_home(tmp_path, monkeypatch):
    """Redirect $HOME so ~/.envoy lives under a tmpdir.

    Many modules write to ~/.envoy/* on import or first use. Call this fixture
    in any test that touches config, memory, sent.json, models.json, etc.
    """
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    # Some platforms read these instead of HOME
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    envoy_dir = fake_home / ".envoy"
    envoy_dir.mkdir()
    return envoy_dir


@pytest.fixture
def fake_mcp_result():
    """Build a fake MCP CallToolResult-like object from a Python value."""
    def _build(value):
        item = MagicMock()
        item.text = json.dumps(value) if not isinstance(value, str) else value
        result = MagicMock()
        result.content = [item]
        return result
    return _build


@pytest.fixture
def no_ai(monkeypatch):
    """Stub agents.base.invoke_ai so tests never hit Bedrock.

    Returns a list that records every prompt that would have been sent.
    Tests can override the return value by setting `no_ai.response`.
    """
    state = {"response": "OK"}

    class _Recorder(list):
        def set_response(self, r):
            state["response"] = r

    calls = _Recorder()

    def _fake_invoke(prompt, max_tokens=10000, tier="heavy"):
        calls.append({"prompt": prompt, "max_tokens": max_tokens, "tier": tier})
        return state["response"]

    # Patch every module that has imported invoke_ai by name, so
    # `from agents.base import invoke_ai` in callers gets stubbed too.
    try:
        from agents import base
        monkeypatch.setattr(base, "invoke_ai", _fake_invoke)
        for mod_name in ("agents.skill_builder", "agents.learning",
                         "agents.email", "agents.workflows", "agents.memory2"):
            try:
                import importlib
                mod = importlib.import_module(mod_name)
                if hasattr(mod, "invoke_ai"):
                    monkeypatch.setattr(mod, "invoke_ai", _fake_invoke)
            except Exception:
                pass
    except Exception:
        pass
    return calls
