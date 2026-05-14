"""Shared data-fetch functions — single source of truth for both gather and workers.

Both the supervisor's gather() and the worker tools call these functions.
This eliminates the dual-path problem where changes to one path don't
propagate to the other.
"""

from datetime import datetime


async def fetch_calendar(days: int = 1, start_date: str = "") -> tuple:
    """Fetch raw calendar events. Returns (text, xref_context).
    
    This is THE function both gather and calendar_worker use.
    """
    from agents.calendar import get_events_raw
    view = "week" if days > 1 else "day"
    return await get_events_raw(view=view, start_date=start_date, days_ahead=days)


async def fetch_emails(days: int = 1, limit: int = 50) -> list:
    """Fetch inbox emails. Returns list of email dicts."""
    from agents.email import fetch_inbox
    return await fetch_inbox(days=days, limit=limit)


async def fetch_slack(days: int = 7, alias: str = "") -> str:
    """Fetch Slack messages. Returns formatted text."""
    from agents.slack_agent import scan_raw
    return await scan_raw(days=days, alias=alias)


async def fetch_todos() -> str:
    """Fetch to-do items. Returns formatted text."""
    from agents.todo import fetch_todos_full
    return await fetch_todos_full()


async def fetch_tickets(alias: str = "") -> str:
    """Fetch open tickets. Returns formatted text."""
    from agents.tickets import scan_tickets
    return await scan_tickets(alias)


async def fetch_people(alias: str = "", mode: str = "team") -> list:
    """Fetch people (directs or bosses). Returns list of person dicts."""
    from agents.people import get_direct_reports, get_management_chain
    if mode == "bosses":
        return await get_management_chain(alias)
    return await get_direct_reports(alias)
