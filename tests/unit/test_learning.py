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
        # Directive-sounding words appearing mid-sentence must NOT trigger a
        # permanent rule — this is the H7 bug: an unrelated instruction that
        # merely mentions "always" should not become a standing process rule.
        "Email Sarah that I'll always be available Fridays",
        "tell him we never do lunch on Tuesdays",
        "ask her if she still prefers window seats",
        "he said to remember that milk is in the fridge",
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

        def fake_remember(text, entry_type="action", **kwargs):
            calls.append({"text": text, "entry_type": entry_type, **kwargs})
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
        assert "—" in c["text"]

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
        # Command portion (after the [domain] tag) capped at 80 chars
        cmd_part = text.split(" — ")[0]
        action = cmd_part.split("] ", 1)[1]
        assert len(action) <= 80
        # Response portion capped at 120 chars
        resp_part = text.split(" — ")[1]
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


# ---------------------------------------------------------------------------
# Pending-confirmation queue: apply_learning/apply_correction now queue rather
# than write, plus list_pending/confirm_pending/reject_pending/pending_summary.
# ---------------------------------------------------------------------------

class TestPendingQueue:
    @pytest.fixture
    def learning(self, envoy_home):
        import agents.learning as learning
        importlib.reload(learning)
        return learning

    def test_apply_learning_queues_not_writes(self, learning):
        msg = learning.apply_learning("check calendar before booking", "Calendar")
        assert "Queued" in msg
        assert not os.path.exists(learning._PROCESS_FILE)
        pending = learning.list_pending()
        assert len(pending) == 1
        assert pending[0]["rule"] == "check calendar before booking"
        assert pending[0]["section"] == "Calendar"
        assert pending[0]["source"] == "preference"
        assert "detected_at" in pending[0]

    def test_apply_correction_queues_with_correction_source(self, learning):
        learning.apply_correction("[Email] Always CC the EA on customer replies")
        pending = learning.list_pending()
        assert len(pending) == 1
        assert pending[0]["source"] == "correction"
        assert pending[0]["section"] == "Email"
        assert not os.path.exists(learning._PROCESS_FILE)

    def test_confirm_pending_writes_to_process_md_and_dequeues(self, learning):
        learning.apply_learning("batch digests every morning", "General")
        msg = learning.confirm_pending(0)
        assert "Learned" in msg
        assert os.path.exists(learning._PROCESS_FILE)
        content = open(learning._PROCESS_FILE).read()
        assert "batch digests every morning" in content
        assert learning.list_pending() == []

    def test_confirm_pending_bad_index(self, learning):
        assert "No pending rule" in learning.confirm_pending(0)
        assert "No pending rule" in learning.confirm_pending(-1)

    def test_reject_pending_discards_without_writing(self, learning):
        learning.apply_learning("never book meetings after 5pm", "Calendar")
        msg = learning.reject_pending(0)
        assert "Rejected" in msg
        assert learning.list_pending() == []
        assert not os.path.exists(learning._PROCESS_FILE)

    def test_reject_pending_bad_index(self, learning):
        assert "No pending rule" in learning.reject_pending(0)

    def test_pending_summary_none_when_empty(self, learning):
        assert learning.pending_summary() is None

    def test_pending_summary_reports_count_and_hint(self, learning):
        learning.apply_learning("always confirm before sending external mail", "Email")
        learning.apply_learning("never schedule over lunch", "Calendar")
        summary = learning.pending_summary()
        assert summary is not None
        assert "2 learned rules pending" in summary
        assert "/learn confirm 1" in summary
        assert "/learn reject 1" in summary

    def test_pending_summary_singular(self, learning):
        learning.apply_learning("always confirm before sending external mail", "Email")
        summary = learning.pending_summary()
        assert "1 learned rule pending" in summary


class TestPendingQueueDedup:
    @pytest.fixture
    def learning(self, envoy_home):
        import agents.learning as learning
        importlib.reload(learning)
        return learning

    def test_skips_near_duplicate_already_pending(self, learning):
        learning.apply_learning(
            "always confirm with the sender before forwarding any external customer email thread",
            "Email",
        )
        msg = learning.apply_learning(
            "always confirm with the sender before forwarding an external customer email thread",
            "Email",
        )
        assert "Skipped" in msg
        assert len(learning.list_pending()) == 1

    def test_skips_near_duplicate_already_in_process_md(self, learning):
        learning.apply_learning("always cc the EA on customer replies", "Email")
        learning.confirm_pending(0)
        msg = learning.apply_learning("always CC the EA on customer replies", "Email")
        assert "Skipped" in msg
        assert learning.list_pending() == []

    def test_dissimilar_rules_are_not_deduped(self, learning):
        learning.apply_learning("always confirm before sending external mail", "Email")
        learning.apply_learning("decline meetings with no agenda", "Calendar")
        assert len(learning.list_pending()) == 2

    def test_has_similar_helper_thresholds(self, learning):
        from agents.learning import _has_similar
        existing = ["always confirm with the sender before forwarding any external customer email thread"]
        assert _has_similar(
            "always confirm with the sender before forwarding an external customer email thread",
            existing,
        )
        assert not _has_similar("decline meetings with no agenda", existing)


class TestPendingQueueCap:
    @pytest.fixture
    def learning(self, envoy_home):
        import agents.learning as learning
        importlib.reload(learning)
        return learning

    def test_queue_caps_at_ten_dropping_oldest(self, learning):
        for i in range(12):
            learning.apply_learning(f"distinct rule number {i} about topic {i}", "General")
        pending = learning.list_pending()
        assert len(pending) == 10
        rules = [p["rule"] for p in pending]
        assert "distinct rule number 0 about topic 0" not in rules
        assert "distinct rule number 1 about topic 1" not in rules
        assert "distinct rule number 11 about topic 11" in rules

    def test_process_section_cap_blocks_confirm(self, learning):
        # Fill process.md's General section to the cap directly.
        os.makedirs(os.path.dirname(learning._PROCESS_FILE), exist_ok=True)
        lines = "\n".join(f"- existing rule {i} zzz{i}" for i in range(30))
        with open(learning._PROCESS_FILE, "w") as f:
            f.write(f"# Process Memory\n\n## General\n{lines}\n")
        learning.apply_learning("brand new rule about something else entirely", "General")
        msg = learning.confirm_pending(0)
        assert "already has 30 rules" in msg
        # Rule should remain queued, not written.
        assert len(learning.list_pending()) == 1
        content = open(learning._PROCESS_FILE).read()
        assert "brand new rule about something else entirely" not in content
