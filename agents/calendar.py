"""Calendar agent — view, availability, room booking, meeting creation."""

import json
from datetime import datetime, timedelta
from typing import List

from agents.base import outlook, invoke_ai


async def get_events_raw(view: str = "day", start_date: str = "", days_ahead: int = 1) -> tuple:
    """Return (event_block, xref_context) without AI call."""
    if not start_date:
        start_date = datetime.now().strftime('%m-%d-%Y')

    async with outlook() as session:
        args = {"view": view, "start_date": start_date}
        if view == "week":
            args["end_date"] = (datetime.now() + timedelta(days=days_ahead)).strftime('%m-%d-%Y')
        result = await session.call_tool("calendar_view", arguments=args)
        raw = str(result.content[0].text) if result.content else "No calendar events found."

        # Cross-reference: search for emails related to meeting subjects
        xref = ""
        if not raw.startswith("No calendar"):
            subjects = []
            for line in raw.split('\n'):
                if 'subject' in line.lower() or '|' in line:
                    parts = line.split('|')
                    if len(parts) > 1:
                        subjects.append(parts[1].strip()[:50])
            if subjects:
                try:
                    query = " OR ".join(subjects[:5])
                    email_result = await session.call_tool("email_search", arguments={
                        "query": query, "limit": 10
                    })
                    from agents.base import parse_email_search_result
                    emails = parse_email_search_result(email_result)
                    if emails:
                        xref = "\n".join(f"- {e['from']}: {e['subject']}" for e in emails[:10])
                except Exception:
                    pass
        return raw, xref


async def review(view: str = "day", start_date: str = "", days_ahead: int = 1) -> str:
    raw, xref = await get_events_raw(view, start_date, days_ahead)
    if raw.startswith("No calendar"):
        return raw

    now_str = datetime.now().strftime('%I:%M %p').lstrip('0')
    period = "today" if view == "day" else f"next {days_ahead} days"

    prompt = f"""You are an executive assistant reviewing a calendar for {period}.
Current time: {now_str}. Events before now have ALREADY HAPPENED — skip unless ongoing.

# Calendar Briefing — {period.title()}

## 🔴 Prep Required
[Meetings needing preparation]

## 📅 Today's Flow
[Chronological schedule with gaps, mark ongoing as "(NOW)"]

## ⚠️ Heads Up
[Conflicts, back-to-backs, tentative RSVPs]

## 📋 Context from Email/Slack
[Relevant email threads]

Skip empty sections. Flag tentative RSVPs and external meetings.

Events:
{raw}
{f"Cross-reference from email:{xref}" if xref else ""}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="heavy")
    except Exception as e:
        return f"# Calendar Briefing\n\n**Error:** {e}\n"


def events(start_date: str = "", days: int = 1, search: str = "") -> str:
    from agents.base import run
    raw, _ = run(get_events_raw(
        view="week" if days > 1 else "day",
        start_date=start_date, days_ahead=days,
    ))
    if search and not raw.startswith("No calendar"):
        lines = [l for l in raw.splitlines() if search.lower() in l.lower()]
        return "\n".join(lines) if lines else f"No events matching '{search}'."
    return raw


async def find_available_times(attendees: List[str], duration_minutes: int = 30, days_ahead: int = 5) -> str:
    start = datetime.now().strftime('%Y-%m-%d')
    end = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
    try:
        async with outlook() as session:
            result = await session.call_tool("calendar_availability", arguments={
                "users": [f"{a}@amazon.com" for a in attendees],
                "startDate": start, "endDate": end
            })
            return str(result.content[0].text) if result.content else "No availability data."
    except Exception as e:
        return f"Error checking availability: {e}"


async def book_room(building: str, start_time: str, end_time: str) -> str:
    try:
        async with outlook() as session:
            result = await session.call_tool("calendar_room_booking", arguments={
                "building": building, "startTime": start_time, "endTime": end_time
            })
            return str(result.content[0].text) if result.content else "No rooms found."
    except Exception as e:
        return f"Error booking room: {e}"


async def create_meeting(subject: str, start: str, end: str,
                         attendees: List[str] = None, location: str = "", body: str = "",
                         optional_attendees: List[str] = None, resources: List[str] = None,
                         recurrence: dict = None, reminder_minutes: int = None,
                         show_as: str = "", is_all_day: bool = False,
                         is_online_meeting: bool = False, sensitivity: str = "",
                         importance: str = "", categories: List[str] = None,
                         response_requested: bool = True,
                         allow_new_time_proposals: bool = True) -> str:
    try:
        async with outlook() as session:
            args = {"operation": "create", "subject": subject, "start": start, "end": end}
            if attendees:
                args["attendees"] = [f"{a}@amazon.com" if "@" not in a else a for a in attendees]
            if optional_attendees:
                args["optionalAttendees"] = [f"{a}@amazon.com" if "@" not in a else a for a in optional_attendees]
            if resources:
                args["resources"] = resources
            if location:
                args["location"] = location
            if body:
                args["body"] = body
            if recurrence:
                args["recurrence"] = recurrence
            if reminder_minutes is not None:
                args["reminderMinutes"] = reminder_minutes
            if show_as:
                args["showAs"] = show_as
            if is_all_day:
                args["isAllDay"] = True
            if is_online_meeting:
                args["isOnlineMeeting"] = True
            if sensitivity:
                args["sensitivity"] = sensitivity
            if importance:
                args["importance"] = importance
            if categories:
                args["categories"] = categories
            if not response_requested:
                args["responseRequested"] = False
            if not allow_new_time_proposals:
                args["allowNewTimeProposals"] = False
            result = await session.call_tool("calendar_meeting", arguments=args)
            return str(result.content[0].text) if result.content else "Meeting created."
    except Exception as e:
        return f"Error creating meeting: {e}"


async def list_shared_calendars() -> str:
    """List shared calendars accessible to the current user."""
    try:
        async with outlook() as session:
            result = await session.call_tool("calendar_shared_list", arguments={})
            return str(result.content[0].text) if result.content else "No shared calendars found."
    except Exception as e:
        return f"Error listing shared calendars: {e}"


async def view_shared_calendar(calendar_id: str, start_date: str = "", days: int = 1) -> str:
    """View events from a shared calendar."""
    if not start_date:
        start_date = datetime.now().strftime('%m-%d-%Y')
    try:
        async with outlook() as session:
            args = {"view": "week" if days > 1 else "day", "start_date": start_date, "calendar_id": calendar_id}
            if days > 1:
                args["end_date"] = (datetime.now() + timedelta(days=days)).strftime('%m-%d-%Y')
            result = await session.call_tool("calendar_view", arguments=args)
            return str(result.content[0].text) if result.content else "No events found."
    except Exception as e:
        return f"Error viewing shared calendar: {e}"
