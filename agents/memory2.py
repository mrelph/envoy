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

# Words that look like entities (capitalized) but aren't people/projects
_ENTITY_STOPWORDS = frozenset({
    # Determiners, prepositions, conjunctions
    'the', 'this', 'that', 'these', 'those', 'from', 'with', 'about', 'into',
    'after', 'before', 'between', 'through', 'during', 'without', 'within',
    'also', 'just', 'only', 'some', 'each', 'every', 'both', 'either',
    # Common verbs (often start sentences in notes)
    'reply', 'send', 'sent', 'check', 'update', 'updated', 'follow', 'review',
    'reviewed', 'added', 'removed', 'created', 'deleted', 'moved', 'fixed',
    'done', 'completed', 'cancelled', 'scheduled', 'shared', 'forwarded',
    'replied', 'asked', 'told', 'said', 'noted', 'mentioned', 'discussed',
    'approved', 'rejected', 'assigned', 'resolved', 'closed', 'opened',
    'flagged', 'marked', 'scanned', 'fetched', 'searched', 'found',
    'need', 'needs', 'should', 'could', 'would', 'will', 'can', 'may',
    'keep', 'skip', 'ignore', 'decline', 'accept', 'confirm', 'cancel',
    # Common nouns in agent context
    'email', 'emails', 'slack', 'meeting', 'meetings', 'calendar', 'inbox',
    'action', 'actions', 'todo', 'todos', 'ticket', 'tickets', 'digest',
    'report', 'briefing', 'summary', 'response', 'message', 'messages',
    'thread', 'channel', 'channels', 'draft', 'drafts', 'attachment',
    'subject', 'body', 'sender', 'recipient', 'reply', 'forward',
    'priority', 'urgent', 'important', 'critical', 'blocked', 'pending',
    'status', 'progress', 'deadline', 'milestone', 'goal', 'project',
    'team', 'manager', 'direct', 'reports', 'customer', 'customers',
    'error', 'warning', 'success', 'failed', 'unavailable', 'available',
    'worker', 'agent', 'envoy', 'heartbeat', 'routine', 'pattern',
    'observation', 'context', 'memory', 'process', 'config', 'settings',
    # Days and months
    'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
    'today', 'tomorrow', 'yesterday', 'week', 'month', 'year',
    # Tech/Amazon terms
    'amazon', 'aws', 'sim', 'phonetool', 'kingpin', 'wiki', 'taskei',
    'sharepoint', 'onedrive', 'outlook', 'teams', 'zoom', 'chime',
    'jira', 'quip', 'broadcast', 'cron', 'api', 'mcp', 'bedrock',
})


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
            # Skip common non-name words — verbs, nouns, adjectives, time, tech terms
            if clean.lower() not in _ENTITY_STOPWORDS:
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
    entries = _load_entries(days=KEEP_DAYS)
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
        # Fallback: search the vault (Knowledge Folder) if configured
        vault_result = _search_vault(query)
        if vault_result:
            return f"## Memory: {query}\n\n*(from vault)*\n{vault_result}"
        return f"No memory entries found for '{query}'."

    return f"## Memory: {query}\n\n" + "\n".join(parts)


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
    """Compress old entries into per-entity rolling summaries."""
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
        return f"Compression failed — kept all {len(old_entries) + len(recent)} entries intact."

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


def _search_vault(query: str) -> str:
    """Search the Knowledge Folder vault for a query. Returns matching content or ''."""
    try:
        from agents.export import _configured_folders
        folder = _configured_folders().get("knowledge", "")
        if not folder:
            return ""
        from agents.base import run
        from agents import sharepoint_agent as sp
        result = run(sp.search(f"{query} path:\"{folder}/wiki\"", row_limit=5))
        if result and not result.startswith("No results") and not result.startswith("Error"):
            return result[:3000]
    except Exception:
        pass
    return ""


# Auto-migrate old format on first import (idempotent — renames files after migration)
_old_days = os.path.join(MEMORY_DIR, "days")
if os.path.exists(_old_days) and os.path.isdir(_old_days):
    try:
        migrate_old_memory()
    except Exception:
        pass
