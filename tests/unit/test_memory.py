"""Unit tests for agents/memory2.py.

Sandboxed via the ``envoy_home`` fixture so writes never touch the real
``~/.envoy`` directory. The memory2 module computes its storage paths from
``os.path.expanduser("~/...")`` at import time, so we have to recompute /
patch those module-level constants whenever the fixture moves $HOME.
"""

import importlib
import json
import os

import pytest


# --- Helpers ---------------------------------------------------------------

def _reload_memory(envoy_home):
    """Reload agents.memory2 so its module-level paths point at the sandbox.

    The fixture has already redirected $HOME, but memory2 captured the old
    value at import time during conftest's strands stubbing. Reload + patch.
    """
    import agents.memory2 as memory2
    importlib.reload(memory2)
    # Belt-and-suspenders: force paths to the sandbox even if anything cached.
    memory2.MEMORY_DIR = str(envoy_home / "memory")
    memory2.ENTRIES_FILE = os.path.join(memory2.MEMORY_DIR, "entries.jsonl")
    memory2.ENTITIES_FILE = os.path.join(memory2.MEMORY_DIR, "entities.json")
    memory2.SUMMARY_FILE = os.path.join(memory2.MEMORY_DIR, "summary.json")
    return memory2


# --- remember() -------------------------------------------------------------

class TestRemember:
    def test_single_entry_round_trips(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        result = memory2.remember("called Alice about Q3 plan", entry_type="action")
        assert "Remembered:" in result
        assert os.path.exists(memory2.ENTRIES_FILE)

        entries = memory2._load_entries(days=30)
        assert len(entries) == 1
        e = entries[0]
        # Schema check
        assert e["text"] == "called Alice about Q3 plan"
        assert e["type"] == "action"
        assert "ts" in e and "id" in e and "entities" in e
        # Timestamp is ISO-formatted
        from datetime import datetime
        datetime.fromisoformat(e["ts"])  # raises if malformed

    def test_two_entries_stored_separately(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        memory2.remember("first thing", entry_type="action")
        memory2.remember("second thing", entry_type="decision")

        entries = memory2._load_entries(days=30)
        assert len(entries) == 2
        texts = {e["text"] for e in entries}
        assert texts == {"first thing", "second thing"}
        types = {e["type"] for e in entries}
        assert types == {"action", "decision"}

    def test_default_entry_type_is_action(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        memory2.remember("a quick note")
        entries = memory2._load_entries(days=30)
        assert entries[0]["type"] == "action"

    def test_long_text_is_truncated(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        long_text = "x" * 1000
        memory2.remember(long_text)
        entries = memory2._load_entries(days=30)
        assert len(entries[0]["text"]) == memory2.MAX_ENTRY_LEN


# --- recall() ---------------------------------------------------------------

class TestRecall:
    def test_empty_memory_returns_empty_string(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        assert memory2.recall() == ""

    def test_recall_returns_entry_text(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        memory2.remember("scheduled lunch with Bob")
        memory2.remember("filed expense report")

        out = memory2.recall()
        assert out  # non-empty
        assert "scheduled lunch with Bob" in out
        assert "filed expense report" in out
        # Should be tagged as "Today" since just written
        assert "Today" in out

    def test_recall_respects_limit(self, envoy_home):
        """recall(limit=N) caps the entries section to the last N entries."""
        memory2 = _reload_memory(envoy_home)
        for i in range(30):
            memory2.remember(f"entry-number-{i:02d}")

        out = memory2.recall(limit=5)
        # The 5 most-recent entries are 25..29 — they must appear.
        assert "entry-number-29" in out
        assert "entry-number-25" in out
        # Earlier entries (those outside the last 5) must NOT appear.
        assert "entry-number-00" not in out
        assert "entry-number-10" not in out

    def test_recall_by_query_matches_text(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        memory2.remember("Project Atlas kickoff went well")
        memory2.remember("unrelated note about lunch")

        out = memory2.recall(query="atlas")
        assert "atlas" in out.lower()
        assert "Atlas kickoff" in out
        # Unrelated entry should not score in
        assert "unrelated note about lunch" not in out

    def test_recall_by_query_with_no_match_returns_friendly_message(
        self, envoy_home, monkeypatch
    ):
        memory2 = _reload_memory(envoy_home)
        memory2.remember("a single note about cats")

        # Disable vault fallback so the no-match path is deterministic
        monkeypatch.setattr(memory2, "_search_vault", lambda q: "")
        out = memory2.recall(query="zebra")
        assert "No memory entries found" in out


# --- entity extraction ------------------------------------------------------

class TestEntityExtraction:
    def test_extracts_amazon_alias(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        ents = memory2._extract_entities("ping alice@amazon.com about it")
        assert "alice" in ents

    def test_extracts_at_mention(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        ents = memory2._extract_entities("talked to @bob today")
        assert "bob" in ents

    def test_extracts_project_id(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        ents = memory2._extract_entities("filed SIM-12345 for the team")
        assert "sim-12345" in ents

    def test_extracts_kp_project_id(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        ents = memory2._extract_entities("KP-99 needs approval")
        assert "kp-99" in ents

    def test_skips_stopwords(self, envoy_home):
        """Common verbs/nouns shouldn't be treated as entities even if capitalized."""
        memory2 = _reload_memory(envoy_home)
        # First word is dropped (sentence-start heuristic), so put stopwords later.
        ents = memory2._extract_entities("Note: please Reply about the Email")
        assert "reply" not in ents
        assert "email" not in ents

    def test_drops_single_capitalized_name(self, envoy_home):
        """Single-word capitalized tokens are intentionally NOT extracted —
        too noisy without a stopword list. Use aliases for unique people."""
        memory2 = _reload_memory(envoy_home)
        ents = memory2._extract_entities("Met with Salvador this morning")
        assert "salvador" not in ents

    def test_extracts_multi_word_capitalized_phrase(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        ents = memory2._extract_entities("Met with the AWS Marketing Team about Q3 2026")
        assert "aws marketing team" in ents
        assert "q3 2026" in ents

    def test_remember_indexes_entities(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        memory2.remember("ping alice@amazon.com about SIM-42")
        index = memory2._load_index()
        assert "alice" in index
        assert "sim-42" in index
        # Each entity points at the entry id
        assert len(index["alice"]) == 1


# --- pruning ----------------------------------------------------------------

class TestPruning:
    def test_prune_does_nothing_when_file_missing(self, envoy_home):
        memory2 = _reload_memory(envoy_home)
        # No file yet — should be a no-op, not crash.
        memory2._prune_if_needed()
        assert not os.path.exists(memory2.ENTRIES_FILE)

    def test_prune_triggers_compress_when_size_cap_exceeded(
        self, envoy_home, monkeypatch
    ):
        """Lower MAX_FILE_SIZE so a tiny entries file looks oversized.

        compress() is the function _prune_if_needed delegates to. We replace it
        with a recorder so we don't need real AI; the test verifies the trigger.
        """
        memory2 = _reload_memory(envoy_home)
        memory2.remember("just a small entry")

        called = {"n": 0}

        def fake_compress(force=False):
            called["n"] += 1
            return "ok"

        monkeypatch.setattr(memory2, "compress", fake_compress)
        # Make the existing tiny file appear oversized.
        monkeypatch.setattr(memory2, "MAX_FILE_SIZE", 1)
        memory2._prune_if_needed()
        assert called["n"] == 1

    def test_prune_triggers_compress_when_entry_count_exceeded(
        self, envoy_home, monkeypatch
    ):
        memory2 = _reload_memory(envoy_home)
        memory2.remember("entry one")
        memory2.remember("entry two")
        memory2.remember("entry three")

        called = {"n": 0}
        monkeypatch.setattr(memory2, "compress", lambda force=False: called.update(n=called["n"] + 1) or "ok")
        monkeypatch.setattr(memory2, "MAX_ENTRIES", 2)
        memory2._prune_if_needed()
        assert called["n"] == 1

    def test_prune_does_not_trigger_under_caps(self, envoy_home, monkeypatch):
        memory2 = _reload_memory(envoy_home)
        memory2.remember("a tiny note")

        called = {"n": 0}
        monkeypatch.setattr(memory2, "compress", lambda force=False: called.update(n=called["n"] + 1) or "ok")
        # Default caps are far above one tiny entry.
        memory2._prune_if_needed()
        assert called["n"] == 0
