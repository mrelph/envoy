"""Unit tests for agents/heartbeat.py — dedup, alert cap, per-item truncation.

Covers the fixes for the "Heartbeat dedup is model-based and its only hard
cap is dead code" review item:
  1. Stable-ID / fingerprint dedup (_extract_stable_id, _fingerprint,
     _alert_key, _dedup_and_cap)
  2. Enforcement of _MAX_ALERTS_PER_RUN (_dedup_and_cap's truncation branch)
  3. Per-item truncation in _gather_context (_truncate_by_item)

AI calls and MCP I/O are intentionally not exercised in most of these tests
(they operate on the pure dedup/truncation helpers), except for one
end-to-end test of _run_heartbeat_async which stubs invoke_ai, _gather_context,
memory.recall and slack_agent.send_dm directly rather than using the shared
`no_ai` fixture (which only patches a fixed module list that doesn't include
agents.heartbeat's local `invoke_ai` binding).
"""

import asyncio
import importlib
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def hb():
    """Import agents.heartbeat fresh. No envoy_home needed — these tests
    only touch the pure helper functions, never _load_state/_save_state."""
    import agents.heartbeat as heartbeat
    return heartbeat


# ---------------------------------------------------------------------------
# Stable-ID extraction
# ---------------------------------------------------------------------------

class TestExtractStableId:
    def test_finds_id_tag(self, hb):
        line = "1. 🔴 Customer escalation needs a reply [id:conv-abc123]"
        assert hb._extract_stable_id(line) == "conv-abc123"

    def test_returns_none_when_absent(self, hb):
        line = "1. 🔴 Customer escalation needs a reply"
        assert hb._extract_stable_id(line) is None

    def test_ignores_empty_tag(self, hb):
        line = "1. 🔴 Something happened [id:]"
        assert hb._extract_stable_id(line) is None


# ---------------------------------------------------------------------------
# Fingerprint fallback
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_reworded_timestamp_and_count_produce_same_fingerprint(self, hb):
        line1 = "1. 🟡 3 emails from Alice need a reply by 5pm today"
        line2 = "2. 🟡 5 emails from alice need a reply by 6:30pm today"
        assert hb._fingerprint(line1) == hb._fingerprint(line2)

    def test_different_content_produces_different_fingerprint(self, hb):
        line1 = "1. 🟡 emails from alice need a reply"
        line2 = "1. 🔴 production database is down"
        assert hb._fingerprint(line1) != hb._fingerprint(line2)

    def test_alert_key_prefers_stable_id_over_fingerprint(self, hb):
        line = "1. 🔴 Customer escalation [id:conv-1]"
        kind, key = hb._alert_key(line)
        assert kind == "id"
        assert key == "conv-1"

    def test_alert_key_falls_back_to_fingerprint(self, hb):
        line = "1. 🔴 Customer escalation, no id here"
        kind, key = hb._alert_key(line)
        assert kind == "fingerprint"
        assert key == hb._fingerprint(line)


# ---------------------------------------------------------------------------
# _dedup_and_cap — dedup behavior
# ---------------------------------------------------------------------------

class TestDedupAndCap:
    def test_new_alert_passes_through(self, hb):
        state = {}
        kept, deduped, truncated = hb._dedup_and_cap(
            ["1. 🔴 production database is down"], state
        )
        assert kept == ["1. 🔴 production database is down"]
        assert deduped == 0
        assert truncated == 0

    def test_rephrased_alert_suppressed_via_fingerprint(self, hb):
        state = {}
        hb._dedup_and_cap(["1. 🟡 3 emails from Alice need a reply by 5pm today"], state)
        kept, deduped, truncated = hb._dedup_and_cap(
            ["1. 🟡 5 emails from alice need a reply by 6:30pm today"], state
        )
        assert kept == []
        assert deduped == 1

    def test_rephrased_alert_suppressed_via_stable_id(self, hb):
        state = {}
        hb._dedup_and_cap(
            ["1. 🔴 Customer escalation needs reply [id:conv-123]"], state
        )
        kept, deduped, _ = hb._dedup_and_cap(
            ["1. 🔴 Urgent: customer escalation still needs a reply today [id:conv-123]"],
            state,
        )
        assert kept == []
        assert deduped == 1

    def test_genuinely_new_alert_not_deduped_against_unrelated_seen(self, hb):
        state = {}
        hb._dedup_and_cap(["1. 🟡 emails from alice need a reply"], state)
        kept, deduped, _ = hb._dedup_and_cap(
            ["1. 🔴 production database is down"], state
        )
        assert deduped == 0
        assert len(kept) == 1

    def test_mixed_batch_keeps_new_and_drops_seen(self, hb):
        state = {}
        hb._dedup_and_cap(["1. 🔴 production database is down"], state)
        kept, deduped, _ = hb._dedup_and_cap(
            [
                "2. 🔴 production database is down",  # only the numbering differs
                "2. 🟡 new ticket needs triage",
            ],
            state,
        )
        assert deduped == 1
        assert kept == ["2. 🟡 new ticket needs triage"]


# ---------------------------------------------------------------------------
# _dedup_and_cap — _MAX_ALERTS_PER_RUN enforcement
# ---------------------------------------------------------------------------

class TestCapEnforcement:
    def test_twelve_alerts_capped_to_ten_keeping_most_severe(self, hb):
        assert hb._MAX_ALERTS_PER_RUN == 10
        words = ["alpha", "beta", "gamma", "delta"]
        lines = (
            [f"🔴 red alert {w}" for w in words]
            + [f"🟡 yellow alert {w}" for w in words]
            + [f"🔵 blue alert {w}" for w in words]
        )
        assert len(lines) == 12
        state = {}
        kept, deduped, truncated = hb._dedup_and_cap(lines, state)

        assert deduped == 0
        assert truncated == 2
        assert len(kept) == 10
        kept_text = "\n".join(kept)
        # All red and yellow (the more severe tiers) survive; only the
        # lowest-severity (blue) tier absorbs the truncation.
        assert kept_text.count("🔴") == 4
        assert kept_text.count("🟡") == 4
        assert kept_text.count("🔵") == 2

    def test_no_truncation_when_at_or_under_cap(self, hb):
        state = {}
        lines = [f"🔵 informational item {i}" for i in range(10)]
        kept, deduped, truncated = hb._dedup_and_cap(lines, state)
        assert truncated == 0
        assert len(kept) == 10

    def test_cap_applies_after_dedup_not_before(self, hb):
        """Cap should only count fresh (non-duplicate) alerts."""
        state = {}
        # Seed state with 5 already-seen alerts.
        seeded = [f"🔵 seen item {w}" for w in ["a", "b", "c", "d", "e"]]
        hb._dedup_and_cap(seeded, state)

        # Next run repeats those 5 (now duplicates) plus 8 new ones = 13 raw,
        # but only 8 are fresh — under the cap, so nothing should truncate.
        fresh_new = [f"🔴 fresh item {w}" for w in "12345678"]
        kept, deduped, truncated = hb._dedup_and_cap(seeded + fresh_new, state)
        assert deduped == 5
        assert truncated == 0
        assert len(kept) == 8


# ---------------------------------------------------------------------------
# _dedup_and_cap — state window bounding
# ---------------------------------------------------------------------------

class TestStateWindowBounding:
    def test_entry_count_bounded_to_window(self, hb):
        seeded = [
            {
                "kind": "fingerprint",
                "key": f"k{i}",
                "ts": datetime.now().isoformat(),
                "summary": f"old {i}",
            }
            for i in range(hb._DEDUP_WINDOW_ENTRIES + 50)
        ]
        state = {"seen_keys": seeded}
        hb._dedup_and_cap(["1. 🔵 brand new distinct alert"], state)
        assert len(state["seen_keys"]) <= hb._DEDUP_WINDOW_ENTRIES

    def test_old_entries_pruned_by_age(self, hb):
        old_ts = (datetime.now() - timedelta(days=hb._DEDUP_WINDOW_DAYS + 1)).isoformat()
        state = {
            "seen_keys": [
                {"kind": "fingerprint", "key": "stale-key", "ts": old_ts, "summary": "old"}
            ]
        }
        hb._dedup_and_cap(["1. 🔵 brand new distinct alert"], state)
        keys = [e["key"] for e in state["seen_keys"]]
        assert "stale-key" not in keys

    def test_recent_entries_survive_pruning(self, hb):
        recent_ts = (datetime.now() - timedelta(days=1)).isoformat()
        state = {
            "seen_keys": [
                {"kind": "fingerprint", "key": "recent-key", "ts": recent_ts, "summary": "recent"}
            ]
        }
        hb._dedup_and_cap(["1. 🔵 brand new distinct alert"], state)
        keys = [e["key"] for e in state["seen_keys"]]
        assert "recent-key" in keys


# ---------------------------------------------------------------------------
# _truncate_by_item — per-item truncation in _gather_context
# ---------------------------------------------------------------------------

class TestTruncateByItem:
    def test_text_under_budget_is_unchanged(self, hb):
        text = "short text\nwith a couple lines"
        assert hb._truncate_by_item(text, budget=2000) == text

    def test_keeps_only_whole_lines_up_to_budget(self, hb):
        lines = [f"item-{i:03d} " + ("x" * 40) for i in range(30)]
        text = "\n".join(lines)
        truncated = hb._truncate_by_item(text, budget=500)
        assert len(truncated) <= 500
        # Every kept line must be byte-identical to a full original line —
        # never a partial slice through the middle of one.
        for line in truncated.splitlines():
            assert line in lines
        # And it must actually have dropped something (budget < full text).
        assert len(truncated.splitlines()) < len(lines)

    def test_single_line_over_budget_is_hard_cut(self, hb):
        text = "x" * 5000
        truncated = hb._truncate_by_item(text, budget=100)
        assert len(truncated) == 100

    def test_drops_trailing_item_that_would_exceed_budget(self, hb):
        # Two 100-char lines fit in budget 250 (with joining newline); a
        # third would push total over budget and must be dropped whole,
        # not sliced.
        lines = ["a" * 100, "b" * 100, "c" * 100]
        text = "\n".join(lines)
        truncated = hb._truncate_by_item(text, budget=250)
        kept = truncated.splitlines()
        assert kept == ["a" * 100, "b" * 100]


# ---------------------------------------------------------------------------
# End-to-end: _run_heartbeat_async persists dedup state across runs
# ---------------------------------------------------------------------------

class TestHeartbeatRunDedupEndToEnd:
    @pytest.fixture
    def heartbeat(self, envoy_home):
        import agents.heartbeat as heartbeat
        importlib.reload(heartbeat)
        return heartbeat

    def _wire_common_stubs(self, heartbeat, monkeypatch, responses):
        call_count = {"n": 0}

        def fake_invoke(prompt, max_tokens=800, tier="medium"):
            idx = min(call_count["n"], len(responses) - 1)
            call_count["n"] += 1
            return responses[idx]

        monkeypatch.setattr(heartbeat, "invoke_ai", fake_invoke)

        async def fake_gather(days=1):
            return "### inbox\nsome data"

        monkeypatch.setattr(heartbeat, "_gather_context", fake_gather)
        monkeypatch.setattr(heartbeat.memory, "recall", lambda *a, **k: "")

        sent = []

        async def fake_send_dm(user, message):
            sent.append(message)
            return "ok"

        monkeypatch.setattr(heartbeat.slack_agent, "send_dm", fake_send_dm)

        async def fake_weekly(notify="none"):
            return None

        monkeypatch.setattr(heartbeat, "_run_weekly_learning", fake_weekly)
        return sent

    def test_rephrased_alert_not_resent_on_next_run(self, heartbeat, monkeypatch):
        # Same underlying alert, only the digits/timestamp differ — exactly
        # what the normalized-text fingerprint (lowercase, strip digits) is
        # meant to catch. Word-order/synonym paraphrasing is out of scope
        # for the fingerprint fallback; that's what the stable-ID path (or
        # the model actually reusing an [id:...] tag) is for.
        responses = [
            "1. 🔴 Server outage detected at 10:00am",
            "1. 🔴 Server outage detected at 10:15am",
        ]
        sent = self._wire_common_stubs(heartbeat, monkeypatch, responses)

        result1 = asyncio.run(heartbeat._run_heartbeat_async(quiet=True, notify="slack"))
        assert "Server outage" in result1
        assert len(sent) == 1

        result2 = asyncio.run(heartbeat._run_heartbeat_async(quiet=True, notify="slack"))
        assert result2 == "All clear."
        assert len(sent) == 1  # no duplicate Slack DM

    def test_genuinely_new_alert_is_sent_on_next_run(self, heartbeat, monkeypatch):
        responses = [
            "1. 🔴 Server outage in us-east-1 detected at 10:00am",
            "1. 🟡 Unrelated ticket TICKET-42 needs triage",
        ]
        sent = self._wire_common_stubs(heartbeat, monkeypatch, responses)

        asyncio.run(heartbeat._run_heartbeat_async(quiet=True, notify="slack"))
        result2 = asyncio.run(heartbeat._run_heartbeat_async(quiet=True, notify="slack"))

        assert "TICKET-42" in result2
        assert len(sent) == 2
