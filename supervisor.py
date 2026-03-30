"""Supervisor tools — higher-level tools that orchestrate domain agents in parallel.

These give the Strands agent the ability to:
1. Gather data from multiple sources in parallel
2. Maintain conversation context across turns
3. Drill into specific items from previous results
"""

import asyncio
import json
import os
from datetime import datetime
from strands import tool
from envoy_logger import get_logger

# --- Conversation context (persists across turns within a session) ---

_context = {
    "last_emails": [],       # emails from last fetch
    "last_slack": "",        # raw slack from last scan
    "last_calendar": "",     # raw calendar from last view
    "last_todos": "",        # raw todos from last fetch
    "last_report": "",       # last AI-generated report
    "last_people": [],       # people from last lookup
    "last_tickets": "",      # tickets from last scan
}


def get_context() -> dict:
    return _context


def set_context(key: str, value):
    _context[key] = value


@tool
def gather(sources: str = "email,slack,calendar,todos", days: int = 1, alias: str = "") -> str:
    """Fetch data from multiple sources in parallel and return combined context.
    Use this for briefings or when you need a cross-referenced view.

    Args:
        sources: Comma-separated list of: email, slack, calendar, todos, tickets, team, bosses
        days: Number of days to look back
        alias: User alias (defaults to $USER)
    """
    alias = alias or os.getenv("USER", "")
    source_list = [s.strip().lower() for s in sources.split(",")]
    results = asyncio.run(_gather_async(source_list, days, alias))

    # Store in context for follow-up questions
    for key, value in results.items():
        set_context(f"last_{key}", value)

    # Build combined output
    sections = []
    for key, value in results.items():
        if value and not str(value).startswith("Error") and not str(value).startswith("No "):
            sections.append(f"## {key.upper()}\n{value}")

    return "\n\n---\n\n".join(sections) if sections else "No data gathered from any source."


async def _gather_async(sources: list, days: int, alias: str) -> dict:
    """Run data fetches in parallel."""
    from agents import email, slack_agent, calendar, todo, tickets, people

    tasks = {}

    if "email" in sources:
        tasks["emails"] = email.fetch_inbox(days=days, limit=50)
    if "slack" in sources:
        tasks["slack"] = slack_agent.scan_raw(days=days)
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

    results = {}
    gathered = await asyncio.gather(
        *[_named(name, coro) for name, coro in tasks.items()],
        return_exceptions=True
    )
    for name, result in gathered:
        if isinstance(result, Exception):
            results[name] = f"Error: {result}"
        elif isinstance(result, tuple):
            # calendar returns (raw, xref)
            results[name] = result[0]
        elif isinstance(result, list):
            if result and isinstance(result[0], dict):
                # emails or people
                if 'subject' in result[0]:
                    results[name] = "\n".join(
                        f"- {e['from']}: {e['subject']} ({e['date']})" for e in result[:30])
                else:
                    results[name] = "\n".join(
                        f"- {p.get('name', p.get('alias', '?'))} ({p.get('alias', '')})" for p in result)
            else:
                results[name] = str(result)
        else:
            results[name] = str(result) if result else ""

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
    """Read the full content of a specific email thread. Use this to dig deeper into
    an email mentioned in a previous scan or briefing.

    Args:
        conversation_id: The conversation ID from a previous email listing
    """
    from agents.base import outlook as _outlook
    async def _call():
        async with _outlook() as session:
            result = await session.call_tool("email_read", {
                "conversationId": conversation_id, "format": "markdown"
            })
            return str(result.content[0].text) if result.content else "No result."
    result = asyncio.run(_call())
    set_context("last_email_thread", result)
    return result


@tool
def lookup_person(alias: str) -> str:
    """Look up a person's Phonetool profile — role, team, manager, tenure.
    Use this when you need context about someone mentioned in email/Slack/calendar.

    Args:
        alias: Amazon login alias
    """
    import asyncio
    from agents.base import builder

    async def _fetch():
        async with builder() as session:
            result = await session.call_tool(
                "ReadInternalWebsites",
                arguments={"inputs": [f"https://phonetool.amazon.com/users/{alias}"]}
            )
            return str(result.content[0].text) if result.content else f"No profile found for {alias}"

    result = asyncio.run(_fetch())
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
    result = asyncio.run(_call())
    set_context("last_search_results", result)
    return result


@tool
def show_context(key: str = "") -> str:
    """Show what data is currently in the conversation context.
    Use this to check what's available before answering follow-up questions.

    Args:
        key: Specific context key to show (e.g., 'last_emails'). Empty = show all keys with sizes.
    """
    if key:
        val = _context.get(key, "Not found")
        return str(val)[:5000] if val else "Empty"

    summary = []
    for k, v in _context.items():
        if v:
            size = len(str(v))
            preview = str(v)[:100].replace('\n', ' ')
            summary.append(f"- **{k}**: {size} chars — {preview}...")
        else:
            summary.append(f"- **{k}**: empty")
    return "\n".join(summary) if summary else "Context is empty."


# All supervisor tools to add to the agent
SUPERVISOR_TOOLS = [
    gather,
    read_email_thread,
    lookup_person,
    search_emails,
    show_context,
]
