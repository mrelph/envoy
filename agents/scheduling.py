"""Smart scheduling — natural language meeting requests end to end.

schedule("30m with jsmith next week, find room at SEA54") →
  1. Parse the request with AI (duration, attendees, timeframe, room, title)
  2. Resolve attendees to real emails via Phonetool (research worker)
  3. Find open slots via the calendar worker's find_time
  4. Return a formatted proposal with 2-3 options for the user to pick from

The booking itself happens in the NEXT turn: the user replies "book option 2"
and the supervisor creates the event (with room) via the calendar worker,
using the emails and slot details embedded in the proposal below.
"""

import json
from datetime import datetime

from agents.base import invoke_ai

from agents.base import current_user as _USER  # call-time alias resolution


def _parse_request(request: str) -> dict:
    """Extract structured scheduling info from a natural language request."""
    today = datetime.now().strftime("%A, %Y-%m-%d")
    prompt = f"""Today is {today}. Parse this meeting scheduling request into JSON.

Request: "{request}"

Return ONLY a JSON object with these keys:
- "title": short meeting title (invent a sensible one if not given, e.g. "Sync: markrelp / jsmith")
- "duration_minutes": integer (default 30)
- "attendees": list of Amazon aliases or emails mentioned (exclude the requester)
- "timeframe": the requested window in plain words (e.g. "next week", "tomorrow afternoon"; default "this week")
- "days_ahead": integer — days from today needed to cover the timeframe (e.g. next week → 12, this week → 5)
- "building": room/building code if a room was requested (e.g. "SEA54"), else ""

JSON:"""
    raw = invoke_ai(prompt, max_tokens=500, tier="light")
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Could not parse scheduling request: {raw[:200]}")
    parsed = json.loads(raw[start:end + 1])
    parsed.setdefault("title", "Meeting")
    parsed.setdefault("duration_minutes", 30)
    parsed.setdefault("attendees", [])
    parsed.setdefault("timeframe", "this week")
    parsed.setdefault("days_ahead", 5)
    parsed.setdefault("building", "")
    return parsed


def schedule(request: str) -> str:
    """Full scheduling flow: parse → resolve people → find times → propose slots."""
    alias = _USER()
    try:
        parsed = _parse_request(request)
    except Exception as e:
        return f"⚠️ Couldn't understand that scheduling request: {e}\n\nTry: `/schedule 30m with jsmith next week, find room at SEA54`"

    duration = int(parsed["duration_minutes"] or 30)
    attendees = [a for a in parsed["attendees"] if a]
    days_ahead = max(1, int(parsed["days_ahead"] or 5))
    building = parsed["building"]

    if not attendees:
        return "⚠️ No attendees found in that request. Tell me who to meet with, e.g. `/schedule 30m with jsmith next week`."

    # Resolve attendees + find open slots in parallel via workers
    from agents.workflows import _worker_gather
    all_people = ", ".join(attendees)
    tasks = {
        "times": ("calendar",
                  f"Find available meeting times for {all_people} and {alias}, "
                  f"duration {duration} minutes, looking {days_ahead} days ahead. "
                  f"The user wants the meeting {parsed['timeframe']} — only report slots in that window. "
                  f"Return the best 3-5 open slots with day, date, and start/end times."),
        "people": ("research",
                   f"Look up these people on Phonetool: {all_people}. "
                   f"For each, return their full name, email address, role, and location. "
                   f"If an alias doesn't resolve, say so explicitly."),
    }
    data = _worker_gather(**tasks)

    times = data.get("times", "")
    people = data.get("people", "")
    if not times or times.startswith("⚠️"):
        return f"⚠️ Couldn't check availability: {times or 'calendar worker returned nothing'}"

    room_note = f"\nThe user wants a conference room at {building} — the room will be booked when they confirm a slot." if building else ""

    prompt = f"""You are proposing meeting times to {alias} who asked: "{request}"

Parsed request: {duration}-minute meeting titled "{parsed['title']}" with {all_people}, {parsed['timeframe']}.{room_note}

ATTENDEE LOOKUP (Phonetool):
{people[:3000]}

AVAILABILITY (calendar worker):
{times[:4000]}

Write a concise markdown proposal:
# 📅 Scheduling: {parsed['title']}
## 👥 Attendees
List each attendee with their VERIFIED email address from the Phonetool lookup. If someone
didn't resolve, flag it clearly — do NOT invent an email.
## 🕐 Proposed Times
Exactly 2-3 numbered options ("**Option 1**", "**Option 2**", ...) with full day, date,
and start-end times, chosen from the availability data. Prefer mid-morning/mid-afternoon slots.
## ✅ To Confirm
Tell the user to reply with e.g. "book option 2"{' — a room at ' + building + ' will be found and booked for that slot' if building else ''}.
Include a one-line machine-readable summary at the end:
`booking-details: title="{parsed['title']}" duration={duration}m attendees=<verified emails>{' building=' + building if building else ''}`
"""
    try:
        return invoke_ai(prompt, max_tokens=4000, tier="medium")
    except Exception as e:
        return f"# 📅 Scheduling\n\n**Error formatting proposal:** {e}\n\nRaw availability:\n{times[:2000]}"
