"""Patrol agent — autonomous chief of staff that wakes on cron.

Reads standing orders (user-requested + learned), checks each using
existing tools, deduplicates against recent alerts, and notifies via Slack DM.
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from agents.base import invoke_ai, outlook, MCPConnectionError
from agents import email, slack_agent, calendar, todo, tickets, people, memory2 as memory

_USER = os.getenv("USER", "")
_ENVOY_DIR = Path.home() / ".envoy"
_ORDERS_FILE = _ENVOY_DIR / "standing_orders.md"
_STATE_FILE = _ENVOY_DIR / "patrol_state.json"
_MAX_ALERTS_PER_RUN = 10


# --- Standing orders ---

def _ensure_files():
    _ENVOY_DIR.mkdir(parents=True, exist_ok=True)
    if not _ORDERS_FILE.exists():
        _ORDERS_FILE.write_text("# Standing Orders\n\n## User-requested\n\n## Learned\n")


def get_standing_orders() -> str:
    _ensure_files()
    return _ORDERS_FILE.read_text()


def add_order(instruction: str, learned: bool = False) -> str:
    _ensure_files()
    content = _ORDERS_FILE.read_text()
    section = "## Learned" if learned else "## User-requested"
    entry = f"- {instruction}"
    if section in content:
        content = content.replace(section, f"{section}\n{entry}", 1)
    else:
        content = content.rstrip() + f"\n\n{section}\n{entry}\n"
    _ORDERS_FILE.write_text(content)
    return f"Added standing order: {instruction}"


def remove_order(instruction_fragment: str) -> str:
    _ensure_files()
    lines = _ORDERS_FILE.read_text().splitlines()
    new_lines = [l for l in lines if instruction_fragment.lower() not in l.lower()]
    if len(new_lines) == len(lines):
        return f"No matching order found for: {instruction_fragment}"
    _ORDERS_FILE.write_text("\n".join(new_lines) + "\n")
    return f"Removed order matching: {instruction_fragment}"


# --- Patrol state (dedup) ---

def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_run": None, "recent_alerts": []}


def _save_state(state: dict):
    _ENVOY_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def _prune_old_alerts(state: dict, hours: int = 24) -> dict:
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    state["recent_alerts"] = [a for a in state.get("recent_alerts", []) if a.get("ts", "") > cutoff]
    return state


# --- Data gathering ---

async def _gather_context(days: int = 1) -> str:
    """Lightweight parallel data fetch for patrol checks."""
    sections = []

    async def _safe(name, coro):
        try:
            result = await coro
            return (name, result)
        except Exception as e:
            return (name, f"Error: {e}")

    tasks = [
        _safe("inbox", email.fetch_inbox(days=days, limit=30)),
        _safe("calendar", calendar.get_events_raw(view="day", days_ahead=1)),
        _safe("slack_dms", slack_agent.scan_raw(days=1)),
    ]

    # Tickets are optional
    try:
        tasks.append(_safe("tickets", tickets.scan_tickets(_USER)))
    except Exception:
        pass

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for item in results:
        if isinstance(item, Exception):
            continue
        name, data = item
        if data and not str(data).startswith("Error"):
            if isinstance(data, list):
                if data and isinstance(data[0], dict) and "subject" in data[0]:
                    text = "\n".join(f"- {e['from']}: {e['subject']} ({e['date']}) [id:{e.get('conversationId','')}]"
                                     for e in data[:20])
                else:
                    text = str(data)[:2000]
            elif isinstance(data, tuple):
                text = str(data[0])[:2000]
            else:
                text = str(data)[:2000]
            sections.append(f"### {name}\n{text}")

    return "\n\n".join(sections) if sections else "No data available."


# --- Core patrol ---

def run_patrol(quiet: bool = False, notify: str = "slack") -> str:
    """Main patrol entry point. Called by cron or CLI."""
    _ensure_files()
    orders = get_standing_orders()
    state = _prune_old_alerts(_load_state())
    recent_memory = memory.recall("", limit=10)

    # Gather fresh data
    context = asyncio.run(_gather_context())

    # Build recent alerts summary for dedup
    already_reported = "\n".join(
        f"- [{a['ts'][:16]}] {a['summary']}" for a in state.get("recent_alerts", [])
    ) or "None"

    prompt = f"""You are Envoy running autonomously on a schedule. No human is present.
Your job: check standing orders against current data and report anything that needs attention.

## Standing Orders
{orders}

## Recent Memory
{recent_memory}

## Current Data
{context}

## Already Reported (do NOT re-alert)
{already_reported}

## Instructions
1. Check each standing order against the current data.
2. Only report NEW items that haven't been reported already.
3. Be concise — one line per alert with an emoji severity indicator.
4. If nothing needs attention, respond with exactly: ALL_CLEAR
5. Format alerts as a numbered list. Include enough context to be actionable.
6. Prefix each with: 🔴 (urgent), 🟡 (important), 🔵 (informational)

Respond with ONLY the alerts or ALL_CLEAR. No preamble."""

    result = invoke_ai(prompt, max_tokens=800, tier="medium")

    if not result or "ALL_CLEAR" in result.upper():
        state["last_run"] = datetime.now().isoformat()
        _save_state(state)
        if not quiet:
            print("✅ Patrol complete — all clear.")
        return "All clear."

    # Record alerts in state for dedup
    for line in result.strip().splitlines():
        line = line.strip()
        if line and (line[0].isdigit() or line[0] in "🔴🟡🔵"):
            state["recent_alerts"].append({
                "ts": datetime.now().isoformat(),
                "summary": line[:200],
            })

    state["last_run"] = datetime.now().isoformat()
    _save_state(state)

    # Notify
    header = f"🔔 Envoy Patrol — {datetime.now().strftime('%a %I:%M%p')}"
    message = f"{header}\n\n{result}"

    if notify == "slack":
        asyncio.run(slack_agent.send_dm(_USER, message))
    elif notify == "email":
        asyncio.run(email.email_digest(message, _USER, 0))

    if not quiet:
        print(message)

    return result


# --- Suggest orders from observer patterns ---

def suggest_orders() -> str:
    """Analyze observer patterns and suggest new standing orders."""
    from agents.observer import analyze_patterns
    patterns = analyze_patterns(days=14)
    current = get_standing_orders()

    prompt = f"""Based on these observed user behavior patterns, suggest standing orders
for an autonomous patrol agent. Only suggest things that would be genuinely useful
as proactive alerts. Don't suggest things already covered.

## Observed Patterns
{patterns}

## Current Standing Orders
{current}

Format each suggestion as:
- [suggestion text] — [why: brief rationale]

Only suggest 1-5 high-value items. If nothing useful, say "No suggestions."
"""
    return invoke_ai(prompt, max_tokens=400, tier="medium")
