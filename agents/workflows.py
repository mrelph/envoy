"""Compound commands that orchestrate multiple agents.

digest, ai_summary, morning_briefing, eod_summary, todo_review, weekly_review,
pto_catchup, slack_catchup, calendar_audit, response_time_tracker,
follow_up_nagger, one_on_one_prep, commitment_tracker, meeting_prep,
yesterbox, send_to_ea, recommend_responses, learn_response
"""

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict

from envoy_logger import get_logger
from agents.base import invoke_ai, MCPConnectionError, outlook, parse_email_search_result
from agents import people, email, slack_agent, calendar, todo, tickets, memory2 as memory

_USER = os.getenv('USER', '')


def pto_catchup(alias: str = "", days: int = 5) -> str:
    alias = alias or _USER
    return asyncio.run(_pto_catchup_async(alias, days))


async def _pto_catchup_async(alias: str, days: int) -> str:
    sections = []
    try:
        raw = generate_digest(alias, days)
        sections.append(f"TEAM EMAIL ACTIVITY:\n{raw[:3000]}")
    except Exception:
        pass
    try:
        raw = generate_digest(alias, days, vip_mode=True)
        sections.append(f"LEADERSHIP ACTIVITY:\n{raw[:3000]}")
    except Exception:
        pass
    try:
        emails = asyncio.run(email.fetch_inbox(days=days, limit=50))
        if emails:
            sections.append("YOUR INBOX:\n" + "\n".join(
                f"- {e['from']}: {e['subject']} ({e['date']})" for e in emails[:30]))
    except Exception:
        pass
    try:
        slack_data = await slack_agent.scan_raw(days=min(days, 7))
        if slack_data and not slack_data.startswith("No "):
            sections.append(f"SLACK ACTIVITY:\n{slack_data[:3000]}")
    except Exception:
        pass
    try:
        customers = await email.scan_customer_emails(alias, days)
        if customers:
            sections.append(f"CUSTOMER EMAILS:\n{customers[:2000]}")
    except Exception:
        pass
    try:
        todos_raw = await todo.fetch_todos_full()
        if todos_raw:
            sections.append(f"OPEN TO-DO ITEMS:\n{todos_raw[:1500]}")
    except Exception:
        pass

    combined = "\n\n---\n\n".join(s for s in sections if s)
    if not combined:
        return "Couldn't gather any data for your catch-up. Check MCP connections."

    prompt = f"""You are briefing {alias} who has been out of office for {days} days.
# 🏖️ PTO Catch-Up — Last {days} Days
## 🔴 Needs Your Attention NOW
## 📊 Team Summary
## 🌟 Leadership Focus
## 📬 Key Emails to Read
## 💬 Slack Highlights
## 🤝 Customer Activity
## ✅ To-Do Status
## 📋 Recommended First Day Back Plan

Data:
{combined[:15000]}"""
    try:
        return invoke_ai(prompt, max_tokens=10000, tier="heavy")
    except Exception as e:
        return f"# PTO Catch-Up\n\n**Error:** {e}\n\n{combined}"


def slack_catchup(alias: str = "", days: int = 3) -> str:
    alias = alias or _USER
    return asyncio.run(_slack_catchup_async(alias, days))


async def _slack_catchup_async(alias: str, days: int) -> str:
    raw = await slack_agent.scan_raw(days=days)
    if raw.startswith("No ") or raw.startswith("Error"):
        return raw

    prompt = f"""Focused Slack catch-up for {alias} — last {days} days.
# Slack Catch-Up
## 🔴 Unread DMs Needing Reply
## ⚠️ @Mentions You Missed
## 🔑 Important Channel Activity
## 📋 Summary & Recommended Actions

Messages:
{raw[:10000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"# Slack Catch-Up\n\n**Error:** {e}\n"


def calendar_audit(alias: str = "", days: int = 5) -> str:
    alias = alias or _USER
    return asyncio.run(_calendar_audit_async(alias, days))


async def _calendar_audit_async(alias: str, days: int) -> str:
    raw, _ = await calendar.get_events_raw(view="week", days_ahead=days)
    if raw.startswith("No calendar"):
        return raw

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
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"# Calendar Audit\n\n**Error:** {e}\n"


def response_time_tracker(alias: str = "", days: int = 7) -> str:
    alias = alias or _USER
    return asyncio.run(_response_time_async(alias, days))


async def _response_time_async(alias: str, days: int) -> str:
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    sections = []
    async with outlook() as session:
        result = await session.call_tool("email_search", arguments={
            "query": f"from:{alias}@amazon.com", "startDate": start_date,
            "endDate": end_date, "limit": 100
        })
        sent = parse_email_search_result(result)
        if sent:
            sections.append("SENT:\n" + "\n".join(
                f"- To: {e['to']} | {e['subject']} | {e['date']}" for e in sent[:50]))
        result = await session.call_tool("email_search", arguments={
            "query": f"to:{alias}@amazon.com", "startDate": start_date,
            "endDate": end_date, "limit": 100
        })
        received = parse_email_search_result(result)
        if received:
            sections.append("RECEIVED:\n" + "\n".join(
                f"- From: {e['from']} | {e['subject']} | {e['date']}" for e in received[:50]))

    combined = "\n\n".join(sections)
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
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"Error: {e}"


def follow_up_nagger(alias: str = "", days: int = 7) -> str:
    alias = alias or _USER
    return asyncio.run(_follow_up_nagger_async(alias, days))


async def _follow_up_nagger_async(alias: str, days: int) -> str:
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    async with outlook() as session:
        sent_result = await session.call_tool("email_search", arguments={
            "query": f"from:{alias}@amazon.com", "startDate": start_date,
            "endDate": end_date, "limit": 50
        })
        sent = parse_email_search_result(sent_result)
        inbox_result = await session.call_tool("email_search", arguments={
            "query": f"to:{alias}@amazon.com", "startDate": start_date,
            "endDate": end_date, "limit": 100
        })
        inbox = parse_email_search_result(inbox_result)

    if not sent:
        return "No sent emails found."

    sent_text = "\n".join(f"- To: {e['to']} | {e['subject']} | {e['date']}" for e in sent[:30])
    inbox_text = "\n".join(f"- From: {e['from']} | {e['subject']} | {e['date']}" for e in inbox[:50])

    prompt = f"""Scan {alias}'s sent emails for unanswered threads.
Compare sent subjects/recipients against inbox replies.

# Follow-Up Nagger
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
    return asyncio.run(_one_on_one_prep_async(person_alias, alias))


async def _one_on_one_prep_async(person_alias: str, alias: str) -> str:
    sections = []
    # Phonetool profile
    try:
        from agents.base import builder
        async with builder() as session:
            result = await session.call_tool("ReadInternalWebsites",
                arguments={"inputs": [f"https://phonetool.amazon.com/users/{person_alias}"]})
            profile = str(result.content[0].text) if result.content else ""
            if profile:
                sections.append(f"PROFILE:\n{profile[:2000]}")
    except Exception:
        pass
    # Recent email threads
    try:
        start_date = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')
        async with outlook() as session:
            result = await session.call_tool("email_search", arguments={
                "query": f"from:{person_alias}@amazon.com to:{alias}@amazon.com",
                "startDate": start_date, "endDate": end_date, "limit": 20
            })
            emails = parse_email_search_result(result)
            result2 = await session.call_tool("email_search", arguments={
                "query": f"from:{alias}@amazon.com to:{person_alias}@amazon.com",
                "startDate": start_date, "endDate": end_date, "limit": 20
            })
            emails += parse_email_search_result(result2)
        if emails:
            sections.append("RECENT EMAILS:\n" + "\n".join(
                f"- {e['from']} → {e['to']}: {e['subject']} ({e['date']})" for e in emails[:20]))
    except Exception:
        pass
    # Shared todos
    try:
        todos_raw = await todo.fetch_todos_full()
        if todos_raw and person_alias.lower() in todos_raw.lower():
            sections.append(f"SHARED TO-DOS:\n{todos_raw[:1000]}")
    except Exception:
        pass
    # Upcoming shared meetings
    try:
        raw_cal, _ = await calendar.get_events_raw(view="week", days_ahead=5)
        if not raw_cal.startswith("No calendar") and person_alias.lower() in raw_cal.lower():
            sections.append(f"SHARED MEETINGS:\n{raw_cal[:1000]}")
    except Exception:
        pass

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
    return asyncio.run(_commitment_tracker_async(alias, days))


async def _commitment_tracker_async(alias: str, days: int) -> str:
    sections = []
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    try:
        async with outlook() as session:
            result = await session.call_tool("email_search", arguments={
                "query": f"from:{alias}@amazon.com", "startDate": start_date,
                "endDate": end_date, "limit": 50
            })
            sent = parse_email_search_result(result)
            if sent:
                sections.append("SENT EMAILS:\n" + "\n".join(
                    f"- To: {e['to']} | {e['subject']} | {e['date']} | {e['snippet'][:200]}" for e in sent[:30]))
    except Exception:
        pass
    try:
        slack_data = await slack_agent.scan_raw(days=min(days, 7))
        if slack_data and not slack_data.startswith("No "):
            sections.append(f"SLACK:\n{slack_data[:3000]}")
    except Exception:
        pass

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
    return asyncio.run(_meeting_prep_async(meeting_subject, alias))


async def _meeting_prep_async(meeting_subject: str, alias: str) -> str:
    # Find the meeting
    raw_cal, _ = await calendar.get_events_raw(view="week", days_ahead=5)
    if raw_cal.startswith("No calendar"):
        return "No upcoming meetings found."

    if not meeting_subject:
        # Use next meeting
        target = raw_cal.split('\n')[0] if raw_cal else ""
    else:
        matches = [l for l in raw_cal.split('\n') if meeting_subject.lower() in l.lower()]
        target = matches[0] if matches else ""

    if not target:
        return f"Meeting '{meeting_subject}' not found in upcoming calendar."

    sections = [f"MEETING:\n{target}"]

    # Look up attendees
    try:
        from agents.base import builder
        attendees = []
        for word in target.split():
            if '@' in word or word.endswith('@amazon.com'):
                attendees.append(word.replace('@amazon.com', ''))
        for att in attendees[:5]:
            try:
                async with builder() as session:
                    result = await session.call_tool("ReadInternalWebsites",
                        arguments={"inputs": [f"https://phonetool.amazon.com/users/{att}"]})
                    profile = str(result.content[0].text)[:500] if result.content else ""
                    if profile:
                        sections.append(f"ATTENDEE {att}:\n{profile}")
            except Exception:
                pass
    except Exception:
        pass

    # Related emails
    try:
        keywords = [w for w in target.split() if len(w) > 3][:3]
        if keywords:
            query = " ".join(keywords)
            async with outlook() as session:
                result = await session.call_tool("email_search", arguments={
                    "query": query, "limit": 10
                })
                emails = parse_email_search_result(result)
                if emails:
                    sections.append("RELATED EMAILS:\n" + "\n".join(
                        f"- {e['from']}: {e['subject']}" for e in emails[:10]))
    except Exception:
        pass

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
    return asyncio.run(_yesterbox_async(alias, days))


async def _yesterbox_async(alias: str, days: int) -> str:
    """Yesterbox: process yesterday's emails with AI triage."""
    start_date = (datetime.now() - timedelta(days=days+1)).strftime('%Y-%m-%d')
    end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    async with outlook() as session:
        result = await session.call_tool("email_search", arguments={
            "query": f"to:{alias}@amazon.com", "folder": "inbox",
            "startDate": start_date, "endDate": end_date, "limit": 100
        })
        emails = parse_email_search_result(result)

    if not emails:
        return "No emails from yesterday to process."

    email_list = "\n".join(
        f"[{i}] From: {e['from']} | Subject: {e['subject']} | Date: {e['date']} | Preview: {e['snippet'][:200]}"
        for i, e in enumerate(emails))

    prompt = f"""Yesterbox triage for {alias} — emails from {start_date} to {end_date}.

# Yesterbox — {len(emails)} emails

## 🔴 Reply Now (< 2 min each)
[Quick replies needed — draft a suggested response for each]

## 📅 Schedule Time (needs thought)
[Emails needing longer responses — suggest when and what to address]

## ➡️ Delegate
[Emails someone else should handle — suggest who]

## 📂 Archive (no action)
[Read-only, FYI, already handled]

## 📊 Summary
Total: {len(emails)} | Estimated processing time: [X minutes]

Emails:
{email_list[:10000]}"""
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
    return asyncio.run(_recommend_responses_async(alias, days))


async def _recommend_responses_async(alias: str, days: int) -> str:
    messages = []
    try:
        async with outlook() as session:
            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
            end_date = datetime.now().strftime('%Y-%m-%d')
            result = await session.call_tool("email_search", arguments={
                "query": f"to:{alias}@amazon.com", "folder": "inbox",
                "startDate": start_date, "endDate": end_date, "limit": 30
            })
            for e in parse_email_search_result(result):
                messages.append({"medium": "email", "from": e.get("from", ""),
                    "subject": e.get("subject", ""), "preview": e.get("snippet", ""),
                    "date": e.get("date", ""), "conversation_id": e.get("conversationId", "")})
    except Exception as ex:
        messages.append({"medium": "email", "error": str(ex)})

    try:
        from datetime import timezone
        oldest = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        from agents.base import slack as slack_ctx
        async with slack_ctx() as session:
            for ch_type in ["dm", "group_dm"]:
                try:
                    result = await session.call_tool("list_channels",
                        arguments={"channelTypes": [ch_type], "unreadOnly": True, "limit": 15})
                    ch_data = json.loads(result.content[0].text) if result.content else {}
                    ch_ids = [c['id'] for c in ch_data.get('channels', [])]
                    if not ch_ids:
                        continue
                    batch = [{"channelId": cid, "oldest": oldest, "limit": 10} for cid in ch_ids]
                    hist = await session.call_tool("batch_get_conversation_history", arguments={"channels": batch})
                    raw = json.loads(hist.content[0].text) if hist.content else []
                    for item in raw:
                        for msg in item.get('result', {}).get('messages', []):
                            text = msg.get('text', '')
                            if text:
                                messages.append({
                                    "medium": "slack_dm" if ch_type == "dm" else "slack_group_dm",
                                    "from": msg.get('user', '?'), "preview": text[:500],
                                    "channel_id": item.get('channelId', ''), "thread_ts": msg.get('ts', '')})
                except Exception:
                    pass
    except Exception as ex:
        messages.append({"medium": "slack", "error": str(ex)})

    if not messages or all("error" in m for m in messages):
        return f"No direct messages found in the last {days} days."

    msg_text = ""
    for i, m in enumerate(messages):
        if "error" in m:
            continue
        msg_text += f"[{i}] ({m['medium']}) From: {m.get('from','')} | {m.get('subject','')}\n"
        msg_text += f"    {m.get('preview','')[:300]}\n\n"

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
    return asyncio.run(_send_to_ea_async(message, ea_alias, category))


async def _send_to_ea_async(message: str, ea_alias: str = None, category: str = "task") -> str:
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
    return await email.send_email([f"{ea_alias}@amazon.com"], subject, message)