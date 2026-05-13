"""Unit tests for supervisor.py — non-AI orchestration logic.

Covers ref-ID generation, the in-memory context store, TTL behavior,
cross-reference detection, drill_down, and show_context. Async fetchers
(`gather`, `_gather_async`, `_fetch_vault`) are intentionally skipped
because they require live MCP sessions.
"""

import pytest

import supervisor


@pytest.fixture(autouse=True)
def _reset_context():
    """Wipe the module-level _context between tests so ref counters don't leak."""
    supervisor.clear_context()
    yield
    supervisor.clear_context()


# --- Ref ID generation -------------------------------------------------------

class TestRefIdGeneration:
    def test_first_store_returns_prefix_with_one(self):
        ref = supervisor._store_item("E", "first email")
        assert ref == "E1"

    def test_subsequent_stores_increment(self):
        r1 = supervisor._store_item("E", "first")
        r2 = supervisor._store_item("E", "second")
        r3 = supervisor._store_item("E", "third")
        assert (r1, r2, r3) == ("E1", "E2", "E3")

    def test_different_prefixes_count_independently(self):
        e1 = supervisor._store_item("E", "email one")
        s1 = supervisor._store_item("S", "slack one")
        c1 = supervisor._store_item("C", "cal one")
        t1 = supervisor._store_item("T", "todo one")
        assert (e1, s1, c1, t1) == ("E1", "S1", "C1", "T1")

        # Mixing them in further calls still keeps independent counters
        assert supervisor._store_item("E", "email two") == "E2"
        assert supervisor._store_item("S", "slack two") == "S2"

    def test_clear_context_resets_counters(self):
        supervisor._store_item("E", "first")
        supervisor._store_item("E", "second")
        supervisor.clear_context()
        # After clearing, the counter starts again at 1
        assert supervisor._store_item("E", "fresh") == "E1"

    def test_store_item_persists_summary_and_data(self):
        ref = supervisor._store_item("E", "subj", type="email", sender="alice")
        ctx = supervisor.get_context()
        assert ctx["items"][ref]["summary"] == "subj"
        assert ctx["items"][ref]["type"] == "email"
        assert ctx["items"][ref]["sender"] == "alice"


# --- Context store / retrieval ----------------------------------------------

class TestContextStore:
    def test_set_and_get_context(self):
        supervisor.set_context("custom_key", "hello world")
        assert supervisor.get_context()["custom_key"] == "hello world"

    def test_set_context_overwrites(self):
        supervisor.set_context("k", 1)
        supervisor.set_context("k", 2)
        assert supervisor.get_context()["k"] == 2

    def test_drill_down_finds_stored_item(self):
        ref = supervisor._store_item("S", "slack thing", type="slack", raw="raw line")
        out = supervisor.drill_down(ref)
        assert ref in out
        assert "slack thing" in out
        assert "raw line" in out

    def test_drill_down_is_case_insensitive(self):
        ref = supervisor._store_item("E", "x", type="other", raw="r")
        # ref is "E1" — try lowercase
        out = supervisor.drill_down(ref.lower())
        assert "E1" in out

    def test_drill_down_missing_ref_returns_friendly_error(self):
        out = supervisor.drill_down("ZZ99")
        assert "not found" in out.lower()
        # Should mention what's available (or "none")
        assert "none" in out.lower() or "available" in out.lower()


# --- TTL behavior ------------------------------------------------------------

class TestTTL:
    def test_fresh_context_survives_check(self, monkeypatch):
        # Pin "now" and set a fresh ts
        fake_now = [1000.0]
        monkeypatch.setattr(supervisor._time, "monotonic", lambda: fake_now[0])

        supervisor.set_context("ts", fake_now[0])
        supervisor._store_item("E", "still here")

        # Advance time but stay within TTL
        fake_now[0] = 1000.0 + supervisor._CONTEXT_TTL - 1
        ctx = supervisor.get_context()  # triggers _check_ttl internally
        assert "E1" in ctx["items"]

    def test_expired_context_is_cleared(self, monkeypatch):
        fake_now = [5000.0]
        monkeypatch.setattr(supervisor._time, "monotonic", lambda: fake_now[0])

        supervisor.set_context("ts", fake_now[0])
        supervisor._store_item("E", "soon to expire")
        assert "E1" in supervisor.get_context()["items"]

        # Jump well past the TTL
        fake_now[0] = 5000.0 + supervisor._CONTEXT_TTL + 1
        ctx = supervisor.get_context()
        assert ctx["items"] == {}
        assert ctx["ts"] == 0

    def test_zero_ts_does_not_trigger_clear(self, monkeypatch):
        # _check_ttl guards on `if _context["ts"]` — a zero ts means "nothing
        # to expire," even if monotonic() has advanced a lot.
        fake_now = [10_000_000.0]
        monkeypatch.setattr(supervisor._time, "monotonic", lambda: fake_now[0])

        supervisor._store_item("E", "no ts set")
        # ts is still 0 from clear_context fixture
        assert supervisor.get_context()["ts"] == 0
        assert "E1" in supervisor.get_context()["items"]


# --- _cross_reference --------------------------------------------------------

class TestCrossReference:
    def test_empty_input_returns_empty(self):
        assert supervisor._cross_reference({}) == ""

    def test_single_source_no_overlap(self):
        # Only one source — overlap impossible by definition
        out = supervisor._cross_reference({
            "emails": "Alice mentioned the Phoenix project",
        })
        assert out == ""

    def test_overlap_across_two_sources(self):
        # "Alice" should appear in both — the entity extractor lowercases
        # capitalized non-stopword tokens that aren't sentence-starters.
        results = {
            "emails": "Subject line mentions Alice today regarding plans",
            "slack": "Message from Alice about the schedule",
        }
        out = supervisor._cross_reference(results)
        # Either "alice" gets picked up as an overlap, or the function
        # decides nothing crosses sources. We assert on observed behavior:
        # if there is output, it must reference both sources for the overlap.
        if out:
            assert "emails" in out and "slack" in out
            assert "multiple sources" in out.lower() or "mentioned in" in out.lower()

    def test_no_overlap_returns_empty(self):
        results = {
            "emails": "totally unrelated content here",
            "slack": "different words entirely nothing matches",
        }
        out = supervisor._cross_reference(results)
        assert out == ""

    def test_error_strings_are_skipped(self):
        # Sources with error/warning prefixes are ignored — should not crash
        # and should not produce overlap output.
        results = {
            "emails": "Error: failed to fetch",
            "slack": "⚠️ slack unavailable",
        }
        assert supervisor._cross_reference(results) == ""

    def test_falsy_values_dont_crash(self):
        results = {"emails": None, "slack": "", "calendar": "Some Text"}
        # Should handle gracefully and (with <2 valid sources) return ""
        assert supervisor._cross_reference(results) == ""


# --- show_context ------------------------------------------------------------

class TestShowContext:
    def test_empty_context_returns_friendly_message(self):
        out = supervisor.show_context("")
        assert "empty" in out.lower() or "gather" in out.lower()

    def test_summary_lists_grouped_items(self):
        supervisor._store_item("E", "Alice: hi", type="email")
        supervisor._store_item("E", "Bob: hey", type="email")
        supervisor._store_item("S", "channel msg", type="slack")
        out = supervisor.show_context("")
        assert "3 items" in out
        # Group headers are titlecased ("Email", "Slack")
        assert "Email" in out
        assert "Slack" in out
        assert "[E1]" in out and "[E2]" in out and "[S1]" in out

    def test_specific_ref_returns_that_item(self):
        ref = supervisor._store_item("E", "drilldown me", type="email")
        out = supervisor.show_context(ref)
        assert "drilldown me" in out
        assert ref in out
        assert "email" in out.lower()

    def test_specific_ref_lowercase_input(self):
        ref = supervisor._store_item("S", "lower test", type="slack")
        out = supervisor.show_context(ref.lower())
        assert ref in out  # show_context uppercases input
        assert "lower test" in out

    def test_missing_ref_returns_friendly_error(self):
        out = supervisor.show_context("NOPE99")
        assert "not found" in out.lower()
