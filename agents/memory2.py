"""Unified memory system — structured entries with entity indexing and topic recall.

Merges the old memory + observer into one system. Every entry is tagged with
entities (people, projects, topics) for fast retrieval. Compression preserves
per-entity threads instead of flattening everything into one paragraph.

Storage:
    ~/.envoy/memory/entries.jsonl   — append-only log of all entries
    ~/.envoy/memory/entities.json   — entity → entry ID index
    ~/.envoy/memory/summary.json    — rolling compressed summary
"""

import json
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from agents.base import invoke_ai

MEMORY_DIR = os.path.expanduser("~/.envoy/memory")
ENTRIES_FILE = os.path.join(MEMORY_DIR, "entries.jsonl")
ENTITIES_FILE = os.path.join(MEMORY_DIR, "entities.json")
SUMMARY_FILE = os.path.join(MEMORY_DIR, "summary.json")

# Limits
MAX_ENTRY_LEN = 500
MAX_ENTRIES = 2000       # prune oldest beyond this
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB hard limit per file
SUMMARY_MAX = 3000
RECALL_DEFAULT = 20      # entries returned by default
KEEP_DAYS = 14           # full entries kept
COMPRESS_AFTER_DAYS = 7  # compress into summary after this


def _ensure_dir():
    os.makedirs(MEMORY_DIR, exist_ok=True)


# --- Entity extraction (no AI, just pattern matching) ---

# Common Amazon alias pattern
_ALIAS_RE = re.compile(r'\b([a-z]{2,12})@amazon\.com\b|@([a-z]{2,12})\b')
# Project/topic patterns — capitalized multi-word or known prefixes
_PROJECT_RE = re.compile(r'\b(KP-\d+|SIM-\d+|[A-Z][a-z]+-\d+)\b')
_TOPIC_RE = re.compile(r'\b(Q[1-4]\s*\d{4}|Q[1-4]\b|[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)+)\b')


def _extract_entities(text: str) -> List[str]:
    """Extract people, project IDs, and topics from text. Fast, no AI."""
    entities = set()
    # Aliases
    for m in _ALIAS_RE.finditer(text.lower()):
        alias = m.group(1) or m.group(2)
        if alias and len(alias) > 2:
            entities.add(alias)
    # Project IDs
    for m in _PROJECT_RE.finditer(text):
        entities.add(m.group(1).lower())
    # Mentioned names (simple: capitalized words that aren't sentence starters)
    words = text.split()
    for i, w in enumerate(words):
        clean = w.strip('.,!?:;()[]"\'')
        if clean and clean[0].isupper() and len(clean) > 2 and i > 0:
            # Skip common non-name words
            if clean.lower() not in ('the', 'this', 'that', 'from', 'with', 'about',
                                      'email', 'slack', 'meeting', 'monday', 'tuesday',
                                      'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
                                      'january', 'february', 'march', 'april', 'may', 'june',
                                      'july', 'august', 'september', 'october', 'november', 'december',
                                      'action', 'todo', 'inbox', 'calendar', 'digest', 'report'):
                entities.add(clean.lower())
    return sorted(entities)


# --- Core operations ---

def remember(text: str, entry_type: str = "action") -> str:
    """Store an entry with auto-extracted entities.

    Args:
        text: What to remember
        entry_type: action, context, decision, observation, preference
    """
    _ensure_dir()
    entities = _extract_entities(text)
    entry_id = datetime.now().strftime("%Y%m%d%H%M%S%f")[:18]
    entry = {
        "id": entry_id,
        "ts": datetime.now().isoformat(),
        "type": entry_type,
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
    """General recall: today's entries + rolling summary."""
    sections = []

    # Rolling summary
    if os.path.exists(SUMMARY_FILE):
        try:
            data = json.loads(open(SUMMARY_FILE).read())
            if data.get("text"):
                sections.append(f"### Patterns & Context\n{data['text']}")
        except Exception:
            pass

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
        # Other days
        for label, entries_list in grouped.items():
            if label not in ("Today", "Yesterday"):
                lines = [f"- {e['ts'][11:16]} [{e['type']}] {e['text']}" for e in entries_list]
                sections.append(f"### {label}\n" + "\n".join(lines))

    if not sections:
        return ""
    return "## Memory\n\n" + "\n\n".join(sections)


def _recall_by_query(query: str, limit: int) -> str:
    """Recall entries matching a query — checks entities and text."""
    query_lower = query.lower().strip()
    entries = _load_entries(days=KEEP_DAYS)

    # Score entries by relevance
    scored = []
    for e in entries:
        score = 0
        # Exact entity match
        if query_lower in e.get("entities", []):
            score += 10
        # Partial entity match
        for ent in e.get("entities", []):
            if query_lower in ent or ent in query_lower:
                score += 5
        # Text match
        if query_lower in e.get("text", "").lower():
            score += 3
        if score > 0:
            scored.append((score, e))

    scored.sort(key=lambda x: (-x[0], x[1]["ts"]), reverse=False)
    scored.sort(key=lambda x: -x[0])
    matches = [e for _, e in scored[:limit]]

    if not matches:
        return f"No memory entries found for '{query}'."

    lines = [f"- {e['ts'][:16]} [{e['type']}] {e['text']}" for e in matches]
    entities_found = set()
    for e in matches:
        entities_found.update(e.get("entities", []))

    return (f"## Memory: {query}\n\n"
            f"**{len(matches)} entries** | Related: {', '.join(sorted(entities_found)[:10])}\n\n"
            + "\n".join(lines))


# --- Entity index ---

def _load_index() -> Dict[str, List[str]]:
    if os.path.exists(ENTITIES_FILE):
        try:
            return json.loads(open(ENTITIES_FILE).read())
        except Exception:
            pass
    return {}


def _save_index(index: dict):
    with open(ENTITIES_FILE, "w") as f:
        json.dump(index, f)


def _index_entry(entry_id: str, entities: List[str]):
    index = _load_index()
    for entity in entities:
        if entity not in index:
            index[entity] = []
        index[entity].append(entry_id)
        # Cap per entity
        if len(index[entity]) > 100:
            index[entity] = index[entity][-100:]
    _save_index(index)


def known_entities() -> List[str]:
    """Return all known entities sorted by frequency."""
    index = _load_index()
    return sorted(index.keys(), key=lambda k: -len(index[k]))


# --- Entry loading ---

def _load_entries(days: int = KEEP_DAYS) -> list:
    if not os.path.exists(ENTRIES_FILE):
        return []
    cutoff = datetime.now() - timedelta(days=days)
    entries = []
    for line in open(ENTRIES_FILE):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if datetime.fromisoformat(e["ts"]) >= cutoff:
                entries.append(e)
        except Exception:
            pass
    return entries


# --- Compression ---

def compress(force: bool = False) -> str:
    """Compress old entries into the rolling summary. Runs automatically but can be forced."""
    _ensure_dir()
    cutoff = datetime.now() - timedelta(days=COMPRESS_AFTER_DAYS)
    all_entries = []
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
                all_entries.append(e)
            else:
                recent.append(e)
        except Exception:
            recent.append({"text": line})  # keep unparseable lines

    if not all_entries and not force:
        return "Nothing old enough to compress."

    # Build per-entity summaries for compression
    entity_threads = {}
    general = []
    for e in all_entries:
        entities = e.get("entities", [])
        if entities:
            for ent in entities:
                entity_threads.setdefault(ent, []).append(e)
        else:
            general.append(e)

    # Format for AI compression
    sections = []
    for ent, entries in sorted(entity_threads.items(), key=lambda x: -len(x[1]))[:20]:
        lines = [f"  - {e['ts'][:10]} [{e['type']}] {e['text']}" for e in entries[-5:]]
        sections.append(f"**{ent}** ({len(entries)} entries):\n" + "\n".join(lines))
    if general:
        lines = [f"  - {e['ts'][:10]} [{e['type']}] {e['text']}" for e in general[-10:]]
        sections.append(f"**general** ({len(general)} entries):\n" + "\n".join(lines))

    existing = ""
    if os.path.exists(SUMMARY_FILE):
        try:
            existing = json.loads(open(SUMMARY_FILE).read()).get("text", "")
        except Exception:
            pass

    try:
        summary = invoke_ai(
            f"Update this rolling memory summary. Organize by entity/person/project. "
            f"For each, keep: latest status, key decisions, unresolved items, user preferences. "
            f"Drop stale items with no recent activity. Max 2500 chars, dense, structured.\n\n"
            f"Existing summary:\n{existing or '(none)'}\n\n"
            f"New entries to fold in:\n" + "\n\n".join(sections),
            max_tokens=1200, tier="memory"
        )
    except Exception:
        summary = existing

    with open(SUMMARY_FILE, "w") as f:
        json.dump({"updated": datetime.now().isoformat(), "text": summary[:SUMMARY_MAX]}, f)

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

    return f"Compressed {len(all_entries)} old entries into summary. {len(recent)} recent entries kept."


# --- Pruning ---

def _prune_if_needed():
    """Prune if entries file is too large (by count or file size)."""
    if not os.path.exists(ENTRIES_FILE):
        return
    try:
        size = os.path.getsize(ENTRIES_FILE)
        lines = open(ENTRIES_FILE).readlines()
        if len(lines) > MAX_ENTRIES or size > MAX_FILE_SIZE:
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


# Auto-migrate old format on first import (idempotent — renames files after migration)
_old_days = os.path.join(MEMORY_DIR, "days")
if os.path.exists(_old_days) and os.path.isdir(_old_days):
    try:
        migrate_old_memory()
    except Exception:
        pass
