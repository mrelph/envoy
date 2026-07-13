"""Unified memory system — structured entries with entity indexing and topic recall.

Merges the old memory + observer into one system. Every entry is tagged with
entities (people, projects, topics) for fast retrieval. Compression preserves
per-entity threads instead of flattening everything into one paragraph.

Storage:
    ~/.envoy/memory/entries.jsonl   — append-only log of all entries
    ~/.envoy/memory/entities.json   — entity → entry ID index
    ~/.envoy/memory/summary.json    — rolling compressed summary
"""

import atexit
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from agents.base import invoke_ai
from agents.paths import config_dir

MEMORY_DIR = str(config_dir() / "memory")
ENTRIES_FILE = os.path.join(MEMORY_DIR, "entries.jsonl")
ENTITIES_FILE = os.path.join(MEMORY_DIR, "entities.json")
SUMMARY_FILE = os.path.join(MEMORY_DIR, "summary.json")

# Limits
MAX_ENTRY_LEN = 500
MAX_ENTRIES = 2000       # prune oldest beyond this
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB hard limit per file
SUMMARY_MAX = 3000
RECALL_DEFAULT = 20      # entries returned by default

# Importance tiers — control retention
#   routine:   auto-prune after 3 days (inbox scans, status checks)
#   notable:   keep 14 days, then compress (decisions, meetings, outcomes)
#   permanent: never auto-prune or compress (corrections, preferences, key decisions)
TIER_KEEP_DAYS = {"routine": 3, "notable": 14, "permanent": 9999}
COMPRESS_AFTER_DAYS = 7  # compress notable entries older than this

# Conservative floor for the byte size of a minimal JSON entry line (id + ts +
# type + importance + text + entities, all near-empty). Real entries run
# larger (up to MAX_ENTRY_LEN=500 chars of text alone), so a file smaller than
# MAX_ENTRIES * MIN_ENTRY_BYTES cannot possibly hold more than MAX_ENTRIES
# lines — used by _prune_if_needed to skip a full readlines() on every write.
MIN_ENTRY_BYTES = 100

# Entity index (entities.json) debounce — remember() calls _index_entry() on
# every worker delegation; without debouncing that rewrites the whole file
# each time. Flush at most every INDEX_FLUSH_INTERVAL seconds or every
# INDEX_FLUSH_EVERY_N updates, whichever comes first, plus an atexit flush so
# the last few updates aren't lost on shutdown.
INDEX_FLUSH_INTERVAL = 30  # seconds
INDEX_FLUSH_EVERY_N = 20   # updates

# compress() failure backoff — if the AI-compression parse fails, don't
# re-attempt for this long. Without it, a near-full entries file retries
# compression (and pays for the AI call) on every single write.
COMPRESS_FAILURE_BACKOFF = 600  # 10 minutes

# External vault paths (Obsidian, directories) — searched on recall fallback
VAULT_CONFIG_FILE = str(config_dir() / "config.json")


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


# --- Entity extraction (no AI, just pattern matching) ---
#
# Three strict signals — anything else is too noisy to index. We deliberately
# do NOT collect bare single-word capitalized tokens; that approach required a
# stopword list that grew to ~80 entries and still leaked words like "Looking"
# or "Information" into entity tags.
#   1. Amazon aliases (alice@amazon.com, @bob)
#   2. Project / ticket IDs (KP-1234, SIM-5678, Foo-42)
#   3. Multi-word capitalized phrases ("AWS Marketing Team", "Q3 2026")
# Single-word names like "Sarah" only flow through if their alias appears
# nearby — that's intentional, since "sarah" alone isn't unique enough to
# be a useful retrieval key.

_ALIAS_RE = re.compile(r'\b([a-z]{2,12})@amazon\.com\b|@([a-z]{2,12})\b')
_PROJECT_RE = re.compile(r'\b(KP-\d+|SIM-\d+|[A-Z][a-z]+-\d+)\b')
_TOPIC_RE = re.compile(
    r'\b(Q[1-4]\s*\d{4}|Q[1-4]\b|[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b'
)


def _extract_entities(text: str) -> List[str]:
    """Extract people, project IDs, and topics from text. Fast, no AI."""
    entities = set()

    # Aliases — case-insensitive. Skip the topic pass on noisy text (raw JSON
    # / markdown soup) since multi-word matching there is mostly false
    # positives off escape sequences.
    for m in _ALIAS_RE.finditer(text.lower()):
        alias = m.group(1) or m.group(2)
        if alias and len(alias) > 2:
            entities.add(alias)

    # Project / ticket IDs
    for m in _PROJECT_RE.finditer(text):
        entities.add(m.group(1).lower())

    is_noisy = text.count("\\n") > 3 or text.count("{") > 2 or text.count("**") > 2
    if not is_noisy:
        # Multi-word capitalized phrases — must be at least 2 capitalized
        # words. Single capitalized tokens are intentionally ignored.
        for m in _TOPIC_RE.finditer(text):
            phrase = m.group(1).strip().lower()
            if 4 <= len(phrase) <= 60:
                entities.add(phrase)

    return sorted(entities)[:10]


# --- Core operations ---

def remember(text: str, entry_type: str = "action", importance: str = "notable") -> str:
    """Store an entry with auto-extracted entities.

    Args:
        text: What to remember
        entry_type: action, context, decision, observation, preference
        importance: routine (3-day), notable (14-day), permanent (forever)
    """
    _ensure_dir()
    if importance not in TIER_KEEP_DAYS:
        importance = "notable"
    entities = _extract_entities(text)
    entry_id = datetime.now().strftime("%Y%m%d%H%M%S%f")[:18]
    entry = {
        "id": entry_id,
        "ts": datetime.now().isoformat(),
        "type": entry_type,
        "importance": importance,
        "text": text[:MAX_ENTRY_LEN],
        "entities": entities,
    }
    with open(ENTRIES_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    # Update entity index
    _index_entry(entry_id, entities)
    # Prune if needed
    _prune_if_needed()
    return f"Remembered: {text[:80]}" + (f" [tagged: {', '.join(entities[:5])}]" if entities else "")


def recall(query: str = "", limit: int = RECALL_DEFAULT) -> str:
    """Recall memory — by topic/entity or general.

    Args:
        query: Entity name, topic, or empty for general recall
        limit: Max entries to return
    """
    _ensure_dir()
    if query:
        return _recall_by_query(query, limit)
    return _recall_general(limit)


def _recall_general(limit: int) -> str:
    """General recall: today's entries + top entity summaries."""
    sections = []

    # Per-entity summaries (top N by relevance to recent entries)
    summaries = _load_summary()
    if summaries:
        # Prioritize entities that appear in recent entries
        recent = _load_entries(days=3)
        recent_entities = set()
        for e in recent:
            recent_entities.update(e.get("entities", []))

        # Show entities mentioned recently first, then others
        active = {k: v for k, v in summaries.items() if k in recent_entities and k != "_general"}
        other = {k: v for k, v in summaries.items() if k not in recent_entities and k != "_general"}

        lines = []
        for k, v in sorted(active.items()):
            lines.append(f"- **{k}**: {v}")
        for k, v in sorted(other.items())[:10]:  # cap background context
            lines.append(f"- {k}: {v}")
        if summaries.get("_general"):
            lines.append(f"- _general: {summaries['_general']}")

        if lines:
            sections.append("### Patterns & Context\n" + "\n".join(lines[:20]))

    # Recent entries (last 3 days, newest first)
    entries = _load_entries(days=3)
    if entries:
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        grouped = {}
        for e in entries[-limit:]:
            day = e["ts"][:10]
            label = "Today" if day == today else ("Yesterday" if day == yesterday else day)
            grouped.setdefault(label, []).append(e)

        for label in ["Today", "Yesterday"]:
            if label in grouped:
                lines = [f"- {e['ts'][11:16]} [{e['type']}] {e['text']}" for e in grouped[label]]
                sections.append(f"### {label}\n" + "\n".join(lines))
        for label, entries_list in grouped.items():
            if label not in ("Today", "Yesterday"):
                lines = [f"- {e['ts'][11:16]} [{e['type']}] {e['text']}" for e in entries_list]
                sections.append(f"### {label}\n" + "\n".join(lines))

    if not sections:
        return ""
    return "## Memory\n\n" + "\n\n".join(sections)


def _recall_by_query(query: str, limit: int) -> str:
    """Recall entries matching a query — checks entity summaries and raw entries."""
    query_lower = query.lower().strip()

    # Check entity summaries first
    summaries = _load_summary()
    summary_hit = summaries.get(query_lower, "")
    related_summaries = []
    if not summary_hit:
        # Partial match on entity names
        for k, v in summaries.items():
            if query_lower in k or k in query_lower:
                related_summaries.append((k, v))

    # Search raw entries
    entries = _load_entries(days=max(TIER_KEEP_DAYS.values()))
    scored = []
    for e in entries:
        score = 0
        if query_lower in e.get("entities", []):
            score += 10
        for ent in e.get("entities", []):
            if query_lower in ent or ent in query_lower:
                score += 5
        if query_lower in e.get("text", "").lower():
            score += 3
        if score > 0:
            scored.append((score, e))

    scored.sort(key=lambda x: -x[0])
    matches = [e for _, e in scored[:limit]]

    parts = []

    # Entity summary
    if summary_hit:
        parts.append(f"**{query_lower}** (summary): {summary_hit}")
    for k, v in related_summaries[:5]:
        parts.append(f"**{k}** (summary): {v}")

    # Raw entries
    if matches:
        entities_found = set()
        for e in matches:
            entities_found.update(e.get("entities", []))
        parts.append(f"**{len(matches)} entries** | Related: {', '.join(sorted(entities_found)[:10])}")
        parts.extend(f"- {e['ts'][:16]} [{e['type']}] {e['text']}" for e in matches)

    if not parts:
        # Fallback: search external vaults (Obsidian, directories)
        vault_result = _search_vault(query)
        if vault_result:
            return f"## Memory: {query}\n\n*(from external vault)*\n\n{vault_result}"
        return f"No memory entries found for '{query}'."

    # Also check vaults for supplementary context
    vault_result = _search_vault(query)
    if vault_result:
        parts.append(f"\n*(from vault)*\n{vault_result}")

    return f"## Memory: {query}\n\n" + "\n".join(parts)


# --- Entity index ---
#
# Kept in memory (loaded once from entities.json, updated incrementally) and
# flushed to disk with debouncing instead of rewriting the whole file on
# every remember() call. `_index_lock` guards the in-memory cache since
# workers can call remember() from multiple threads.

_index_lock = threading.Lock()
_index_cache: Optional[Dict[str, List[str]]] = None
_index_dirty = False
_index_updates_since_flush = 0
_index_last_flush = 0.0


def _load_index_from_disk() -> Dict[str, List[str]]:
    if os.path.exists(ENTITIES_FILE):
        try:
            return json.loads(open(ENTITIES_FILE).read())
        except Exception:
            pass
    return {}


def _flush_index_to_disk(index: dict):
    try:
        _ensure_dir()
        with open(ENTITIES_FILE, "w") as f:
            json.dump(index, f)
    except Exception:
        pass


def _load_index() -> Dict[str, List[str]]:
    """Return the entity index, loading from disk once and caching in memory.

    Readers (known_entities(), etc.) always see the up-to-date in-memory
    copy, including updates made by _index_entry() that haven't been
    flushed to disk yet.
    """
    global _index_cache
    with _index_lock:
        if _index_cache is None:
            _index_cache = _load_index_from_disk()
        return {k: list(v) for k, v in _index_cache.items()}


def _save_index(index: dict):
    """Full replace of the index — used by compress()/rebuild_entity_index(),
    which already rebuild the whole thing. Flushes immediately (these are
    infrequent, not the remember() hot path)."""
    global _index_cache, _index_dirty, _index_updates_since_flush, _index_last_flush
    with _index_lock:
        _index_cache = index
        _index_dirty = False
        _index_updates_since_flush = 0
        _index_last_flush = time.monotonic()
    _flush_index_to_disk(index)


def _index_entry(entry_id: str, entities: List[str]):
    """Incrementally update the in-memory entity index; flush is debounced.

    remember() calls this on every worker delegation — rewriting the full
    entities.json each time was needless I/O on the hot path. Flushes at
    most every INDEX_FLUSH_INTERVAL seconds or INDEX_FLUSH_EVERY_N updates.
    """
    global _index_cache, _index_dirty, _index_updates_since_flush, _index_last_flush
    snapshot = None
    with _index_lock:
        if _index_cache is None:
            _index_cache = _load_index_from_disk()
        for entity in entities:
            bucket = _index_cache.setdefault(entity, [])
            bucket.append(entry_id)
            # Cap per entity
            if len(bucket) > 100:
                _index_cache[entity] = bucket[-100:]
        _index_dirty = True
        _index_updates_since_flush += 1
        should_flush = (
            _index_updates_since_flush >= INDEX_FLUSH_EVERY_N
            or (time.monotonic() - _index_last_flush) >= INDEX_FLUSH_INTERVAL
        )
        if should_flush:
            snapshot = {k: list(v) for k, v in _index_cache.items()}
            _index_dirty = False
            _index_updates_since_flush = 0
            _index_last_flush = time.monotonic()
    if snapshot is not None:
        _flush_index_to_disk(snapshot)


def _flush_index_if_dirty():
    """atexit hook so debounced updates aren't lost when the process exits."""
    with _index_lock:
        if not _index_dirty or _index_cache is None:
            return
        snapshot = {k: list(v) for k, v in _index_cache.items()}
    _flush_index_to_disk(snapshot)


atexit.register(_flush_index_if_dirty)


def known_entities() -> List[str]:
    """Return all known entities sorted by frequency."""
    index = _load_index()
    return sorted(index.keys(), key=lambda k: -len(index[k]))


# --- Entry loading ---

def _load_entries(days: int = 14) -> list:
    """Load entries respecting importance tiers.
    
    Each entry is kept based on its importance tier:
      routine: 3 days, notable: 14 days, permanent: always
    The `days` param acts as an upper bound override.
    """
    if not os.path.exists(ENTRIES_FILE):
        return []
    now = datetime.now()
    entries = []
    for line in open(ENTRIES_FILE):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            ts = datetime.fromisoformat(e["ts"])
            importance = e.get("importance", "notable")
            keep_days = min(days, TIER_KEEP_DAYS.get(importance, 14))
            if ts >= now - timedelta(days=keep_days):
                entries.append(e)
        except Exception:
            pass
    return entries


# --- Compression ---

# Module-level timestamp of the last failed AI-compression parse. Read/write
# via time.monotonic() so a failed compress() doesn't get retried (and pay
# for another AI call) on every single remember() while a near-full file
# keeps calling _prune_if_needed() -> compress().
_last_compress_failure = 0.0


def compress(force: bool = False) -> str:
    """Compress old entries into per-entity rolling summaries."""
    global _last_compress_failure
    if not force and _last_compress_failure and (
        time.monotonic() - _last_compress_failure < COMPRESS_FAILURE_BACKOFF
    ):
        return "Compression skipped — recent AI-compression failure, will retry later."

    _ensure_dir()
    cutoff = datetime.now() - timedelta(days=COMPRESS_AFTER_DAYS)
    old_entries = []
    recent = []

    if not os.path.exists(ENTRIES_FILE):
        return "Nothing to compress."

    for line in open(ENTRIES_FILE):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if datetime.fromisoformat(e["ts"]) < cutoff:
                old_entries.append(e)
            else:
                recent.append(e)
        except Exception:
            recent.append({"text": line})

    if not old_entries and not force:
        return "Nothing old enough to compress."

    # Group old entries by entity
    entity_threads = {}
    general = []
    for e in old_entries:
        entities = e.get("entities", [])
        if entities:
            for ent in entities:
                entity_threads.setdefault(ent, []).append(e)
        else:
            general.append(e)

    # Load existing summaries
    existing = _load_summary()

    # Format for AI compression
    sections = []
    for ent, entries in sorted(entity_threads.items(), key=lambda x: -len(x[1]))[:30]:
        prev = existing.get(ent, "")
        lines = [f"  - {e['ts'][:10]} [{e['type']}] {e['text']}" for e in entries[-5:]]
        sections.append(f"**{ent}** (prev: {prev or 'none'})\n" + "\n".join(lines))
    if general:
        prev = existing.get("_general", "")
        lines = [f"  - {e['ts'][:10]} [{e['type']}] {e['text']}" for e in general[-10:]]
        sections.append(f"**_general** (prev: {prev or 'none'})\n" + "\n".join(lines))

    compression_ok = False
    try:
        raw = invoke_ai(
            "Compress these memory entries into per-entity summaries. "
            "Output ONLY a JSON object where each key is the entity name and the value is a concise summary string (max 200 chars each). "
            "Keep: latest status, key decisions, unresolved items, preferences. Drop stale resolved items.\n\n"
            + "\n\n".join(sections),
            max_tokens=1500, tier="memory"
        )
        # Parse JSON from response (handle markdown fences)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
        new_summaries = json.loads(raw)
        # Merge with existing (new overwrites old)
        existing.update(new_summaries)
        compression_ok = True
    except Exception:
        pass  # keep existing summaries on failure

    if not compression_ok:
        _last_compress_failure = time.monotonic()
        return f"Compression failed — kept all {len(old_entries) + len(recent)} entries intact."

    _last_compress_failure = 0.0

    # Cap total entities in summary
    if len(existing) > 100:
        # Keep most recently updated — sort by whether they appear in recent entries
        recent_entities = set()
        for e in recent:
            recent_entities.update(e.get("entities", []))
        # Keep entities that are in recent entries + top by entry count
        keep = {k for k in existing if k in recent_entities or k == "_general"}
        for ent in sorted(entity_threads.keys(), key=lambda x: -len(entity_threads.get(x, []))):
            keep.add(ent)
            if len(keep) >= 100:
                break
        existing = {k: v for k, v in existing.items() if k in keep}

    _save_summary(existing)

    # Rewrite entries file with only recent entries
    with open(ENTRIES_FILE, "w") as f:
        for e in recent:
            f.write(json.dumps(e) + "\n")

    # Rebuild index from remaining entries
    index = {}
    for e in recent:
        for ent in e.get("entities", []):
            index.setdefault(ent, []).append(e.get("id", ""))
    _save_index(index)

    return f"Compressed {len(old_entries)} old entries into {len(existing)} entity summaries. {len(recent)} recent entries kept."


def _load_summary() -> Dict[str, str]:
    """Load entity summaries. Handles both old blob format and new dict format."""
    if not os.path.exists(SUMMARY_FILE):
        return {}
    try:
        data = json.loads(open(SUMMARY_FILE).read())
        if isinstance(data, dict) and "text" in data and isinstance(data["text"], str):
            # Old blob format — migrate: store as _general
            return {"_general": data["text"]} if data["text"] else {}
        if isinstance(data, dict):
            # Remove metadata keys, keep only entity summaries
            return {k: v for k, v in data.items() if isinstance(v, str) and k != "updated"}
        return {}
    except Exception:
        return {}


def _save_summary(summaries: Dict[str, str]):
    with open(SUMMARY_FILE, "w") as f:
        json.dump(summaries, f, indent=1)


# --- Pruning ---

def _prune_if_needed():
    """Prune if entries file is too large (by count or file size).

    remember() calls this after every write, so keep it cheap: a stat
    (os.path.getsize) is essentially free, but readlines() on a file that
    can be up to MAX_FILE_SIZE (2MB) is not. Only fall through to counting
    lines when the file is big enough that it's actually possible
    MAX_ENTRIES has been exceeded (size >= MAX_ENTRIES * MIN_ENTRY_BYTES);
    the MAX_FILE_SIZE check never needs a line count at all.
    """
    if not os.path.exists(ENTRIES_FILE):
        return
    try:
        size = os.path.getsize(ENTRIES_FILE)
        if size > MAX_FILE_SIZE:
            compress()
            return
        if size < MAX_ENTRIES * MIN_ENTRY_BYTES:
            return
        lines = open(ENTRIES_FILE).readlines()
        if len(lines) > MAX_ENTRIES:
            compress()
    except Exception:
        pass


# --- Migration from old format ---

def migrate_old_memory():
    """One-time migration from old memory format (today.jsonl, days/, monthly.json)."""
    old_today = os.path.join(MEMORY_DIR, "today.jsonl")
    old_days = os.path.join(MEMORY_DIR, "days")
    old_monthly = os.path.join(MEMORY_DIR, "monthly.json")
    old_observations = os.path.join(MEMORY_DIR, "observations.jsonl")
    migrated = 0

    # Migrate today.jsonl
    if os.path.exists(old_today):
        for line in open(old_today):
            try:
                e = json.loads(line.strip())
                remember(e.get("text", ""), e.get("type", "action"))
                migrated += 1
            except Exception:
                pass
        os.rename(old_today, old_today + ".migrated")

    # Migrate observations.jsonl
    if os.path.exists(old_observations):
        for line in open(old_observations):
            try:
                e = json.loads(line.strip())
                text = f"{e.get('summary', '')} → {e.get('outcome', '')}"
                remember(text, entry_type="observation")
                migrated += 1
            except Exception:
                pass
        os.rename(old_observations, old_observations + ".migrated")

    # Migrate daily summaries from days/ directory
    if os.path.exists(old_days) and os.path.isdir(old_days):
        for fname in sorted(os.listdir(old_days)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(old_days, fname)
            try:
                data = json.loads(open(fpath).read())
                date_str = data.get("date", fname.replace(".json", ""))
                text = data.get("text", "")
                if text:
                    entry_id = date_str.replace("-", "") + "235900"
                    entry = {
                        "id": entry_id,
                        "ts": f"{date_str}T23:59:00",
                        "type": "context",
                        "text": text[:MAX_ENTRY_LEN],
                        "entities": _extract_entities(text),
                    }
                    _ensure_dir()
                    with open(ENTRIES_FILE, "a") as f:
                        f.write(json.dumps(entry) + "\n")
                    _index_entry(entry_id, entry["entities"])
                    migrated += 1
            except Exception:
                pass
        os.rename(old_days, old_days + ".migrated")

    # Migrate monthly summary
    if os.path.exists(old_monthly):
        try:
            data = json.loads(open(old_monthly).read())
            if data.get("text"):
                with open(SUMMARY_FILE, "w") as f:
                    json.dump({"updated": datetime.now().isoformat(), "text": data["text"]}, f)
        except Exception:
            pass
        os.rename(old_monthly, old_monthly + ".migrated")

    return f"Migrated {migrated} entries from old format." if migrated else "Nothing to migrate."


def _search_vault(query: str) -> str:
    """Structure-aware vault search — routes queries to the right subfolder.
    
    Intent detection:
      - Person names / aliases → 02 - People/
      - Partner/company names → 10 - Org Relationships/ + wiki/entities/
      - Concepts / frameworks → wiki/concepts/ + wiki/topics/
      - Meeting context → 08 - Meeting Notes/
      - Briefing / EBC / prep → 03 - Briefings/
      - Doc reviews / narratives → 04 - Doc Reviews/
      - Research / deep dives → 05 - Research/
      - Presentations / decks → 06 - Presentations/
      - Think Big / vision → 07 - Think Big/
      - Reflections / lessons → 09 - Reflections/
      - Projects / initiatives → wiki/projects/
      - Standards / guidelines → 01 - Steering/
      - Fallback → full vault search (capped)
    """
    paths = _get_vault_paths()
    if not paths:
        return ""

    query_lower = query.lower()
    query_terms = [t.lower() for t in query.split() if len(t) > 2]
    if not query_terms:
        return ""

    # Determine which subfolders to prioritize based on intent
    priority_subdirs = _route_query(query_lower)

    results = []
    for vault_path in paths:
        vault_path = os.path.expanduser(vault_path)
        if not os.path.isdir(vault_path):
            continue

        # Search priority folders first (higher score boost)
        searched_files = set()
        for subdir, boost in priority_subdirs:
            target = os.path.join(vault_path, subdir)
            if not os.path.isdir(target):
                continue
            hits = _scan_folder(target, query_terms, vault_path, max_files=100)
            for score, snippet, fpath in hits:
                searched_files.add(fpath)
                results.append((score + boost, snippet))

        # Fallback: scan remaining vault (lower priority, capped)
        file_count = 0
        for root, _dirs, files in os.walk(vault_path):
            _dirs[:] = [d for d in _dirs if not d.startswith(".")]
            for fname in files:
                if not fname.endswith(".md"):
                    continue
                fpath = os.path.join(root, fname)
                if fpath in searched_files:
                    continue
                file_count += 1
                if file_count > 200:
                    break
                hit = _score_file(fpath, query_terms, vault_path)
                if hit:
                    results.append(hit)
            if file_count > 200:
                break

    if not results:
        return ""

    results.sort(key=lambda x: -x[0])
    return "\n\n".join(r[1] for r in results[:5])


# Vault structure routing table
_PERSON_SIGNALS = {"who is", "about ", "prep for my 1:1", "relationship with", "report"}
_PARTNER_SIGNALS = {"partner", "customer", "dossier", "relationship", "health", "cold", "pulse"}
_CONCEPT_SIGNALS = {"what is", "concept", "framework", "strategy", "how does", "explain"}
_MEETING_SIGNALS = {"meeting", "discussed", "action item", "1:1", "sync", "review"}
_BRIEFING_SIGNALS = {"briefing", "ebc", "prep", "brief", "talking points"}
_REVIEW_SIGNALS = {"doc review", "review document", "feedback on", "prfaq", "pr-faq", "narrative", "6-pager"}
_RESEARCH_SIGNALS = {"research", "analysis", "deep dive", "investigate", "explore", "study"}
_PRESENTATION_SIGNALS = {"presentation", "slide", "deck", "talk", "keynote", "demo"}
_THINK_BIG_SIGNALS = {"think big", "vision", "future", "bold", "moonshot", "big bet", "innovation"}
_REFLECTION_SIGNALS = {"reflection", "lesson", "retrospective", "retro", "learned", "growth", "mistake"}
_PROJECT_SIGNALS = {"project", "initiative", "workstream", "program", "milestone", "deliverable"}
_STEERING_SIGNALS = {"standard", "principle", "guideline", "language rule", "writing style", "decision framework"}


def _route_query(query_lower: str) -> list:
    """Return list of (subfolder, score_boost) tuples ordered by relevance."""
    routes = []

    if any(s in query_lower for s in _PERSON_SIGNALS):
        routes.append(("02 - People", 5))
        routes.append(("wiki/entities", 3))

    if any(s in query_lower for s in _PARTNER_SIGNALS):
        routes.append(("10 - Org Relationships", 5))
        routes.append(("wiki/entities", 4))
        routes.append(("03 - Briefings", 2))

    if any(s in query_lower for s in _CONCEPT_SIGNALS):
        routes.append(("wiki/concepts", 5))
        routes.append(("wiki/topics", 4))

    if any(s in query_lower for s in _MEETING_SIGNALS):
        routes.append(("08 - Meeting Notes", 5))

    if any(s in query_lower for s in _BRIEFING_SIGNALS):
        routes.append(("03 - Briefings", 5))

    if any(s in query_lower for s in _REVIEW_SIGNALS):
        routes.append(("04 - Doc Reviews", 5))
        routes.append(("01 - Steering", 2))

    if any(s in query_lower for s in _RESEARCH_SIGNALS):
        routes.append(("05 - Research", 5))
        routes.append(("wiki/topics", 3))

    if any(s in query_lower for s in _PRESENTATION_SIGNALS):
        routes.append(("06 - Presentations", 5))

    if any(s in query_lower for s in _THINK_BIG_SIGNALS):
        routes.append(("07 - Think Big", 5))
        routes.append(("wiki/topics", 3))

    if any(s in query_lower for s in _REFLECTION_SIGNALS):
        routes.append(("09 - Reflections", 5))

    if any(s in query_lower for s in _PROJECT_SIGNALS):
        routes.append(("wiki/projects", 5))
        routes.append(("wiki/topics", 3))

    if any(s in query_lower for s in _STEERING_SIGNALS):
        routes.append(("01 - Steering", 5))

    # Always include wiki as a secondary source
    if not any(r[0].startswith("wiki/") for r in routes):
        routes.append(("wiki/entities", 2))
        routes.append(("wiki/topics", 2))

    return routes


def _scan_folder(folder: str, query_terms: list, vault_root: str, max_files: int = 100) -> list:
    """Scan a specific folder for matches. Returns [(score, snippet, filepath)]."""
    results = []
    file_count = 0
    for root, _dirs, files in os.walk(folder):
        _dirs[:] = [d for d in _dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            file_count += 1
            if file_count > max_files:
                return results
            fpath = os.path.join(root, fname)
            hit = _score_file(fpath, query_terms, vault_root)
            if hit:
                results.append((hit[0], hit[1], fpath))
    return results


def _score_file(fpath: str, query_terms: list, vault_root: str):
    """Score a single file against query terms. Returns (score, snippet) or None."""
    try:
        content = open(fpath, encoding="utf-8", errors="ignore").read(5000)
        content_lower = content.lower()
        # Filename match gets a bonus
        fname_lower = os.path.basename(fpath).lower()
        fname_hits = sum(2 for t in query_terms if t in fname_lower)
        content_hits = sum(1 for t in query_terms if t in content_lower)
        total = fname_hits + content_hits
        if total >= max(1, len(query_terms) // 2):
            lines = content.split("\n")
            matched_lines = [
                l.strip() for l in lines
                if any(t in l.lower() for t in query_terms)
                and len(l.strip()) > 10
            ][:5]
            if matched_lines:
                rel_path = os.path.relpath(fpath, vault_root)
                snippet = "\n".join(matched_lines)
                return (total, f"**{rel_path}**\n{snippet}")
    except Exception:
        pass
    return None


def _get_vault_paths() -> List[str]:
    """Load vault/directory paths from config.json."""
    try:
        if os.path.exists(VAULT_CONFIG_FILE):
            config = json.loads(open(VAULT_CONFIG_FILE).read())
            return config.get("memory_vaults", [])
    except Exception:
        pass
    return []


def add_vault_path(path: str) -> str:
    """Add an external vault/directory path to memory sources."""
    path = os.path.expanduser(path)
    if not os.path.isdir(path):
        return f"Error: '{path}' is not a valid directory."

    config = {}
    try:
        if os.path.exists(VAULT_CONFIG_FILE):
            config = json.loads(open(VAULT_CONFIG_FILE).read())
    except Exception:
        pass

    vaults = config.get("memory_vaults", [])
    # Store with ~ for portability
    store_path = path.replace(os.path.expanduser("~"), "~")
    if store_path in vaults or path in vaults:
        return f"Vault already configured: {store_path}"

    vaults.append(store_path)
    config["memory_vaults"] = vaults
    os.makedirs(os.path.dirname(VAULT_CONFIG_FILE), exist_ok=True)
    with open(VAULT_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    return f"Added vault: {store_path}"


def remove_vault_path(path: str) -> str:
    """Remove an external vault/directory path from memory sources."""
    config = {}
    try:
        if os.path.exists(VAULT_CONFIG_FILE):
            config = json.loads(open(VAULT_CONFIG_FILE).read())
    except Exception:
        return "No config found."

    vaults = config.get("memory_vaults", [])
    path_expanded = os.path.expanduser(path)
    store_path = path.replace(os.path.expanduser("~"), "~")

    # Try both forms
    removed = False
    for p in [path, store_path, path_expanded]:
        if p in vaults:
            vaults.remove(p)
            removed = True
            break

    if not removed:
        return f"Vault not found: {path}"

    config["memory_vaults"] = vaults
    with open(VAULT_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    return f"Removed vault: {path}"


def list_vault_paths() -> List[str]:
    """List configured vault paths."""
    return _get_vault_paths()


def rebuild_entity_index() -> str:
    """Re-extract entities from every entry and rewrite entities.json.

    Use this after a change to _extract_entities so legacy junk entities
    (left over from looser extraction rules) drop out of the index.
    """
    if not os.path.exists(ENTRIES_FILE):
        return "No entries file — nothing to rebuild."
    before = len(_load_index())
    new_index: Dict[str, List[str]] = {}
    rebuilt = 0
    rewritten_lines = []
    for line in open(ENTRIES_FILE):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            rewritten_lines.append(line)
            continue
        text = e.get("text", "")
        entities = _extract_entities(text) if text else []
        e["entities"] = entities
        rewritten_lines.append(json.dumps(e))
        for ent in entities:
            new_index.setdefault(ent, []).append(e.get("id", ""))
            if len(new_index[ent]) > 100:
                new_index[ent] = new_index[ent][-100:]
        rebuilt += 1
    with open(ENTRIES_FILE, "w") as f:
        f.write("\n".join(rewritten_lines) + "\n")
    _save_index(new_index)
    after = len(new_index)
    return f"Rebuilt index: {rebuilt} entries scanned, {before} → {after} entities."


# Auto-migrate old format on first import (idempotent — renames files after migration)
_old_days = os.path.join(MEMORY_DIR, "days")
if os.path.exists(_old_days) and os.path.isdir(_old_days):
    try:
        migrate_old_memory()
    except Exception:
        pass
