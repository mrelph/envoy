"""Team health dashboard — per-direct-report rollup across email and Slack.

For each direct report (via Phonetool), gathers in parallel:
  - email sent count   (Outlook email_search from:{alias})
  - email received count (Outlook email_search to:{alias})
  - Slack recency      (slack-mcp search from:@{alias})

Calendar/meeting load needs shared-calendar access we don't have — reported
as "unavail" (see TEAM-HEALTH-SPEC.md). All failures degrade gracefully.
"""

import asyncio
from datetime import datetime, timedelta

from agents.base import invoke_ai, run, parse_email_search_result
from agents.base import current_user as _USER

_CONCURRENCY = 8       # bounded parallelism across all per-person MCP calls
_FETCH_TIMEOUT = 25    # seconds per signal fetch — fail fast, don't stall the gather
_MAX_DIRECTS = 15      # bound total call volume for large orgs


async def _fetch_email_count(sem, direction: str, p_alias: str, start: str, end: str):
    """Count emails sent by (from:) or received by (to:) p_alias. None = unavailable."""
    from agents.base import outlook
    async with sem:
        try:
            async with outlook() as s:
                result = await asyncio.wait_for(
                    s.call_tool("email_search", arguments={
                        "query": f"{direction}:{p_alias}@amazon.com",
                        "startDate": start, "endDate": end, "limit": 100,
                    }),
                    timeout=_FETCH_TIMEOUT,
                )
                return len(parse_email_search_result(result))
        except Exception:
            return None


async def _fetch_slack_recency(sem, p_alias: str):
    """Recent Slack messages from p_alias — raw search text with timestamps. None = unavailable."""
    from agents.base import slack
    async with sem:
        try:
            async with slack() as s:
                result = await asyncio.wait_for(
                    s.call_tool("search", arguments={"query": f"from:@{p_alias}"}),
                    timeout=_FETCH_TIMEOUT,
                )
                raw = str(result.content[0].text) if result.content else ""
                return raw[:1500] or None
        except Exception:
            return None


async def _gather_person(person: dict, days: int, sem) -> dict:
    p_alias = person.get("alias", "")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    sent, received, slack_raw = await asyncio.gather(
        _fetch_email_count(sem, "from", p_alias, start, end),
        _fetch_email_count(sem, "to", p_alias, start, end),
        _fetch_slack_recency(sem, p_alias),
    )
    return {
        "alias": p_alias,
        "name": person.get("name", p_alias),
        "email_sent": sent,
        "email_received": received,
        "slack": slack_raw,
    }


async def _gather(alias: str, days: int) -> dict:
    from agents.people import get_direct_reports
    try:
        directs = await asyncio.wait_for(get_direct_reports(alias), timeout=30)
    except asyncio.TimeoutError:
        return {"manager": alias, "people": [], "error": "Phonetool lookup timed out after 30s"}
    except Exception as e:
        return {"manager": alias, "people": [], "error": str(e)}
    if not directs:
        return {"manager": alias, "people": []}
    sem = asyncio.Semaphore(_CONCURRENCY)
    people = await asyncio.gather(
        *[_gather_person(p, days, sem) for p in directs[:_MAX_DIRECTS]]
    )
    return {"manager": alias, "people": list(people)}


def _person_block(p: dict) -> str:
    """Compact text block for one person, feeding the synthesis prompt."""
    def _num(v):
        return "unavail" if v is None else str(v)
    lines = [
        f"### {p['name']} ({p['alias']})",
        f"- Emails sent: {_num(p['email_sent'])}",
        f"- Emails received: {_num(p['email_received'])}",
        f"- Recent Slack activity: {p['slack'] or 'unavail'}",
    ]
    return "\n".join(lines)


def synthesize(data: dict, days: int) -> str:
    """Turn raw per-person numbers into the formatted dashboard via AI."""
    manager = data.get("manager", "")
    blocks = "\n\n".join(_person_block(p) for p in data.get("people", []))
    prompt = f"""You are building a team health dashboard for {manager}'s direct reports over the last {days} days.

Raw per-person data is below. Slack data is raw search results —
use message timestamps to judge recency; silent for 3+ days = flag. Low email sent volume
(vs. peers) = possibly blocked, disengaged, or on PTO. Meeting load data is unavailable —
show "unavail" in that column. "unavail" for any signal means the data source failed; do not
treat it as zero or as a problem with the person.

Format exactly like this:

## Team Health — {manager}'s directs ({days} days)

| Name | 📧 Sent | 📧 Recv | 📅 Mtg% | ⚠️ Flags |
|------|---------|---------|---------|----------|
(one row per person; flags like "📧 low send volume", "💬 slack silent")

### 🔴 Needs Attention
(bullet per person with a concern — cite specifics like day counts and volume numbers)

### 🟢 Looking Good
(bullet per person with healthy signals)

Data:
{blocks[:12000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"# Team Health\n\n**Error synthesizing report:** {e}\n\nRaw data:\n\n{blocks[:3000]}"


def team_health(alias: str = None, days: int = 7) -> str:
    """Team health dashboard for a manager's direct reports."""
    alias = alias or _USER()
    try:
        data = run(_gather(alias, days))
    except Exception as e:
        return f"Error gathering team health data: {e}"
    if data.get("error"):
        return f"⚠️ Team health failed: {data['error']}"
    if not data.get("people"):
        return (f"No direct reports found for {alias} — check the Phonetool MCP "
                f"connection (/doctor) or pass a manager alias.")
    return synthesize(data, days)
