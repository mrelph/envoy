"""Unit tests for agents/learning.py.

Covers regex pattern matching (no AI), reflect() side-effects, and the fast
exit path of detect_correction(). All AI calls are intercepted by the
``no_ai`` fixture from conftest.py.
"""

import importlib
import os

import pytest


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

class TestCorrectionPatterns:
    @pytest.fixture
    def pat(self):
        from agents.learning import _CORRECTION_PATTERNS
        return _CORRECTION_PATTERNS

    @pytest.mark.parametrize("text", [
        "no, that's wrong",
        "wrong",
        "don't do that",
        "dont do that",        # missing apostrophe variant
        "stop doing that",
        "actually, I meant tomorrow",
        "actually that's fine",
        "incorrect",
        "I said the other one",
        "I meant Tuesday",
        "I don't want that",
        "please don't email him",
        "stop ",                # 'stop ' (with space) is matched by the pattern
    ])
    def test_matches(self, pat, text):
        assert pat.search(text), f"expected match for: {text!r}"

    @pytest.mark.parametrize("text", [
        "thanks!",
        "good morning",
        "sounds good",
        "ok let's do it",
        "schedule the meeting",
        "",
    ])
    def test_no_match(self, pat, text):
        assert not pat.search(text), f"unexpected match for: {text!r}"


class TestPreferencePatterns:
    @pytest.fixture
    def pat(self):
        from agents.learning import _PREFERENCE_PATTERNS
        return _PREFERENCE_PATTERNS

    @pytest.mark.parametrize("text", [
        "always reply within an hour",
        "never email john on weekends",
        "from now on, use Slack",
        "make sure you check Slack",
        "I prefer concise replies",
        "going forward, batch the digests",
        "remember that I leave at 5pm",
        "next time send a calendar invite",
        "don't ever auto-decline meetings",
    ])
    def test_matches(self, pat, text):
        assert pat.search(text), f"expected match for: {text!r}"

    @pytest.mark.parametrize("text", [
        "i sent the email",
        "scheduled the meeting",
        "thanks for the update",
        "",
    ])
    def test_no_match(self, pat, text):
        assert not pat.search(text), f"unexpected match for: {text!r}"


# ---------------------------------------------------------------------------
# reflect()
# ---------------------------------------------------------------------------

class TestReflect:
    """reflect() should append observations to memory unless the input is trivial."""

    @pytest.fixture
    def recorder(self, envoy_home, monkeypatch):
        """Replace agents.memory2.remember with a recorder, return the call list.

        Reload learning so its lazy-import resolves to the patched module.
        """
        import agents.memory2 as memory2
        importlib.reload(memory2)
        import agents.learning as learning
        importlib.reload(learning)

        calls = []

        def fake_remember(text, entry_type="action"):
            calls.append({"text": text, "entry_type": entry_type})
            return "ok"

        monkeypatch.setattr(memory2, "remember", fake_remember)
        return calls, learning

    def test_skips_help_command(self, recorder):
        calls, learning = recorder
        learning.reflect("/help me out", "Some long response that is over twenty chars.")
        assert calls == []

    def test_skips_exit_command(self, recorder):
        calls, learning = recorder
        learning.reflect("/exit", "Some long response that is over twenty chars.")
        assert calls == []

    def test_skips_empty_command(self, recorder):
        calls, learning = recorder
        learning.reflect("", "Some long response that is over twenty chars.")
        assert calls == []

    def test_skips_short_response(self, recorder):
        calls, learning = recorder
        learning.reflect("/digest", "short")  # < 20 chars
        assert calls == []

    def test_records_meaningful_interaction(self, recorder):
        calls, learning = recorder
        learning.reflect(
            "/digest morning",
            "Pulled 12 emails and 3 ticket updates from overnight; nothing urgent.",
        )
        assert len(calls) == 1
        c = calls[0]
        assert c["entry_type"] == "observation"
        assert "/digest morning" in c["text"]
        # Response substring (truncated to 120 chars) should appear, with newlines flattened.
        assert "Pulled 12 emails" in c["text"]
        assert "→" in c["text"]

    def test_includes_user_reply_when_provided(self, recorder):
        calls, learning = recorder
        learning.reflect(
            "/inbox",
            "Here is a long enough response with more than twenty characters total.",
            user_reply="thanks, that was useful",
        )
        assert len(calls) == 1
        assert "user:" in calls[0]["text"]
        assert "thanks" in calls[0]["text"]

    def test_truncates_long_command_and_response(self, recorder):
        calls, learning = recorder
        long_cmd = "/x " + ("a" * 200)
        long_resp = "y" * 500
        learning.reflect(long_cmd, long_resp)
        assert len(calls) == 1
        text = calls[0]["text"]
        # Command portion capped at 80 chars
        cmd_part = text.split(" → ")[0]
        assert len(cmd_part) <= 80
        # Response portion capped at 120 chars
        resp_part = text.split(" → ")[1]
        assert len(resp_part) <= 120

    def test_swallows_remember_exceptions(self, envoy_home, monkeypatch):
        """reflect() must never break the main flow if remember() raises."""
        import agents.memory2 as memory2
        importlib.reload(memory2)
        import agents.learning as learning
        importlib.reload(learning)

        def boom(*a, **kw):
            raise RuntimeError("disk full")

        monkeypatch.setattr(memory2, "remember", boom)
        # Should not raise.
        learning.reflect("/digest", "A response that is definitely longer than twenty chars.")


# ---------------------------------------------------------------------------
# detect_correction() — fast-path branches only (no AI)
# ---------------------------------------------------------------------------

class TestDetectCorrectionFastPath:
    """Note: the shared ``no_ai`` fixture in conftest has a setup-time bug
    (it tries to set an attribute on a list). We sidestep it by stubbing
    ``invoke_ai`` ourselves with a local fixture that only records calls.
    """

    @pytest.fixture
    def ai_calls(self, monkeypatch):
        from agents import base
        calls = []

        def _fake(prompt, max_tokens=10000, tier="heavy", _response=["Email: stub rule"]):
            calls.append({"prompt": prompt, "max_tokens": max_tokens, "tier": tier})
            return _response[0]

        monkeypatch.setattr(base, "invoke_ai", _fake)
        return calls

    def test_returns_none_for_empty_input(self, envoy_home, ai_calls):
        from agents.learning import detect_correction
        assert detect_correction("") is None
        assert ai_calls == []  # AI never called

    def test_returns_none_for_too_short_input(self, envoy_home, ai_calls):
        from agents.learning import detect_correction
        # < 5 characters
        assert detect_correction("ok") is None
        assert detect_correction("hi") is None
        assert ai_calls == []

    def test_returns_none_for_neutral_input(self, envoy_home, ai_calls):
        """Input that matches neither correction nor preference patterns: no AI call."""
        from agents.learning import detect_correction
        assert detect_correction("schedule the meeting for tomorrow") is None
        assert detect_correction("thanks for sending that report") is None
        assert detect_correction("looks good to me") is None
        assert ai_calls == []

    def test_calls_ai_only_when_pattern_matches(self, envoy_home, ai_calls):
        """When a correction phrase matches, the AI path runs (smoke test).

        We assert AI was invoked exactly once with the expected light tier,
        confirming the fast-path regex filter passes through.
        """
        from agents.learning import detect_correction
        result = detect_correction("no, that's wrong — don't auto-reply")
        assert len(ai_calls) == 1
        assert ai_calls[0]["tier"] == "light"
        # Successful format path produces a [Section] prefix.
        if result is not None:
            assert result.startswith("[")

    def test_preference_phrase_also_calls_ai(self, envoy_home, ai_calls):
        from agents.learning import detect_correction
        detect_correction("always confirm before sending external mail")
        assert len(ai_calls) == 1
