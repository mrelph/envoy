"""Compound commands that orchestrate multiple agents.

digest, ai_summary, morning_briefing, eod_summary, todo_review, weekly_review,
pto_catchup, slack_catchup, calendar_audit, response_time_tracker,
follow_up_tracker, one_on_one_prep, commitment_tracker, meeting_prep,
yesterbox, send_to_ea, recommend_responses, learn_response
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict

from agents.base import invoke_ai, run

_USER = os.getenv('USER', '')


def _worker_gather(**tasks) -> dict:
    """Delegate data-gathering tasks to workers in parallel.

    Each kwarg is name → (worker_name, request_str).
    Returns {name: result_str} with all results.
    """
    from agents.workers import get_worker

    async def _run_one(name, worker_name, request):
        try:
            result = get_worker(worker_name)(request)
            return name, str(result.message) if hasattr(result, 'message') else str(result)
        except Exception as e:
            return name, f"⚠️ {worker_name} unavailable: {e}"

    async def _run_all():
        coros = [_run_one(n, wn, req) for n, (wn, req) in tasks.items()]
        results = await asyncio.gather(*coros, return_exceptions=True)
        out = {}
        for r in results:
            if isinstance(r, tuple):
                out[r[0]] = r[1]
            elif isinstance(r, Exception):
                out[str(r)] = f"⚠️ Error: {r}"
        return out

    return run(_run_all())


async def _read_bodies_parallel(session, emails, limit=15):
    """Read email bodies in parallel via asyncio.gather instead of sequential loop."""
    async def _read_one(e):
        try:
            result = await session.call_tool("email_read", arguments={
                "conversationId": e['conversationId'], "format": "text"
            })
            body = str(result.content[0].text) if result.content else ""
            if body:
                e['full_body'] = body[:1500]
        except Exception:
            pass
    targets = [e for e in emails[:limit] if e.get('conversationId')]
    if targets:
        await asyncio.gather(*[_read_one(e) for e in targets])


def pto_catchup(alias: str = "", days: int = 5) -> str:
    alias = alias or _USER
    from supervisor import gather_data
    gathered = gather_data(sources="email,slack,calendar,todos,tickets", days=days, alias=alias)
    if not gathered or gathered == "No data gathered from any source.":
        return "Couldn't gather any data for your catch-up. Check MCP connections."

    prompt = f"""You are briefing {alias} who has been out of office for {days} days.

In Slack data: "[you]" = sent by {alias}, "⚡@you" = {alias} was @mentioned. Prioritize unanswered DMs and @mentions.
IMPORTANT: Preserve reference IDs like [E1], [S3], [C2] in your output so the user can drill into specific items.

# 🏖️ PTO Catch-Up — Last {days} Days
## 🔴 Needs Your Attention NOW
## 📊 Team Summary
## 🌟 Leadership Focus
## 📬 Key Emails to Read
## 💬 Slack Highlights
## ✅ To-Do Status
## 📋 Recommended First Day Back Plan

Data:
{gathered[:15000]}"""
    try:
        return invoke_ai(prompt, max_tokens=10000, tier="medium")
    except Exception as e:
        return f"# PTO Catch-Up\n\n**Error:** {e}\n\n{gathered[:3000]}"


def slack_catchup(alias: str = "", days: int = 3) -> str:
    alias = alias or _USER
    from supervisor import gather_data
    gathered = gather_data(sources="slack", days=days, alias=alias)
    if not gathered or gathered == "No data gathered from any source.":
        return "No Slack data available."

    prompt = f"""Focused Slack catch-up for {alias} — last {days} days.

Key markers: "[you]" = sent by {alias}, "⚡@you" = {alias} was @mentioned. Skip conversations {alias} already replied to.
IMPORTANT: Preserve reference IDs like [S1], [S2] in your output so the user can drill into specific items.

# Slack Catch-Up
## 🔴 Unread DMs Needing Reply
## ⚠️ @Mentions You Missed
## 🔑 Important Channel Activity
## 📋 Summary & Recommended Actions

Messages:
{gathered[:10000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"# Slack Catch-Up\n\n**Error:** {e}\n"


def calendar_audit(alias: str = "", days: int = 5) -> str:
    alias = alias or _USER
    return run(_calendar_audit_async(alias, days))


async def _calendar_audit_async(alias: str, days: int) -> str:
    data = _worker_gather(
        calendar=("calendar", f"Show my calendar for the next {days} days"),
    )
    raw = data.get("calendar", "")
    if not raw or raw.startswith("⚠️"):
        return raw or "No calendar data available."

    prompt = f"""Analyze {alias}'s calendar for the next {days} days.
# Calendar Audit
## 📊 Meeting Load (% of work hours in meetings)
## 🔴 Back-to-Backs & Conflicts
## 🟡 Meetings to Consider Declining
## 🟢 Focus Time Blocks (protected time)
## 📋 Recommendations

Events:
{raw[:10000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="light")
    except Exception as e:
        return f"# Calendar Audit\n\n**Error:** {e}\n"


def response_time_tracker(alias: str = "", days: int = 7) -> str:
    alias = alias or _USER
    return run(_response_time_async(alias, days))


async def _response_time_async(alias: str, days: int) -> str:
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    # Delegate data gathering to email worker
    data = _worker_gather(
        sent=("email", f"Search sent emails from:{alias}@amazon.com between {start_date} and {end_date}, limit 100. List each with To, Subject, Date."),
        received=("email", f"Search emails to:{alias}@amazon.com between {start_date} and {end_date}, limit 100. List each with From, Subject, Date."),
    )

    combined = "\n\n".join(f"{k.upper()}:\n{v}" for k, v in data.items() if v and not v.startswith("⚠️"))
    if not combined:
        return "No email data found."

    prompt = f"""Analyze email response patterns for {alias} over {days} days.
# Response Time Analysis
## ⏱️ Your Response Patterns
## 🐌 Slow Replies From You
## ⏳ Slow Replies To You
## 📊 Volume & Top Correspondents
## 📋 Recommendations

Data:
{combined[:10000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="light")
    except Exception as e:
        return f"Error: {e}"


def follow_up_tracker(alias: str = "", days: int = 7) -> str:
    alias = alias or _USER
    return run(_follow_up_tracker_async(alias, days))


async def _follow_up_tracker_async(alias: str, days: int) -> str:
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    data = _worker_gather(
        sent=("email", f"Search sent emails from:{alias}@amazon.com between {start_date} and {end_date}, limit 50. For each, read the full body and include it. List with To, Subject, Date, Body."),
        inbox=("email", f"Search emails to:{alias}@amazon.com between {start_date} and {end_date}, limit 100. List with From, Subject, Date."),
    )

    sent_text = data.get("sent", "")
    inbox_text = data.get("inbox", "")
    if not sent_text or sent_text.startswith("⚠️"):
        return "No sent emails found."

    prompt = f"""Scan {alias}'s sent emails for unanswered threads.
Compare sent subjects/recipients against inbox replies.

# Follow-Up Tracker
## 🔴 Follow Up Now (no reply, time-sensitive)
## 🟡 Gentle Reminder (no reply, not urgent)
## 🟢 No Action Needed
For each item needing follow-up, suggest a nudge message.

SENT:
{sent_text}

INBOX (for cross-reference):
{inbox_text}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"Error: {e}"


def one_on_one_prep(person_alias: str, alias: str = "") -> str:
    alias = alias or _USER
    return run(_one_on_one_prep_async(person_alias, alias))


async def _one_on_one_prep_async(person_alias: str, alias: str) -> str:
    # Delegate data gathering to workers in parallel
    data = _worker_gather(
        profile=("research", f"Look up {person_alias} on Phonetool — role, team, manager, tenure"),
        emails=("email", f"Search emails between {alias}@amazon.com and {person_alias}@amazon.com from the last 14 days. List each with From, To, Subject, Date."),
        calendar=("calendar", f"Show my calendar for the next 5 days"),
        todos=("productivity", f"List my to-do items"),
    )

    sections = []
    for key, val in data.items():
        if val and not val.startswith("⚠️"):
            sections.append(f"{key.upper()}:\n{val[:2000]}")

    # Filter calendar/todos to only include items mentioning the person
    for key in ("calendar", "todos"):
        if key in data and person_alias.lower() not in data[key].lower():
            sections = [s for s in sections if not s.startswith(key.upper())]

    combined = "\n\n".join(s for s in sections if s)
    if not combined:
        return f"No data found for 1:1 prep with {person_alias}."

    prompt = f"""Generate a 1:1 prep brief for {alias} meeting with {person_alias}.
# 1:1 Prep — {person_alias}
## 👤 About Them
## 📧 Recent Email Context
## 📋 Shared Action Items
## 💬 Suggested Talking Points
## ❓ Questions to Ask

Data:
{combined[:10000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"Error: {e}"


def commitment_tracker(alias: str = "", days: int = 7) -> str:
    alias = alias or _USER
    return run(_commitment_tracker_async(alias, days))


async def _commitment_tracker_async(alias: str, days: int) -> str:
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    data = _worker_gather(
        sent=("email", f"Search sent emails from:{alias}@amazon.com between {start_date} and {end_date}, limit 50. For each, read the full body and include it. List with To, Subject, Date, Body."),
        slack=("comms", f"Scan my Slack channels for the last {min(days, 7)} days. Show messages I sent, especially any commitments or promises."),
    )

    sections = []
    for key, val in data.items():
        if val and not val.startswith("⚠️"):
            sections.append(f"{key.upper()}:\n{val[:3000]}")

    combined = "\n\n".join(s for s in sections if s)
    if not combined:
        return "No data found."

    prompt = f"""Scan {alias}'s sent emails and Slack for commitments and promises.
Look for: "I'll send", "by Friday", "action on me", "will follow up", deadlines, etc.

# Commitment Tracker
## 🔴 Overdue (past deadline)
## 🟡 Due This Week
## 🟢 Open (no deadline)
## ✅ Likely Fulfilled
## 📋 Summary

Data:
{combined[:10000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"Error: {e}"


def meeting_prep(meeting_subject: str = "", alias: str = "") -> str:
    alias = alias or _USER
    return run(_meeting_prep_async(meeting_subject, alias))


async def _meeting_prep_async(meeting_subject: str, alias: str) -> str:
    # Get calendar data via worker
    cal_data = _worker_gather(
        calendar=("calendar", f"Show my calendar for the next 5 days"),
    )
    raw_cal = cal_data.get("calendar", "")
    if not raw_cal or raw_cal.startswith("⚠️"):
        return "No upcoming meetings found."

    if not meeting_subject:
        target = raw_cal.split('\n')[0] if raw_cal else ""
    else:
        matches = [l for l in raw_cal.split('\n') if meeting_subject.lower() in l.lower()]
        target = matches[0] if matches else ""

    if not target:
        return f"Meeting '{meeting_subject}' not found in upcoming calendar."

    # Gather attendee profiles and related emails via workers in parallel
    gather_tasks = {"meeting": ("calendar", f"Tell me about this meeting: {target}")}

    # Extract potential attendee aliases from the meeting line
    attendees = [w.replace('@amazon.com', '') for w in target.split() if '@' in w]
    if attendees:
        gather_tasks["attendees"] = ("research", f"Look up these people on Phonetool: {', '.join(attendees[:5])}")

    keywords = [w for w in target.split() if len(w) > 3][:3]
    if keywords:
        gather_tasks["emails"] = ("email", f"Search emails for: {' '.join(keywords)}, limit 10")

    data = _worker_gather(**gather_tasks)

    sections = [f"MEETING:\n{target}"]
    for key, val in data.items():
        if val and not val.startswith("⚠️") and key != "meeting":
            sections.append(f"{key.upper()}:\n{val[:2000]}")

    combined = "\n\n".join(s for s in sections if s)
    prompt = f"""Generate a meeting prep brief for {alias}.
# Meeting Prep
## 📅 Meeting Details
## 👥 Attendee Profiles
## 📧 Related Email Context
## 📋 Prep Actions
## 💬 Suggested Talking Points

Data:
{combined[:8000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"Error: {e}"


def yesterbox(alias: str = "", days: int = 1) -> str:
    alias = alias or _USER
    from supervisor import gather_data
    gathered = gather_data(sources="email,slack", days=days, alias=alias)
    if not gathered or gathered == "No data gathered from any source.":
        return "No emails from yesterday to process."

    start_date = (datetime.now() - timedelta(days=days+1)).strftime('%Y-%m-%d')
    end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    prompt = f"""Yesterbox triage for {alias} — emails from {start_date} to {end_date}.
IMPORTANT: Preserve reference IDs like [E1], [S3] in your output so the user can drill into specific items.

# Yesterbox

## 🔴 Reply Now (< 2 min each)
[Quick replies needed — draft a suggested response for each]

## 📅 Schedule Time (needs thought)
[Emails needing longer responses — suggest when and what to address]

## ➡️ Delegate
[Emails someone else should handle — suggest who]

## 📂 Archive (no action)
[Read-only, FYI, already handled]

## 📊 Summary
Total emails | Estimated processing time: [X minutes]

Data:
{gathered[:10000]}"""
    try:
        return invoke_ai(prompt, max_tokens=10000, tier="medium")
    except Exception as e:
        return f"Error: {e}"


# --- Response learning ---

RESPONSE_PATTERNS_FILE = os.path.expanduser("~/.envoy/response_patterns.jsonl")
MAX_PATTERNS = 200


def learn_response(context: str, response: str, medium: str = "email") -> str:
    os.makedirs(os.path.dirname(RESPONSE_PATTERNS_FILE), exist_ok=True)
    entry = json.dumps({
        "ts": datetime.now().isoformat(), "medium": medium,
        "context": context[:500], "response": response[:1000],
    })
    with open(RESPONSE_PATTERNS_FILE, "a") as f:
        f.write(entry + "\n")
    try:
        lines = open(RESPONSE_PATTERNS_FILE).readlines()
        if len(lines) > MAX_PATTERNS:
            with open(RESPONSE_PATTERNS_FILE, "w") as f:
                f.writelines(lines[-MAX_PATTERNS:])
    except Exception:
        pass
    return "✅ Response pattern saved."


def _load_response_patterns() -> str:
    if not os.path.exists(RESPONSE_PATTERNS_FILE):
        return ""
    try:
        lines = open(RESPONSE_PATTERNS_FILE).readlines()
        entries = [json.loads(l) for l in lines[-50:] if l.strip()]
        if not entries:
            return ""
        return "\n".join(
            f"- [{e.get('medium','?')}] Context: {e['context'][:200]}\n  Response: {e['response'][:300]}"
            for e in entries)
    except Exception:
        return ""


def recommend_responses(alias: str = "", days: int = 3) -> str:
    alias = alias or _USER
    return run(_recommend_responses_async(alias, days))


async def _recommend_responses_async(alias: str, days: int) -> str:
    data = _worker_gather(
        emails=("email", f"Search emails to:{alias}@amazon.com in inbox from the last {days} days, limit 30. For the first 10, read the full body. List with From, Subject, Date, Body."),
        slack_dms=("comms", f"Show my unread Slack DMs and group DMs from the last {days} days. Include message text and sender."),
    )

    sections = []
    for key, val in data.items():
        if val and not val.startswith("⚠️"):
            sections.append(f"{key.upper()}:\n{val[:3000]}")

    if not sections:
        return f"No direct messages found in the last {days} days."

    msg_text = "\n\n".join(sections)

    patterns = _load_response_patterns()
    patterns_section = f"\n## RESPONSE HISTORY\n{patterns[:3000]}\n" if patterns else ""

    prompt = f"""Draft recommended responses for {alias}@amazon.com.
{patterns_section}
For each message needing a response:
### [index] Reply to [sender] — [topic]
**Medium:** email | slack
**Urgency:** 🔴 Today | 🟡 Soon | 🟢 When free
**Draft response:** [concise, professional]

Messages:
{msg_text[:6000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"Error: {e}"


# --- Send to EA ---

def send_to_ea(message: str, ea_alias: str = None, category: str = "task") -> str:
    if not ea_alias:
        ea_alias = os.environ.get("ENVOY_EA_ALIAS", "")
    if not ea_alias:
        return "No EA alias configured. Set ENVOY_EA_ALIAS or pass ea_alias."

    from agents.base import agent_name as get_name
    subject_map = {
        "task": f"[{get_name()}] Task Request",
        "schedule": f"[{get_name()}] Scheduling Request",
        "info": f"[{get_name()}] FYI",
    }
    subject = subject_map.get(category, f"[{get_name()}] Request")
    data = _worker_gather(
        send=("email", f"Send an email to {ea_alias}@amazon.com with subject '{subject}' and body: {message}"),
    )
    return data.get("send", "Failed to send.")