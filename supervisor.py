"""Supervisor tools — higher-level tools that orchestrate domain agents in parallel.

These give the Strands agent the ability to:
1. Gather data from multiple sources in parallel
2. Maintain conversation context across turns
3. Drill into specific items from previous results
"""

import asyncio
import json
import os
import re
import threading
from datetime import datetime
from strands import tool
from envoy_logger import get_logger
from agents.base import run

# --- Conversation context (persists across turns within a session) ---

import time as _time

_context = {
    "items": {},             # ref_id → {type, summary, data, ...}  e.g. "E1" → email dict
    "last_email_bodies": {}, # conversation_id → full thread body (cache)
    "last_report": "",       # last AI-generated report
    "ts": 0,                 # timestamp of last gather
}
_context_lock = threading.RLock()

_CONTEXT_TTL = 1800  # 30 minutes


def _next_ref(prefix: str) -> str:
    """Generate next reference ID like E1, E2, S1, S2, C1..."""
    with _context_lock:
        existing = [k for k in _context["items"] if k.startswith(prefix)]
        return f"{prefix}{len(existing) + 1}"


def _store_item(prefix: str, summary: str, **data) -> str:
    """Store an item in context and return its reference ID."""
    with _context_lock:
        ref = _next_ref(prefix)
        _context["items"][ref] = {"summary": summary, **data}
        return ref


def clear_context():
    """Clear all indexed items and reset timestamp."""
    with _context_lock:
        _context["items"].clear()
        _context["last_email_bodies"].clear()
        _context["last_report"] = ""
        _context["ts"] = 0


def _check_ttl():
    """Clear stale context."""
    with _context_lock:
        if _context["ts"] and (_time.monotonic() - _context["ts"]) > _CONTEXT_TTL:
            clear_context()


def get_context() -> dict:
    _check_ttl()
    return _context


def set_context(key: str, value):
    with _context_lock:
        _context[key] = value


@tool
def gather(sources: str = "email,slack,calendar,todos", days: int = 1, alias: str = "") -> str:
    """Fetch data from multiple sources in parallel and return combined context with reference IDs.
    Each item gets a ref like [E1], [S1], [C1] that the user can reference in follow-ups.

    Args:
        sources: Comma-separated list of: email, slack, calendar, todos, tickets, team, bosses, vault
        days: Number of days to look back
        alias: User alias (defaults to $USER)
    """
    return gather_data(sources, days, alias)


def gather_data(sources: str = "email,slack,calendar,todos", days: int = 1, alias: str = "") -> str:
    """Core gather logic — callable by both the @tool and workflows directly."""
    alias = alias or os.getenv("USER", "")
    source_list = [s.strip().lower() for s in sources.split(",")]

    # Only wipe stale context; preserve refs from recent gathers in same session
    with _context_lock:
        if _context["ts"] and (_time.monotonic() - _context["ts"]) > _CONTEXT_TTL:
            clear_context()
        elif _context["items"]:
            # Subsequent gather in same session — clear only refs for sources
            # we're about to re-fetch, so we don't get stale duplicates
            prefix_map = {"email": "E", "slack": "S", "calendar": "C",
                          "todos": "T", "tickets": "K", "team": "P", "bosses": "P",
                          "vault": "V"}
            for src in source_list:
                pfx = prefix_map.get(src)
                if pfx:
                    stale = [k for k in _context["items"] if k.startswith(pfx)]
                    for k in stale:
                        del _context["items"][k]
        _context["ts"] = _time.monotonic()

    results = run(_gather_async(source_list, days, alias))

    # Build combined output with reference IDs
    sections = []
    for key, value in results.items():
        if value and not str(value).startswith("Error") and not str(value).startswith("⚠️"):
            header = key.upper()
            if key == "slack":
                header = "SLACK (format: [ref] [channel/DM (sender)] (time) sender: message)"
            elif key == "vault":
                header = "VAULT (personal knowledge base — wiki pages and recent log entries)"
            sections.append(f"## {header}\n{value}")

    # Cross-reference: find entities that appear in multiple sources
    xref = _cross_reference(results)
    if xref:
        sections.append(f"## CROSS-REFERENCES\n{xref}")

    output = "\n\n---\n\n".join(sections) if sections else "No data gathered from any source."
    _context["last_report"] = output
    return output


def _cross_reference(results: dict) -> str:
    """Find people, projects, and topics that appear across multiple sources."""
    from agents.memory2 import _extract_entities

    # Extract entities per source
    source_entities = {}
    for source, data in results.items():
        text = str(data) if data else ""
        if not text or text.startswith("Error") or text.startswith("⚠️"):
            continue
        entities = _extract_entities(text)
        if entities:
            source_entities[source] = set(entities)

    if len(source_entities) < 2:
        return ""

    # Find entities appearing in 2+ sources
    all_sources = list(source_entities.keys())
    overlaps = {}
    for entity in set().union(*source_entities.values()):
        appearing_in = [s for s in all_sources if entity in source_entities[s]]
        if len(appearing_in) >= 2:
            key = entity
            overlaps[key] = appearing_in

    if not overlaps:
        return ""

    # Format: group by entity, show which sources mention it
    lines = []
    # Sort by number of sources (most connected first), cap at 15
    for entity, sources in sorted(overlaps.items(), key=lambda x: -len(x[1]))[:15]:
        source_names = " + ".join(sources)
        lines.append(f"- **{entity}** → mentioned in {source_names}")

    return "These people/topics appear across multiple sources — likely connected threads:\n" + "\n".join(lines)


async def _fetch_vault() -> str:
    """Read wiki/index.md and wiki/log.md from the configured Knowledge Folder."""
    from agents.export import _configured_folders
    folder = _configured_folders().get("knowledge", "")
    if not folder:
        return ""
    from agents import sharepoint_agent as sp
    parts = []
    for page in ("wiki/index.md", "wiki/log.md"):
        try:
            text = await sp.read_file(f"/personal/{os.getenv('USER', '')}_amazon_com/Documents/{folder}/{page}", inline=True)
            if text and not text.startswith("Error") and not text.startswith("Could not"):
                parts.append(f"### {page}\n{text[:3000]}")
        except Exception:
            pass
    return "\n\n".join(parts) if parts else ""


async def _gather_async(sources: list, days: int, alias: str) -> dict:
    """Run data fetches in parallel."""
    from agents import email, slack_agent, calendar, todo, tickets, people

    tasks = {}

    if "email" in sources:
        tasks["emails"] = email.fetch_inbox(days=days, limit=50)
    if "slack" in sources:
        tasks["slack"] = slack_agent.scan_raw(days=days, alias=alias)
    if "calendar" in sources:
        tasks["calendar"] = _wrap(calendar.get_events_raw(view="day" if days <= 1 else "week", days_ahead=days))
    if "todos" in sources:
        tasks["todos"] = todo.fetch_todos_full()
    if "tickets" in sources:
        tasks["tickets"] = tickets.scan_tickets(alias)
    if "team" in sources:
        tasks["people"] = people.get_direct_reports(alias)
    if "bosses" in sources:
        tasks["people"] = people.get_management_chain(alias)
    if "vault" in sources:
        tasks["vault"] = _fetch_vault()

    results = {}
    gathered = await asyncio.gather(
        *[_named(name, coro) for name, coro in tasks.items()],
        return_exceptions=True
    )
    for name, result in gathered:
        if isinstance(result, Exception):
            results[name] = f"⚠️ {name} unavailable: {result}"
        elif isinstance(result, tuple):
            # calendar returns (raw, xref)
            raw_cal = result[0] if result[0] else ""
            lines = []
            for line in str(raw_cal).splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "<", "IMPORTANT")):
                    if line.startswith("#"):
                        lines.append(line)
                    continue
                if any(skip in line for skip in ("untrusted_content", "success", "error")):
                    continue
                ref = _store_item("C", line[:200], type="calendar", raw=line)
                lines.append(f"[{ref}] {line}")
            results[name] = "\n".join(lines) if lines else str(raw_cal)
        elif isinstance(result, list):
            if result and isinstance(result[0], dict):
                if 'subject' in result[0]:
                    # Emails — index each one
                    lines = []
                    for e in result[:30]:
                        ref = _store_item("E", f"{e['from']}: {e['subject']}",
                                          type="email",
                                          conversationId=e.get('conversationId', ''),
                                          **{k: e.get(k, '') for k in ('from', 'subject', 'date', 'preview')})
                        lines.append(f"[{ref}] {e['from']}: {e['subject']} ({e['date']})")
                    results[name] = "\n".join(lines)
                else:
                    # People
                    results[name] = "\n".join(
                        f"- {p.get('name', p.get('alias', '?'))} ({p.get('alias', '')})" for p in result)
            else:
                results[name] = str(result)
        else:
            text = str(result) if result else ""
            # Index Slack messages and todos
            if name == "slack" and text:
                lines = []
                for line in text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("    ↳"):
                        # Thread reply — attach to previous message, don't index separately
                        lines.append(line)
                        continue
                    if "[" in line or line.startswith("🔴") or line.startswith("🟡"):
                        # Extract sender name from format: [prefix] (ts) Name: text
                        sender = ""
                        m = re.search(r'\)\s+(.+?)(?:\s+\[you\]|\s+⚡@you)?:\s', line)
                        if m:
                            sender = m.group(1)
                        ref = _store_item("S", line[:300], type="slack", raw=line, sender=sender)
                        lines.append(f"[{ref}] {line}")
                    else:
                        lines.append(line)
                results[name] = "\n".join(lines)
            elif name == "todos" and text:
                lines = []
                for line in text.splitlines():
                    line = line.strip()
                    if line and line.startswith(("- ", "* ", "☐", "☑", "✅")):
                        ref = _store_item("T", line[:200], type="todo", raw=line)
                        lines.append(f"[{ref}] {line}")
                    elif line:
                        lines.append(line)
                results[name] = "\n".join(lines)
            elif name == "tickets" and text:
                lines = []
                for line in text.splitlines():
                    line = line.strip()
                    if line and line.startswith("- "):
                        ref = _store_item("K", line[:200], type="ticket", raw=line)
                        lines.append(f"[{ref}] {line}")
                    elif line:
                        lines.append(line)
                results[name] = "\n".join(lines)
            elif name == "vault" and text:
                lines = []
                for line in text.splitlines():
                    line = line.strip()
                    if line and (line.startswith("- ") or line.startswith("[[") or "]]" in line):
                        ref = _store_item("V", line[:300], type="vault", raw=line)
                        lines.append(f"[{ref}] {line}")
                    elif line:
                        lines.append(line)
                results[name] = "\n".join(lines)
            else:
                results[name] = text

    return results


async def _named(name, coro):
    """Wrap a coroutine to return (name, result)."""
    try:
        result = await coro
        return (name, result)
    except Exception as e:
        return (name, e)


async def _wrap(coro):
    """Passthrough wrapper for coroutines."""
    return await coro


@tool
def read_email_thread(conversation_id: str) -> str:
    """Read the full content of a specific email thread.

    Args:
        conversation_id: The conversation ID, or a reference ID like E1
    """
    _check_ttl()
    # Check if it's a reference ID
    if conversation_id.upper() in _context["items"]:
        item = _context["items"][conversation_id.upper()]
        if item.get("conversationId"):
            conversation_id = item["conversationId"]

    # Return cached body if we already fetched it
    cached = _context.get("last_email_bodies", {}).get(conversation_id)
    if cached:
        return cached

    from agents.base import outlook as _outlook
    async def _call():
        async with _outlook() as session:
            result = await session.call_tool("email_read", {
                "conversationId": conversation_id, "format": "markdown"
            })
            return str(result.content[0].text) if result.content else "No result."
    result = run(_call())
    bodies = _context.get("last_email_bodies", {})
    bodies[conversation_id] = result
    if len(bodies) > 50:
        del bodies[list(bodies.keys())[0]]
    _context["last_email_bodies"] = bodies
    return result


@tool
def lookup_person(alias: str) -> str:
    """Look up a person's Phonetool profile — role, team, manager, tenure.
    Use this when you need context about someone mentioned in email/Slack/calendar.

    Args:
        alias: Amazon login alias
    """
    from agents.base import builder

    async def _fetch():
        async with builder() as session:
            result = await session.call_tool(
                "ReadInternalWebsites",
                arguments={"inputs": [f"https://phonetool.amazon.com/users/{alias}"]}
            )
            return str(result.content[0].text) if result.content else f"No profile found for {alias}"

    result = run(_fetch())
    set_context("last_person_lookup", result)
    return result


@tool
def search_emails(query: str, days: int = 14) -> str:
    """Search emails with a specific query. More targeted than the general inbox fetch.
    Use this to find emails about a specific topic, from a specific person, or related
    to something mentioned in conversation.

    Args:
        query: Search query (e.g., "from:alice@amazon.com project deadline")
        days: Days to look back
    """
    from agents.base import outlook as _outlook
    from datetime import timedelta
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    async def _call():
        async with _outlook() as session:
            result = await session.call_tool("email_search", {
                "query": query, "startDate": start_date, "endDate": end_date, "limit": 25
            })
            return str(result.content[0].text) if result.content else "No results."
    result = run(_call())
    set_context("last_search_results", result)
    return result


@tool
def get_attachment(item_id: str, filename: str = "") -> str:
    """Download and preview an email attachment. Use when the user asks about
    a file attached to an email. Get the item_id from reading the email thread first.

    Args:
        item_id: The attachment ID or email item ID
        filename: Optional filename hint for context
    """
    from agents.base import outlook as _outlook
    async def _call():
        async with _outlook() as session:
            result = await session.call_tool("email_attachments", {"attachmentId": item_id})
            return str(result.content[0].text) if result.content else "No attachment data."
    result = run(_call())
    set_context("last_attachment", result)
    return result


@tool
def drill_down(ref: str) -> str:
    """Get full details for a referenced item from the last gather.
    For emails, automatically fetches the full thread body.

    Args:
        ref: Reference ID like E1, S3, C2, T1, K1
    """
    _check_ttl()
    ref = ref.upper().strip()
    item = _context["items"].get(ref)
    if not item:
        return f"Reference {ref} not found in context. Available: {', '.join(sorted(_context['items'].keys())) or 'none'}"

    # For emails, fetch full thread body
    if item.get("type") == "email" and item.get("conversationId"):
        conv_id = item["conversationId"]
        # Check cache first
        cached = _context.get("last_email_bodies", {}).get(conv_id)
        if cached:
            return f"**[{ref}] {item['summary']}**\n\n{cached}"
        # Fetch full thread
        from agents.base import outlook as _outlook
        async def _call():
            async with _outlook() as session:
                result = await session.call_tool("email_read", {
                    "conversationId": conv_id, "format": "markdown"
                })
                return str(result.content[0].text) if result.content else "No result."
        body = run(_call())
        bodies = _context.get("last_email_bodies", {})
        bodies[conv_id] = body
        if len(bodies) > 50:
            del bodies[list(bodies.keys())[0]]
        _context["last_email_bodies"] = bodies
        return f"**[{ref}] {item['summary']}**\n\n{body}"

    # For everything else, return stored data
    return f"**[{ref}]** {item.get('summary', '')}\n\n{item.get('raw', json.dumps(item, indent=2, default=str))}"


@tool
def show_context(key: str = "") -> str:
    """Show what data is currently in the conversation context.
    Use this to check what's available before answering follow-up questions.

    Args:
        key: Specific ref ID (e.g., 'E1') or empty to show all indexed items.
    """
    _check_ttl()
    if key:
        # Try as ref ID first
        item = _context["items"].get(key.upper())
        if item:
            return f"**[{key.upper()}]** {item.get('summary', '')}\nType: {item.get('type', '?')}"
        return f"Reference {key} not found."

    items = _context["items"]
    if not items:
        return "Context is empty. Use `gather` to fetch data first."

    # Group by type
    by_type = {}
    for ref, item in sorted(items.items()):
        t = item.get("type", "other")
        by_type.setdefault(t, []).append((ref, item.get("summary", "")[:100]))

    lines = [f"**{len(items)} items in context**\n"]
    for t, entries in by_type.items():
        lines.append(f"### {t.title()} ({len(entries)})")
        for ref, summary in entries:
            lines.append(f"  [{ref}] {summary}")
    lines.append(f"\nUse `drill_down('E1')` to get full details for any item.")
    return "\n".join(lines)


# All supervisor tools to add to the agent
SUPERVISOR_TOOLS = [
    gather,
    drill_down,
    read_email_thread,
    get_attachment,
    lookup_person,
    search_emails,
    show_context,
]
