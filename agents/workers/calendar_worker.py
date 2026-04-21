"""Calendar worker v2 — decomposed tools matching MCP capabilities."""

from strands import Agent, tool
from agents.base import run
from agents.workers import _model


def create():
    from agents import calendar as cal_mod

    @tool
    def view_calendar(view_type: str = "day", days_ahead: int = 1, calendar_id: str = "") -> str:
        """View calendar with AI briefing.
        Args:
            view_type: 'day' or 'week'
            days_ahead: Days to look ahead
            calendar_id: Shared calendar ID (empty = your calendar)
        """
        if calendar_id:
            return run(cal_mod.view_shared_calendar(calendar_id, "", days_ahead))
        return run(cal_mod.review(view_type, days_ahead=days_ahead))

    @tool
    def create_event(subject: str, start: str, end: str,
                     attendees: str = "", optional_attendees: str = "",
                     resources: str = "", location: str = "", body: str = "",
                     show_as: str = "", is_all_day: bool = False,
                     is_online_meeting: bool = False, sensitivity: str = "",
                     importance: str = "", categories: str = "",
                     response_requested: bool = True,
                     allow_new_time_proposals: bool = True,
                     reminder_minutes: int = -1,
                     recurrence_pattern: str = "", recurrence_interval: int = 1,
                     recurrence_days: str = "", recurrence_end_date: str = "") -> str:
        """Create a calendar event or meeting.
        Args:
            subject: Meeting subject
            start: Start ISO datetime
            end: End ISO datetime
            attendees: Comma-separated required attendee emails/aliases
            optional_attendees: Comma-separated optional attendee emails/aliases
            resources: Comma-separated room resource emails
            location: Meeting location
            body: Meeting description/agenda
            show_as: free, busy, tentative, oof (out of office), workingElsewhere, unknown
            is_all_day: All-day event
            is_online_meeting: Add online meeting link
            sensitivity: normal, personal, private, confidential
            importance: low, normal, high
            categories: Comma-separated category names (e.g. "Focus Time,Project X")
            response_requested: Request RSVP from attendees (default true)
            allow_new_time_proposals: Allow attendees to propose new times (default true)
            reminder_minutes: Reminder before event (-1 = default, 0 = none)
            recurrence_pattern: daily, weekly, or monthly
            recurrence_interval: Interval between occurrences
            recurrence_days: Comma-separated days for weekly (e.g. Monday,Wednesday)
            recurrence_end_date: End date for recurrence YYYY-MM-DD
        """
        from tools import _outlook_tool
        args = _build_event_args("create", subject, start, end,
                                 attendees, optional_attendees, resources, location, body,
                                 show_as, is_all_day, is_online_meeting, sensitivity,
                                 importance, categories, response_requested,
                                 allow_new_time_proposals, reminder_minutes,
                                 recurrence_pattern, recurrence_interval,
                                 recurrence_days, recurrence_end_date)
        return _outlook_tool("calendar_meeting", args)

    @tool
    def update_event(meeting_id: str, meeting_change_key: str = "",
                     subject: str = "", start: str = "", end: str = "",
                     attendees: str = "", optional_attendees: str = "",
                     resources: str = "", location: str = "", body: str = "",
                     show_as: str = "", is_all_day: bool = False,
                     is_online_meeting: bool = False, sensitivity: str = "",
                     importance: str = "", categories: str = "",
                     response_requested: bool = True,
                     allow_new_time_proposals: bool = True,
                     reminder_minutes: int = -1) -> str:
        """Update an existing calendar event — change time, attendees, status, categories, etc.
        Args:
            meeting_id: Meeting ID (from reading/searching events)
            meeting_change_key: Change key (from reading events)
            subject: New subject (empty = keep current)
            start: New start ISO datetime (empty = keep current)
            end: New end ISO datetime (empty = keep current)
            attendees: New required attendees (replaces existing)
            optional_attendees: New optional attendees (replaces existing)
            resources: New room resources (replaces existing)
            location: New location
            body: New description
            show_as: free, busy, tentative, oof, workingElsewhere, unknown
            is_all_day: All-day event
            is_online_meeting: Add online meeting link
            sensitivity: normal, personal, private, confidential
            importance: low, normal, high
            categories: Comma-separated category names
            response_requested: Request RSVP
            allow_new_time_proposals: Allow time proposals
            reminder_minutes: Reminder (-1 = default, 0 = none)
        """
        from tools import _outlook_tool
        args = {"operation": "update", "meetingId": meeting_id}
        if meeting_change_key:
            args["meetingChangeKey"] = meeting_change_key
        if subject: args["subject"] = subject
        if start: args["start"] = start
        if end: args["end"] = end
        _add_attendee_args(args, attendees, optional_attendees, resources)
        if location: args["location"] = location
        if body: args["body"] = body
        _add_metadata_args(args, show_as, is_all_day, is_online_meeting,
                           sensitivity, importance, categories,
                           response_requested, allow_new_time_proposals,
                           reminder_minutes)
        return _outlook_tool("calendar_meeting", args)

    @tool
    def delete_event(meeting_id: str, meeting_change_key: str = "") -> str:
        """Cancel/delete a calendar event.
        Args:
            meeting_id: Meeting ID
            meeting_change_key: Change key
        """
        from tools import _outlook_tool
        args = {"operation": "delete", "meetingId": meeting_id}
        if meeting_change_key:
            args["meetingChangeKey"] = meeting_change_key
        return _outlook_tool("calendar_meeting", args)

    @tool
    def search_events(query: str, limit: int = 25) -> str:
        """Search calendar events by keyword.
        Args:
            query: Search term (subject, body, attendee)
            limit: Max results
        """
        from tools import _outlook_tool
        return _outlook_tool("calendar_search", {"query": query, "limit": limit})

    @tool
    def find_time(attendees: str, duration: int = 30, days_ahead: int = 5) -> str:
        """Find available meeting times for a group of people.
        Args:
            attendees: Comma-separated aliases or emails
            duration: Meeting duration in minutes
            days_ahead: Days ahead to search
        """
        att_list = [a.strip() for a in attendees.split(",") if a.strip()]
        return run(cal_mod.find_available_times(att_list, duration, days_ahead))

    @tool
    def find_room(building: str, start_time: str, end_time: str) -> str:
        """Find available meeting rooms in a building.
        Args:
            building: Building code (e.g. SEA54, JFK27)
            start_time: ISO datetime
            end_time: ISO datetime
        """
        from agents import internal
        return run(internal.find_rooms(building, start_time=start_time, end_time=end_time))

    @tool
    def shared_calendars(action: str = "list", calendar_id: str = "",
                         start_date: str = "", days: int = 1) -> str:
        """List or view shared calendars.
        Args:
            action: 'list' to see available shared calendars, 'view' to see events
            calendar_id: Calendar ID (required for 'view')
            start_date: Start date MM-DD-YYYY (for 'view')
            days: Days to show (for 'view')
        """
        if action == "view" and calendar_id:
            return run(cal_mod.view_shared_calendar(calendar_id, start_date, days))
        return run(cal_mod.list_shared_calendars())

    @tool
    def block_time(subject: str, start: str, end: str,
                   show_as: str = "busy", sensitivity: str = "private",
                   categories: str = "", is_all_day: bool = False) -> str:
        """Block time on your calendar (focus time, OOO, personal, etc). No attendees.
        Args:
            subject: Block title (e.g. "Focus Time", "Out of Office", "Lunch")
            start: Start ISO datetime
            end: End ISO datetime
            show_as: free, busy, tentative, oof, workingElsewhere
            sensitivity: normal, personal, private, confidential
            categories: Comma-separated category names
            is_all_day: All-day block
        """
        from tools import _outlook_tool
        args = {"operation": "create", "subject": subject, "start": start, "end": end,
                "showAs": show_as, "sensitivity": sensitivity}
        if is_all_day:
            args["isAllDay"] = True
        if categories:
            args["categories"] = [c.strip() for c in categories.split(",") if c.strip()]
        return _outlook_tool("calendar_meeting", args)

    # --- Helpers ---

    def _add_attendee_args(args, attendees, optional_attendees, resources):
        if attendees:
            args["attendees"] = [f"{a.strip()}@amazon.com" if "@" not in a.strip() else a.strip()
                                 for a in attendees.split(",") if a.strip()]
        if optional_attendees:
            args["optionalAttendees"] = [f"{a.strip()}@amazon.com" if "@" not in a.strip() else a.strip()
                                          for a in optional_attendees.split(",") if a.strip()]
        if resources:
            args["resources"] = [r.strip() for r in resources.split(",") if r.strip()]

    def _add_metadata_args(args, show_as, is_all_day, is_online_meeting,
                           sensitivity, importance, categories,
                           response_requested, allow_new_time_proposals,
                           reminder_minutes):
        if show_as: args["showAs"] = show_as
        if is_all_day: args["isAllDay"] = True
        if is_online_meeting: args["isOnlineMeeting"] = True
        if sensitivity: args["sensitivity"] = sensitivity
        if importance: args["importance"] = importance
        if categories:
            args["categories"] = [c.strip() for c in categories.split(",") if c.strip()]
        if not response_requested: args["responseRequested"] = False
        if not allow_new_time_proposals: args["allowNewTimeProposals"] = False
        if reminder_minutes >= 0: args["reminderMinutes"] = reminder_minutes

    def _build_event_args(operation, subject, start, end,
                          attendees, optional_attendees, resources, location, body,
                          show_as, is_all_day, is_online_meeting, sensitivity,
                          importance, categories, response_requested,
                          allow_new_time_proposals, reminder_minutes,
                          recurrence_pattern, recurrence_interval,
                          recurrence_days, recurrence_end_date):
        args = {"operation": operation, "subject": subject, "start": start, "end": end}
        _add_attendee_args(args, attendees, optional_attendees, resources)
        if location: args["location"] = location
        if body: args["body"] = body
        _add_metadata_args(args, show_as, is_all_day, is_online_meeting,
                           sensitivity, importance, categories,
                           response_requested, allow_new_time_proposals,
                           reminder_minutes)
        if recurrence_pattern:
            rec = {"pattern": recurrence_pattern, "interval": recurrence_interval}
            if recurrence_days:
                rec["daysOfWeek"] = [d.strip() for d in recurrence_days.split(",")]
            if recurrence_end_date:
                rec["endDate"] = recurrence_end_date
            args["recurrence"] = rec
        return args

    return Agent(
        model=_model("light"),
        system_prompt=(
            "You are a calendar specialist. You manage schedules, create/update/delete events, "
            "find available times, book rooms, block focus time, and set event metadata "
            "(categories, sensitivity, show-as status, importance). "
            "Use block_time for personal blocks and OOO. "
            "Use create_event for meetings with attendees. "
            "Return structured data."
        ),
        tools=[view_calendar, create_event, update_event, delete_event,
               search_events, find_time, find_room, shared_calendars, block_time],
        callback_handler=None,
    )
