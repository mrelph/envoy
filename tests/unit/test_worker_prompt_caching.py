"""Unit tests for agents/workers/__init__.py:

- Context bus cap behavior (always evict expired, hard-cap at 50 oldest-first).
- Worker system-prompt cachePoint wrapping (_supports_prompt_caching /
  _system_prompt_for_model), mirroring agent.py's supervisor-side helper.
- _import_create's prompt assembly order: process.md rules are concatenated
  as plain text *before* the result is wrapped in cachePoint block form.
"""

import sys
import time
import types

import pytest


# --- Context bus cap ---------------------------------------------------

class TestContextBusCap:
    def setup_method(self):
        from agents.workers import clear_bus
        clear_bus()

    def teardown_method(self):
        from agents.workers import clear_bus
        clear_bus()

    def test_fresh_entries_over_cap_are_trimmed_to_50(self):
        from agents.workers import post_context, _bus
        for i in range(60):
            post_context(f"key{i}", f"value{i}", source="test")
        assert len(_bus) == 50

    def test_oldest_fresh_entries_evicted_first(self):
        from agents.workers import post_context, _bus
        for i in range(55):
            post_context(f"key{i}", f"value{i}", source="test")
        # First 5 posted (oldest) should be gone; the most recent 50 remain.
        for i in range(5):
            assert f"key{i}" not in _bus
        for i in range(5, 55):
            assert f"key{i}" in _bus
        assert len(_bus) == 50

    def test_at_or_under_cap_nothing_evicted(self):
        from agents.workers import post_context, _bus
        for i in range(50):
            post_context(f"key{i}", f"value{i}", source="test")
        assert len(_bus) == 50
        for i in range(50):
            assert f"key{i}" in _bus

    def test_expired_entries_evicted_even_when_under_cap(self, monkeypatch):
        from agents.workers import post_context, _bus
        post_context("old1", "v", source="test")
        post_context("old2", "v", source="test")

        real_monotonic = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: real_monotonic() + 2000)

        post_context("new1", "v", source="test")

        assert "old1" not in _bus
        assert "old2" not in _bus
        assert "new1" in _bus
        assert len(_bus) == 1


# --- cachePoint helpers --------------------------------------------------

class TestSupportsPromptCaching:
    def test_claude_model_is_eligible(self):
        from agents.workers import _supports_prompt_caching
        assert _supports_prompt_caching("us.anthropic.claude-sonnet-4-6-v1")

    def test_nova_model_is_eligible(self):
        from agents.workers import _supports_prompt_caching
        assert _supports_prompt_caching("us.amazon.nova-micro-v1:0")

    def test_other_model_is_not_eligible(self):
        from agents.workers import _supports_prompt_caching
        assert not _supports_prompt_caching("meta.llama3-70b-instruct-v1:0")


class TestSystemPromptForModel:
    def test_non_eligible_model_returns_plain_string(self):
        from agents.workers import _system_prompt_for_model
        result = _system_prompt_for_model("hello world", "meta.llama3-70b-instruct-v1:0")
        assert result == "hello world"

    def test_eligible_model_wraps_full_text_in_cachepoint_block(self):
        from agents.workers import _system_prompt_for_model
        from strands.types.content import SystemContentBlock

        SystemContentBlock.reset_mock()
        text = "BASE PROMPT\n\nProcess rules (learned from user corrections):\n- rule one"

        result = _system_prompt_for_model(text, "us.anthropic.claude-sonnet-4-6-v1")

        assert isinstance(result, list)
        assert len(result) == 2
        calls = SystemContentBlock.call_args_list
        assert calls[-2].kwargs == {"text": text}
        assert calls[-1].kwargs == {"cachePoint": {"type": "default"}}


# --- _import_create prompt assembly + wrapping --------------------------

class _FakeAgent:
    def __init__(self, system_prompt):
        self.system_prompt = system_prompt


def _install_fake_worker_module(name, base_prompt, relevant_sections=None, model_tier="medium"):
    """Register a fake agents.workers.<name> module with a create() that
    mimics a real worker module: calls _model(tier) (so _last_model_id gets
    recorded, exactly as every real worker's create() does) and returns an
    object with a plain-string system_prompt.
    """
    mod = types.ModuleType(f"agents.workers.{name}")
    mod.RELEVANT_SECTIONS = relevant_sections or []

    def _create(session_mgr=None):
        from agents.workers import _model
        _model(model_tier)
        return _FakeAgent(base_prompt)

    mod.create = _create
    sys.modules[f"agents.workers.{name}"] = mod
    return mod


@pytest.fixture
def _redirect_worker_sessions(envoy_home, monkeypatch):
    """Point _SESSIONS_DIR at the sandboxed home so _session_manager's mkdir
    doesn't touch the real filesystem."""
    from agents import workers as workers_mod
    monkeypatch.setattr(workers_mod, "_SESSIONS_DIR", envoy_home / "sessions" / "workers")


class TestImportCreatePromptAssembly:
    def _cleanup(self, name):
        sys.modules.pop(f"agents.workers.{name}", None)

    def test_eligible_model_full_assembled_prompt_gets_cachepoint(
        self, envoy_home, _redirect_worker_sessions, monkeypatch
    ):
        from agents import workers as workers_mod
        from strands.types.content import SystemContentBlock

        (envoy_home / "process.md").write_text(
            "## TestSection\n- Always double-check dates\n"
        )
        monkeypatch.setattr(
            "agents.base.model_for", lambda tier: "us.anthropic.claude-sonnet-4-6-v1"
        )

        mod_name = "fake_cache_eligible_worker"
        self._cleanup(mod_name)
        _install_fake_worker_module(
            mod_name, "You are a fake worker.", relevant_sections=["TestSection"]
        )
        SystemContentBlock.reset_mock()

        try:
            agent = workers_mod._import_create(mod_name, "fake_cache_eligible_test")
        finally:
            self._cleanup(mod_name)

        expected_full_prompt = (
            "You are a fake worker."
            "\n\nProcess rules (learned from user corrections):\n"
            "- Always double-check dates"
        )
        assert isinstance(agent.system_prompt, list)
        assert len(agent.system_prompt) == 2
        calls = SystemContentBlock.call_args_list
        assert calls[-2].kwargs == {"text": expected_full_prompt}
        assert calls[-1].kwargs == {"cachePoint": {"type": "default"}}

    def test_non_eligible_model_keeps_plain_string_with_rules_appended(
        self, envoy_home, _redirect_worker_sessions, monkeypatch
    ):
        from agents import workers as workers_mod

        (envoy_home / "process.md").write_text(
            "## TestSection\n- Always double-check dates\n"
        )
        monkeypatch.setattr(
            "agents.base.model_for", lambda tier: "meta.llama3-70b-instruct-v1:0"
        )

        mod_name = "fake_cache_ineligible_worker"
        self._cleanup(mod_name)
        _install_fake_worker_module(
            mod_name, "You are a fake worker.", relevant_sections=["TestSection"]
        )

        try:
            agent = workers_mod._import_create(mod_name, "fake_cache_ineligible_test")
        finally:
            self._cleanup(mod_name)

        assert agent.system_prompt == (
            "You are a fake worker."
            "\n\nProcess rules (learned from user corrections):\n"
            "- Always double-check dates"
        )

    def test_no_process_rules_still_wraps_base_prompt(
        self, envoy_home, _redirect_worker_sessions, monkeypatch
    ):
        from agents import workers as workers_mod
        from strands.types.content import SystemContentBlock

        # No process.md written -> _load_process_rules returns "".
        monkeypatch.setattr(
            "agents.base.model_for", lambda tier: "us.anthropic.claude-sonnet-4-6-v1"
        )

        mod_name = "fake_cache_no_rules_worker"
        self._cleanup(mod_name)
        _install_fake_worker_module(mod_name, "You are a fake worker.")
        SystemContentBlock.reset_mock()

        try:
            agent = workers_mod._import_create(mod_name, "fake_cache_no_rules_test")
        finally:
            self._cleanup(mod_name)

        assert isinstance(agent.system_prompt, list)
        calls = SystemContentBlock.call_args_list
        assert calls[-2].kwargs == {"text": "You are a fake worker."}
        assert calls[-1].kwargs == {"cachePoint": {"type": "default"}}


class TestModelRecordsLastModelId:
    def test_model_helper_records_model_id_used(self, monkeypatch):
        from agents import workers as workers_mod

        monkeypatch.setattr("agents.base.model_for", lambda tier: f"model-for-{tier}")
        workers_mod._model("medium")
        assert workers_mod._last_model_id.value == "model-for-medium"
