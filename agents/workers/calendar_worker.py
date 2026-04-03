"""Calendar worker — schedule, meetings, rooms."""

from strands import Agent, tool
from agents.base import run
from agents.workers import _model


def create():
    from agents import calendar as cal_mod

    @tool
    def view(view_type: str = "day", days_ahead: int = 1) -> str:
        """View calendar with AI briefing.
        Args:
            view_type: 'day' or 'week'
            days_ahead: Days to look ahead
        """
        return run(cal_mod.review(view_type, days_ahead=days_ahead))

    @tool
    def calendar_operation(operation: str, subject: str = "", start: str = "", end: str = "",
                           attendees: str = "", optional_attendees: str = "",
                           resources: str = "", location: str = "", body: str = "",
                           meeting_id: str = "", meeting_change_key: str = "",
                           building: str = "", duration: int = 30, days_ahead: int = 5,
                           start_date: str = "", end_date: str = "",
                           recurrence_pattern: str = "", recurrence_interval: int = 1,
                           recurrence_days: str = "", recurrence_end_date: str = "",
                           reminder_minutes: int = -1, show_as: str = "",
                           is_all_day: bool = False, calendar_id: str = "") -> str:
        """Full calendar control — create, read, update, delete, search, find_time, find_room, shared_calendars.
        Args:
            operation: create, read, update, delete, search, find_time, find_room, shared_calendars, view_shared
            subject: Meeting subject
            start: Start ISO datetime
            end: End ISO datetime
            attendees: Comma-separated required attendee emails/aliases
            optional_attendees: Comma-separated optional attendee emails/aliases
            resources: Comma-separated room resource emails
            location: Meeting location
            body: Meeting description
            meeting_id: Meeting ID (read/update/delete)
            meeting_change_key: Change key (update/delete)
            building: Building code for find_room
            duration: Minutes for find_time
            days_ahead: Days ahead for find_time/view_shared
            start_date: Start date MM-DD-YYYY
            end_date: End date MM-DD-YYYY
            recurrence_pattern: daily, weekly, or monthly (for recurring meetings)
            recurrence_interval: Interval between occurrences (default 1)
            recurrence_days: Comma-separated days for weekly (e.g. Monday,Wednesday)
            recurrence_end_date: End date for recurrence YYYY-MM-DD
            reminder_minutes: Reminder before meeting in minutes (-1 = default, 0 = none)
            show_as: free, busy, tentative, or away
            is_all_day: Whether this is an all-day event
            calendar_id: Shared calendar ID (for view_shared)
        """
        from tools import _outlook_tool
        if operation == "find_time":
            att_list = [a.strip() for a in attendees.split(",") if a.strip()]
            return run(cal_mod.find_available_times(att_list, duration, days_ahead))
        if operation == "find_room":
            return run(cal_mod.book_room(building, start, end))
        if operation == "search":
            return _outlook_tool("calendar_search", {"query": subject, "limit": 25})
        if operation == "shared_calendars":
            return run(cal_mod.list_shared_calendars())
        if operation == "view_shared":
            return run(cal_mod.view_shared_calendar(calendar_id, start_date, days_ahead))
        args = {"operation": operation}
        if subject: args["subject"] = subject
        if start: args["start"] = start
        if end: args["end"] = end
        if attendees:
            args["attendees"] = [f"{a.strip()}@amazon.com" if "@" not in a.strip() else a.strip() for a in attendees.split(",")]
        if optional_attendees:
            args["optionalAttendees"] = [f"{a.strip()}@amazon.com" if "@" not in a.strip() else a.strip() for a in optional_attendees.split(",")]
        if resources:
            args["resources"] = [r.strip() for r in resources.split(",")]
        if location: args["location"] = location
        if body: args["body"] = body
        if meeting_id: args["meetingId"] = meeting_id
        if meeting_change_key: args["meetingChangeKey"] = meeting_change_key
        if is_all_day: args["isAllDay"] = True
        if show_as: args["showAs"] = show_as
        if reminder_minutes >= 0: args["reminderMinutes"] = reminder_minutes
        if recurrence_pattern:
            rec = {"pattern": recurrence_pattern, "interval": recurrence_interval}
            if recurrence_days:
                rec["daysOfWeek"] = [d.strip() for d in recurrence_days.split(",")]
            if recurrence_end_date:
                rec["endDate"] = recurrence_end_date
            args["recurrence"] = rec
        return _outlook_tool("calendar_meeting", args)

    @tool
    def find_meeting_room(building: str, start_time: str, end_time: str) -> str:
        """Find available meeting rooms in a building via meetings.amazon.com.
        Args:
            building: Building code (e.g. SEA54, JFK27)
            start_time: ISO datetime
            end_time: ISO datetime
        """
        from agents import internal
        return run(internal.find_rooms(building, start_time=start_time, end_time=end_time))

    return Agent(
        model=_model("light"),
        system_prompt="You are a calendar specialist. You view schedules, create meetings (including recurring with optional attendees and room resources), find available times, book rooms, and access shared calendars. Use Outlook for calendar operations and meetings.amazon.com only for finding meeting rooms. Return structured data.",
        tools=[view, calendar_operation, find_meeting_room],
        callback_handler=None,
    )
