"""Unit tests for agents/memory2.py.

Sandboxed via the ``envoy_home`` fixture so writes never touch the real
``~/.envoy`` directory. The memory2 module computes its storage paths from
``os.path.expanduser("~/...")`` at import time, so we have to recompute /
patch those module-level constants whenever the fixture moves $HOME.
"""

import importlib
import json
import os
from datetime import datetime, timedelta

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

    def test_size_gate_skips_readlines_when_file_too_small(self, envoy_home, monkeypatch):
        """Regression test: _prune_if_needed used to readlines() the whole
        entries file on every call, regardless of size. It should now only
        do that once the file is big enough that MAX_ENTRIES could plausibly
        be exceeded (size >= MAX_ENTRIES * MIN_ENTRY_BYTES)."""
        memory2 = _reload_memory(envoy_home)
        memory2.remember("one small entry")
        # Raise MAX_ENTRIES so the byte-size gate can't possibly be satisfied
        # by this tiny file, regardless of actual line count.
        monkeypatch.setattr(memory2, "MAX_ENTRIES", 10_000_000)

        opened = []
        real_open = open

        def spy_open(path, *a, **kw):
            opened.append(str(path))
            return real_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", spy_open)
        memory2._prune_if_needed()
        assert memory2.ENTRIES_FILE not in opened

    def test_size_gate_does_not_suppress_the_byte_size_cap(self, envoy_home, monkeypatch):
        """MAX_FILE_SIZE is checked by stat alone — it must still trigger
        compress() even though the line-count path is gated off."""
        memory2 = _reload_memory(envoy_home)
        memory2.remember("small entry")

        called = {"n": 0}
        monkeypatch.setattr(memory2, "compress", lambda force=False: called.update(n=called["n"] + 1) or "ok")
        monkeypatch.setattr(memory2, "MAX_FILE_SIZE", 1)

        opened = []
        real_open = open

        def spy_open(path, *a, **kw):
            opened.append(str(path))
            return real_open(path, *a, **kw)

        monkeypatch.setattr("builtins.open", spy_open)
        memory2._prune_if_needed()
        assert called["n"] == 1
        # The oversized-file branch returns before any readlines() call.
        assert memory2.ENTRIES_FILE not in opened

    def test_size_gate_opens_when_file_is_large_enough(self, envoy_home, monkeypatch):
        """Once the file is big enough that MAX_ENTRIES could plausibly be
        exceeded, the line count is actually performed."""
        memory2 = _reload_memory(envoy_home)
        memory2.remember("entry one")
        memory2.remember("entry two")
        memory2.remember("entry three")

        called = {"n": 0}
        monkeypatch.setattr(memory2, "compress", lambda force=False: called.update(n=called["n"] + 1) or "ok")
        monkeypatch.setattr(memory2, "MAX_ENTRIES", 2)
        monkeypatch.setattr(memory2, "MIN_ENTRY_BYTES", 1)  # force the size gate open
        memory2._prune_if_needed()
        assert called["n"] == 1


# --- entity index: in-memory cache + debounced flush -------------------------

class TestEntityIndexDebounce:
    @staticmethod
    def _freeze_clock(memory2, monkeypatch, start=1000.0):
        fake_time = {"t": start}
        monkeypatch.setattr(memory2.time, "monotonic", lambda: fake_time["t"])
        return fake_time

    def test_readers_see_in_memory_updates_before_any_flush(self, envoy_home, monkeypatch):
        memory2 = _reload_memory(envoy_home)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_EVERY_N", 1_000_000)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_INTERVAL", 1_000_000)
        self._freeze_clock(memory2, monkeypatch)

        memory2.remember("ping alice@amazon.com")
        memory2.remember("ping bob@amazon.com")
        # Debounced — nothing written to disk yet.
        assert not os.path.exists(memory2.ENTITIES_FILE)

        # But _load_index() / known_entities() still see both updates.
        index = memory2._load_index()
        assert "alice" in index and "bob" in index
        assert "alice" in memory2.known_entities()

    def test_flush_every_n_updates_triggers_disk_write(self, envoy_home, monkeypatch):
        memory2 = _reload_memory(envoy_home)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_EVERY_N", 3)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_INTERVAL", 1_000_000)
        self._freeze_clock(memory2, monkeypatch)

        memory2.remember("ping alice@amazon.com")
        memory2.remember("ping bob@amazon.com")
        assert not os.path.exists(memory2.ENTITIES_FILE)

        memory2.remember("ping carol@amazon.com")  # 3rd update — hits EVERY_N
        on_disk = json.loads(open(memory2.ENTITIES_FILE).read())
        assert "alice" in on_disk and "bob" in on_disk and "carol" in on_disk

    def test_flush_after_interval_elapses(self, envoy_home, monkeypatch):
        memory2 = _reload_memory(envoy_home)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_EVERY_N", 1_000_000)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_INTERVAL", 30)
        fake_time = self._freeze_clock(memory2, monkeypatch)

        # The very first update after a fresh module load always flushes
        # (module-level _index_last_flush starts at 0.0 — "infinitely long
        # ago" — so we don't leave the first write unflushed indefinitely).
        memory2.remember("ping alice@amazon.com")
        on_disk = json.loads(open(memory2.ENTITIES_FILE).read())
        assert "alice" in on_disk

        # Too soon after that flush — debounced, not yet on disk.
        memory2.remember("ping bob@amazon.com")
        on_disk = json.loads(open(memory2.ENTITIES_FILE).read())
        assert "bob" not in on_disk

        fake_time["t"] += 31  # past INDEX_FLUSH_INTERVAL since the last flush
        memory2.remember("ping dave@amazon.com")

        on_disk = json.loads(open(memory2.ENTITIES_FILE).read())
        assert "bob" in on_disk
        assert "dave" in on_disk

    def test_atexit_hook_flushes_dirty_index(self, envoy_home, monkeypatch):
        """This is exactly what atexit.register(_flush_index_if_dirty) calls
        on interpreter shutdown, so debounced updates aren't lost."""
        memory2 = _reload_memory(envoy_home)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_EVERY_N", 1_000_000)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_INTERVAL", 1_000_000)
        self._freeze_clock(memory2, monkeypatch)

        memory2.remember("ping alice@amazon.com")
        assert not os.path.exists(memory2.ENTITIES_FILE)

        memory2._flush_index_if_dirty()

        on_disk = json.loads(open(memory2.ENTITIES_FILE).read())
        assert "alice" in on_disk

    def test_atexit_hook_is_a_noop_when_nothing_dirty(self, envoy_home, monkeypatch):
        memory2 = _reload_memory(envoy_home)
        # No remember() calls at all — cache never loaded, nothing dirty.
        memory2._flush_index_if_dirty()
        assert not os.path.exists(memory2.ENTITIES_FILE)

    def test_save_index_full_replace_flushes_immediately(self, envoy_home, monkeypatch):
        """compress()/rebuild_entity_index() call _save_index() directly and
        expect an immediate flush regardless of debounce settings."""
        memory2 = _reload_memory(envoy_home)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_EVERY_N", 1_000_000)
        monkeypatch.setattr(memory2, "INDEX_FLUSH_INTERVAL", 1_000_000)
        self._freeze_clock(memory2, monkeypatch)

        memory2._save_index({"someone": ["e1"]})
        on_disk = json.loads(open(memory2.ENTITIES_FILE).read())
        assert on_disk == {"someone": ["e1"]}


# --- compress() failure backoff ----------------------------------------------

class TestCompressFailureBackoff:
    """compress() is reached from the remember() -> _prune_if_needed() hot
    path with force=False. These tests seed a genuinely old entry (rather
    than using force=True) so compress() actually attempts AI compression
    without needing to bypass the 'nothing old enough' gate — that keeps the
    backoff assertions exercising the same force=False path the hot loop
    uses, instead of force=True (which is a deliberate escape hatch — see
    test_force_bypasses_the_backoff below)."""

    @staticmethod
    def _seed_old_entry(memory2, text="an old note"):
        memory2._ensure_dir()
        old_ts = (datetime.now() - timedelta(days=memory2.COMPRESS_AFTER_DAYS + 1)).isoformat()
        entry = {
            "id": "seed00000000000001",
            "ts": old_ts,
            "type": "action",
            "importance": "notable",
            "text": text,
            "entities": [],
        }
        with open(memory2.ENTRIES_FILE, "w") as f:
            f.write(json.dumps(entry) + "\n")

    def test_repeated_failure_is_not_retried_within_backoff_window(
        self, envoy_home, monkeypatch
    ):
        memory2 = _reload_memory(envoy_home)
        self._seed_old_entry(memory2)

        calls = {"n": 0}

        def fake_invoke_ai(prompt, max_tokens=1500, tier="memory"):
            calls["n"] += 1
            return "not valid json"

        monkeypatch.setattr(memory2, "invoke_ai", fake_invoke_ai)
        fake_time = {"t": 1000.0}
        monkeypatch.setattr(memory2.time, "monotonic", lambda: fake_time["t"])

        out1 = memory2.compress()
        assert "Compression failed" in out1
        assert calls["n"] == 1

        # Immediate retry — backoff should skip it without calling invoke_ai again.
        out2 = memory2.compress()
        assert "skipped" in out2.lower()
        assert calls["n"] == 1

    def test_retries_after_backoff_window_elapses(self, envoy_home, monkeypatch):
        memory2 = _reload_memory(envoy_home)
        self._seed_old_entry(memory2)

        calls = {"n": 0}

        def fake_invoke_ai(prompt, max_tokens=1500, tier="memory"):
            calls["n"] += 1
            return "not valid json"

        monkeypatch.setattr(memory2, "invoke_ai", fake_invoke_ai)
        fake_time = {"t": 1000.0}
        monkeypatch.setattr(memory2.time, "monotonic", lambda: fake_time["t"])

        memory2.compress()
        assert calls["n"] == 1

        fake_time["t"] += memory2.COMPRESS_FAILURE_BACKOFF + 1
        memory2.compress()
        assert calls["n"] == 2

    def test_successful_compress_resets_the_backoff(self, envoy_home, monkeypatch):
        memory2 = _reload_memory(envoy_home)
        self._seed_old_entry(memory2)

        calls = {"n": 0}

        def flaky_invoke_ai(prompt, max_tokens=1500, tier="memory"):
            calls["n"] += 1
            return "not valid json" if calls["n"] == 1 else "{}"

        monkeypatch.setattr(memory2, "invoke_ai", flaky_invoke_ai)
        fake_time = {"t": 1000.0}
        monkeypatch.setattr(memory2.time, "monotonic", lambda: fake_time["t"])

        memory2.compress()
        assert memory2._last_compress_failure != 0.0

        # The failed attempt returns before rewriting entries.jsonl, so the
        # same old entry is still there for the retry after backoff elapses.
        fake_time["t"] += memory2.COMPRESS_FAILURE_BACKOFF + 1
        memory2.compress()
        assert memory2._last_compress_failure == 0.0

    def test_backoff_does_not_apply_without_a_prior_failure(self, envoy_home, monkeypatch):
        memory2 = _reload_memory(envoy_home)
        self._seed_old_entry(memory2)
        monkeypatch.setattr(memory2, "invoke_ai", lambda *a, **k: "{}")
        out = memory2.compress()
        assert "skipped" not in out.lower()

    def test_force_bypasses_the_backoff(self, envoy_home, monkeypatch):
        """force=True is an explicit user-initiated retry (e.g. a manual
        /memory compress) and should not be blocked by the automatic
        backoff that protects the remember() -> _prune_if_needed() hot path."""
        memory2 = _reload_memory(envoy_home)
        self._seed_old_entry(memory2)

        calls = {"n": 0}

        def fake_invoke_ai(prompt, max_tokens=1500, tier="memory"):
            calls["n"] += 1
            return "not valid json"

        monkeypatch.setattr(memory2, "invoke_ai", fake_invoke_ai)
        fake_time = {"t": 1000.0}
        monkeypatch.setattr(memory2.time, "monotonic", lambda: fake_time["t"])

        memory2.compress()  # records a failure (force=False, as the hot path does)
        assert calls["n"] == 1

        fake_time["t"] += 1  # still well within the backoff window
        out = memory2.compress(force=True)
        assert "skipped" not in out.lower()
        assert calls["n"] == 2
