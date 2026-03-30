"""Tickets agent — scan and summarize open tickets."""

import json
import os

from agents.base import builder, invoke_ai


async def scan_tickets(alias: str = "") -> str:
    alias = alias or os.getenv("USER", "")
    try:
        async with builder() as session:
            result = await session.call_tool("TicketingReadActions", arguments={
                "action": "search-tickets",
                "input": {
                    "status": ["Assigned", "Researching", "Work In Progress"],
                    "sort": "lastUpdatedDate desc",
                    "rows": 20,
                    "responseFields": ["id", "title", "status", "extensions.tt.assignedGroup",
                                       "extensions.tt.impact", "createDate", "lastUpdatedDate"]
                }
            })
            raw = str(result.content[0].text) if result.content else "No tickets found."
            if len(raw) < 50:
                return raw
            prompt = f"""Summarize these open tickets for {alias}. Group by severity/impact.
Flag anything sev-2 or higher. Note stale tickets (no update in 7+ days).
Format as a brief report with action items.

Tickets:
{raw[:8000]}"""
            return invoke_ai(prompt, max_tokens=6000, tier="light")
    except Exception as e:
        return f"Error scanning tickets: {e}"
