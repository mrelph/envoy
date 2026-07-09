"""Unit tests for agent.py.

Covers the supervisor session bloat guard (mirrors the worker guard in
agents/workers/__init__.py), the model_for() lookup replacing the hardcoded
default model ID, get_agent()'s per-session caching, and the system-prompt
text (learning-loop contradiction fix + untrusted-content guardrail).

All heavy modules (strands, mcp) are stubbed by tests/conftest.py, so
create_agent() can be called directly without touching Bedrock or spawning
MCP subprocesses.
"""

import os
import time as _time

import pytest


@pytest.fixture
def agent_mod(envoy_home, monkeypatch):
    """Import agent.py and redirect its config/session paths into the tmp sandbox.

    agent.py computes CONFIG_DIR/SESSIONS_DIR (and friends) from Path.home()
    at import time, before envoy_home can patch $HOME — so tests patch the
    module attributes directly, same pattern as test_skills.py / test_skill_builder.py.
    """
    import agent

    monkeypatch.setattr(agent, "CONFIG_DIR", envoy_home, raising=True)
    monkeypatch.setattr(agent, "SOUL_FILE", envoy_home / "soul.md", raising=True)
    monkeypatch.setattr(agent, "ENVOY_FILE", envoy_home / "envoy.md", raising=True)
    monkeypatch.setattr(agent, "PROCESS_FILE", envoy_home / "process.md", raising=True)

    sessions_dir = envoy_home / "sessions"
    monkeypatch.setattr(agent, "SESSIONS_DIR", sessions_dir, raising=True)
    # _AGENT_SESSION_DIRS is a module-level list baked from SESSIONS_DIR at
    # import time; swap it too so the bloat guard only looks in the sandbox
    # (and never touches the real /tmp/strands/sessions).
    monkeypatch.setattr(agent, "_AGENT_SESSION_DIRS", [str(sessions_dir)], raising=True)

    # Reset the module-level agent cache so tests don't leak into each other.
    monkeypatch.setattr(agent, "_AGENT_INSTANCE", None, raising=True)
    monkeypatch.setattr(agent, "_AGENT_INSTANCE_SESSION_ID", None, raising=True)

    return agent


def _make_session_messages(sessions_dir, session_id, n_messages, age_hours=0.0):
    """Create n_messages files under sessions_dir/session_<id>/messages with a given age."""
    msgs = sessions_dir / f"session_{session_id}" / "messages"
    msgs.mkdir(parents=True, exist_ok=True)
    mtime = _time.time() - age_hours * 3600
    for i in range(n_messages):
        f = msgs / f"msg_{i}.json"
        f.write_text("{}")
        os.utime(f, (mtime, mtime))
    return msgs


# ---------------------------------------------------------------------------
# Session bloat guard
# ---------------------------------------------------------------------------

class TestAgentSessionBloatGuard:
    def test_no_session_on_disk_is_not_bloated(self, agent_mod):
        assert agent_mod._agent_session_is_bloated("default") is False

    def test_few_fresh_messages_is_not_bloated(self, agent_mod):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=5)
        assert agent_mod._agent_session_is_bloated("default") is False

    def test_message_count_below_cap_is_not_bloated(self, agent_mod):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=39)
        assert agent_mod._agent_session_is_bloated("default") is False

    def test_message_count_at_cap_is_bloated(self, agent_mod):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=40)
        assert agent_mod._agent_session_is_bloated("default") is True

    def test_recent_but_over_cap_is_bloated(self, agent_mod):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=100)
        assert agent_mod._agent_session_is_bloated("default") is True

    def test_stale_session_under_age_cap_is_not_bloated(self, agent_mod):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=3, age_hours=11)
        assert agent_mod._agent_session_is_bloated("default") is False

    def test_stale_session_over_age_cap_is_bloated(self, agent_mod):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=3, age_hours=13)
        assert agent_mod._agent_session_is_bloated("default") is True

    def test_different_session_ids_are_independent(self, agent_mod):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=40)
        assert agent_mod._agent_session_is_bloated("default") is True
        assert agent_mod._agent_session_is_bloated("other-session") is False

    def test_reset_agent_session_removes_on_disk_state(self, agent_mod):
        msgs = _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=40)
        assert msgs.exists()
        agent_mod._reset_agent_session("default")
        assert not (agent_mod.SESSIONS_DIR / "session_default").exists()

    def test_reset_agent_session_on_missing_dir_is_a_noop(self, agent_mod):
        # Should not raise even if nothing exists on disk yet.
        agent_mod._reset_agent_session("never-created")


class TestCreateAgentResetsBloat:
    def test_create_agent_wipes_bloated_session_before_building(self, agent_mod, monkeypatch):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=50)
        session_path = agent_mod.SESSIONS_DIR / "session_default"
        assert session_path.exists()

        agent_mod.create_agent("default")

        # The stub FileSessionManager (a MagicMock) never recreates the dir,
        # so its continued absence proves the bloat guard fired first.
        assert not session_path.exists()

    def test_create_agent_leaves_healthy_session_alone(self, agent_mod):
        _make_session_messages(agent_mod.SESSIONS_DIR, "default", n_messages=5)
        session_path = agent_mod.SESSIONS_DIR / "session_default"
        assert session_path.exists()

        agent_mod.create_agent("default")

        assert session_path.exists()


# ---------------------------------------------------------------------------
# Model lookup (item 4: no hardcoded model ID)
# ---------------------------------------------------------------------------

class TestCreateAgentModelLookup:
    def test_create_agent_uses_model_for_agent_tier(self, agent_mod, monkeypatch):
        import agents.base as base
        monkeypatch.setattr(base, "model_for", lambda tier: f"sentinel::{tier}", raising=True)

        from strands.models import BedrockModel

        agent_mod.create_agent("default")

        assert BedrockModel.call_args.kwargs["model_id"] == "sentinel::agent"

    def test_create_agent_never_hardcodes_default_model_id(self, agent_mod, monkeypatch):
        # Guard against regressing back to a literal model string in agent.py:
        # model_for() must be consulted, and its return value used verbatim.
        import agents.base as base
        sentinel = "us.anthropic.made-up-test-model-v1"
        monkeypatch.setattr(base, "model_for", lambda tier: sentinel, raising=True)

        from strands.models import BedrockModel

        agent_mod.create_agent("default")

        assert BedrockModel.call_args.kwargs["model_id"] == sentinel


# ---------------------------------------------------------------------------
# get_agent() per-session caching (item 4: session_id was previously ignored)
# ---------------------------------------------------------------------------

class TestGetAgentSessionCaching:
    def test_get_agent_creates_on_first_call(self, agent_mod, monkeypatch):
        calls = []

        def fake_create(session_id="default"):
            calls.append(session_id)
            return object()

        monkeypatch.setattr(agent_mod, "create_agent", fake_create, raising=True)

        agent_mod.get_agent("sess-a")

        assert calls == ["sess-a"]

    def test_get_agent_caches_for_same_session_id(self, agent_mod, monkeypatch):
        calls = []

        def fake_create(session_id="default"):
            calls.append(session_id)
            return object()

        monkeypatch.setattr(agent_mod, "create_agent", fake_create, raising=True)

        a1 = agent_mod.get_agent("sess-a")
        a2 = agent_mod.get_agent("sess-a")

        assert a1 is a2
        assert calls == ["sess-a"]

    def test_get_agent_rebuilds_for_a_different_session_id(self, agent_mod, monkeypatch):
        calls = []

        def fake_create(session_id="default"):
            calls.append(session_id)
            return object()

        monkeypatch.setattr(agent_mod, "create_agent", fake_create, raising=True)

        a1 = agent_mod.get_agent("sess-a")
        a2 = agent_mod.get_agent("sess-b")
        a1_again = agent_mod.get_agent("sess-a")

        assert a1 is not a2
        assert a1_again is a2 or a1_again is not a1  # switched back == rebuild, not a1
        assert calls == ["sess-a", "sess-b", "sess-a"]

    def test_reload_agent_clears_cache_and_session_id(self, agent_mod, monkeypatch):
        monkeypatch.setattr(agent_mod, "_AGENT_INSTANCE", object(), raising=True)
        monkeypatch.setattr(agent_mod, "_AGENT_INSTANCE_SESSION_ID", "sess-a", raising=True)

        agent_mod.reload_agent()

        assert agent_mod._AGENT_INSTANCE is None
        assert agent_mod._AGENT_INSTANCE_SESSION_ID is None


# ---------------------------------------------------------------------------
# System prompt: learning-loop contradiction fix + untrusted-content guardrail
# ---------------------------------------------------------------------------

class TestSystemPromptText:
    def test_builds_without_crashing(self, agent_mod):
        prompt = agent_mod._build_system_prompt()
        assert "Envoy" in prompt
        assert "## GUARDRAILS" in prompt

    def test_no_longer_claims_corrections_skip_confirmation(self, agent_mod):
        prompt = agent_mod._build_system_prompt()
        assert "without needing explicit confirmation" not in prompt

    def test_learning_loop_describes_pending_queue_and_confirmation(self, agent_mod):
        prompt = agent_mod._build_system_prompt()
        lower = prompt.lower()
        assert "pending queue" in lower
        assert "process.md" in lower
        # Both the "active learning" bullet and the GUARDRAILS bullet should
        # agree nothing lands in process.md without the user confirming.
        assert "confirm" in lower

    def test_update_process_still_requires_confirmation(self, agent_mod):
        prompt = agent_mod._build_system_prompt()
        assert "update_process" in prompt
        guardrails = prompt.split("## GUARDRAILS", 1)[1]
        assert "update_process" in guardrails
        assert "confirm" in guardrails.lower()

    def test_untrusted_content_guardrail_present(self, agent_mod):
        prompt = agent_mod._build_system_prompt()
        guardrails = prompt.split("## GUARDRAILS", 1)[1]
        assert "<untrusted_content" in guardrails
        assert "CONTENT SAFETY DIRECTIVE" in guardrails
        assert "DATA" in guardrails

    def test_untrusted_content_guardrail_covers_key_actions(self, agent_mod):
        prompt = agent_mod._build_system_prompt()
        guardrails = prompt.split("## GUARDRAILS", 1)[1].lower()
        for action in ("sending", "forwarding", "deleting", "running code"):
            assert action in guardrails
