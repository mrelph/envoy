"""Envoy Strands tools — thin wrappers around EnvoyService methods."""
import os
import re
import hashlib
import functools
from strands import tool
from service import EnvoyService

_svc = EnvoyService()

# --- Demo mode masking ---

_DEMO_MODE = os.environ.get("ENVOY_DEMO", "").strip().lower() in ("1", "true", "yes")

_FAKE_FIRST = [
    "Alex", "Jordan", "Morgan", "Casey", "Riley", "Quinn", "Avery", "Taylor",
    "Skyler", "Dakota", "Reese", "Finley", "Rowan", "Sage", "Blair", "Drew",
    "Emery", "Harper", "Kendall", "Logan", "Parker", "Peyton", "Sawyer", "Tatum",
]
_FAKE_LAST = [
    "Chen", "Patel", "Kim", "Santos", "Müller", "Nakamura", "Okafor", "Johansson",
    "Rivera", "Kowalski", "Tanaka", "Gupta", "Larsson", "Moreau", "Novak", "Reyes",
    "Fischer", "Sharma", "Dubois", "Yamamoto", "Costa", "Petrov", "Andersen", "Ortiz",
]
_FAKE_DOMAINS = [
    "acmecorp.com", "globex.io", "initech.co", "umbrella.net", "waynetech.org",
    "starkindustries.com", "oscorp.io", "lexcorp.net", "cyberdyne.co", "soylent.org",
]

def _demo_hash(text: str) -> int:
    """Deterministic hash so same input always maps to same fake output."""
    return int(hashlib.md5(text.lower().encode()).hexdigest(), 16)

def _fake_name(real: str) -> str:
    h = _demo_hash(real)
    return f"{_FAKE_FIRST[h % len(_FAKE_FIRST)]} {_FAKE_LAST[(h >> 8) % len(_FAKE_LAST)]}"

def _fake_alias(real: str) -> str:
    name = _fake_name(real)
    return name.split()[0].lower() + name.split()[1].lower()[:3]

def _fake_email(real: str) -> str:
    local = real.split("@")[0] if "@" in real else real
    h = _demo_hash(local)
    alias = _fake_alias(local)
    domain = _FAKE_DOMAINS[h % len(_FAKE_DOMAINS)]
    return f"{alias}@{domain}"

def _mask_output(text: str) -> str:
    """Replace real PII patterns with deterministic fakes."""
    if not text:
        return text

    # Cache replacements for consistency
    seen = {}

    def _replace_email(m):
        orig = m.group(0)
        if orig not in seen:
            seen[orig] = _fake_email(orig)
        return seen[orig]

    def _replace_alias_ref(m):
        """Replace @alias patterns."""
        orig = m.group(1)
        if orig not in seen:
            seen[orig] = _fake_alias(orig)
        return f"@{seen[orig]}"

    # Emails: user@amazon.com, user@domain.com
    text = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', _replace_email, text)

    # @alias mentions (Slack-style)
    text = re.sub(r'@([a-z]{2,12})\b', _replace_alias_ref, text)

    # Slack channel IDs (C/D/G followed by alphanumeric)
    text = re.sub(r'\b([CDG][A-Z0-9]{8,12})\b',
                  lambda m: f"C{''.join(format(_demo_hash(m.group(1)) >> i & 0xF, 'X') for i in range(10))}",
                  text)

    # Conversation IDs (long base64-ish strings that look like email thread IDs)
    text = re.sub(r'(AAQ[A-Za-z0-9+/=]{20,})',
                  lambda m: f"AAQkDemo{''.join(format(_demo_hash(m.group(1)) >> i & 0xF, 'X') for i in range(16))}==",
                  text)

    # Phone numbers
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '555-867-5309', text)

    # Building codes (SEA54, PDX12, etc.)
    text = re.sub(r'\b([A-Z]{3})\d{1,3}(?:-\d{2}\.\d{3})?\b',
                  lambda m: f"HQ{_demo_hash(m.group(0)) % 99:02d}", text)

    return text

def _demo_wrap(t):
    """If demo mode is on, wrap the tool's inner function to mask output."""
    if not _DEMO_MODE:
        return t
    orig_func = t._tool_func
    @functools.wraps(orig_func)
    def masked(*args, **kwargs):
        result = orig_func(*args, **kwargs)
        return _mask_output(str(result)) if isinstance(result, str) else result
    t._tool_func = masked
    return t


@tool
def get_team_digest(alias: str = "", days: int = 14, selected: str = "") -> str:
    """Generate a digest of your direct reports' recent email activity.

    Args:
        alias: Manager alias (defaults to $USER)
        days: Number of days to look back
        selected: Comma-separated aliases to include (empty = all directs)
    """
    alias = alias or os.environ.get("USER", "")
    selected_list = [s.strip() for s in selected.split(",") if s.strip()] or None
    digest = _svc.generate_digest(alias, days, selected_list, vip_mode=False)
    summary = _svc.generate_ai_summary(digest, alias, days)
    return summary


@tool
def get_boss_tracker(alias: str = "", days: int = 14, levels: int = 3) -> str:
    """Track your management chain's email activity — see what your bosses are focused on.

    Args:
        alias: Your alias (defaults to $USER)
        days: Number of days to look back
        levels: How many management levels up to track
    """
    alias = alias or os.environ.get("USER", "")
    digest = _svc.generate_digest(alias, days, vip_mode=True)
    summary = _svc.generate_ai_summary(digest, alias, days)
    return summary


@tool
def scan_inbox_for_cleanup(days: int = 14, limit: int = 100) -> str:
    """Scan inbox and classify emails as DELETE/REVIEW/KEEP for cleanup.

    Args:
        days: Number of days to look back
        limit: Maximum emails to scan
    """
    alias = os.environ.get("USER", "")
    emails = _svc.fetch_inbox_emails(days, limit)
    classified = _svc.classify_emails(emails, alias)

    lines = []
    for e in classified:
        cls = e.get("classification", "KEEP")
        lines.append(f"[{cls}] {e['from']} — {e['subject']} | Reason: {e.get('reason', '')}")
    return "\n".join(lines) if lines else "No emails found."


@tool
def delete_emails(conversation_ids: str) -> str:
    """Delete emails by moving them to Deleted Items. Requires user confirmation first.

    Args:
        conversation_ids: Comma-separated conversation IDs to delete
    """
    ids = [c.strip() for c in conversation_ids.split(",") if c.strip()]
    if not ids:
        return "No conversation IDs provided."
    result = _svc.delete_emails(ids)
    return f"Deleted {result.get('deleted', 0)} emails, {result.get('failed', 0)} failed."


@tool
def scan_customer_emails(alias: str = "", days: int = 14, team: str = "") -> str:
    """Scan for external customer emails with action items across you and your team.

    Args:
        alias: Your alias (defaults to $USER)
        days: Number of days to look back
        team: Comma-separated team aliases (empty = auto-detect directs)
    """
    alias = alias or os.environ.get("USER", "")
    team_list = [t.strip() for t in team.split(",") if t.strip()] or None
    return _svc.scan_customer_emails(alias, days, team_list)


@tool
def send_email_to_self(subject: str, body: str) -> str:
    """Send an email to the user (e.g., digest, report, summary).

    Args:
        subject: Email subject line
        body: Email body content (markdown or plain text)
    """
    alias = os.environ.get("USER", "")
    _svc.email_digest(body, alias, 0)
    return f"Email sent to {alias}@amazon.com with subject: {subject}"


@tool
def add_todo_items(items: str) -> str:
    """Add action items to Microsoft To-Do.

    Args:
        items: Newline-separated list of action items to add
    """
    action_items = [{"title": line.strip()} for line in items.split("\n") if line.strip()]
    if not action_items:
        return "No items provided."
    _svc.add_to_todo(action_items)
    return f"Added {len(action_items)} items to To-Do."


@tool
def update_soul(rule: str) -> str:
    """Add or update a rule in the agent's soul file (~/.envoy/soul.md).
    Use this when the user corrects behavior, asks you to change your tone/personality,
    or gives you behavioral directives.

    Args:
        rule: The rule or personality directive to add (will be appended)
    """
    path = os.path.expanduser("~/.envoy/soul.md")
    with open(path, "a") as f:
        f.write(f"\n- {rule}\n")
    return f"Updated soul: {rule}"


@tool
def update_envoy(preference: str) -> str:
    """Add or update a preference in the user's envoy config (~/.envoy/envoy.md).
    Use this for specific preferences: favorite Slack channels, email rules, key people,
    calendar preferences, EA info, etc.

    Args:
        preference: The preference to add (will be appended)
    """
    path = os.path.expanduser("~/.envoy/envoy.md")
    with open(path, "a") as f:
        f.write(f"\n- {preference}\n")
    return f"Updated preferences: {preference}"


@tool
def update_personality(fact: str) -> str:
    """Add or update a fact in the user's personality file (~/.envoy/personality.md).
    Use this when the user shares information about themselves, their role, or preferences.

    Args:
        fact: The fact to add (will be appended)
    """
    path = os.path.expanduser("~/.envoy/personality.md")
    with open(path, "a") as f:
        f.write(f"\n- {fact}\n")
    return f"Updated personality: {fact}"


@tool
def scan_slack_channels(channels: str = "", days: int = 7) -> str:
    """Scan Slack channels for critical information, action items, and important updates.

    Args:
        channels: Comma-separated channel IDs (empty = auto-detect unread channels)
        days: Number of days to look back
    """
    ch_list = [c.strip() for c in channels.split(",") if c.strip()] or None
    return _svc.scan_slack(ch_list, days)


@tool
def morning_briefing() -> str:
    """Proactive scan of calendar, to-dos, inbox, Slack, and tickets from the last 24 hours.
    Returns a prioritized snapshot of what needs attention — meetings, pending tasks, unread emails, Slack actions, and open tickets.
    Use this at the start of a session or when the user asks "what did I miss?" or "catch me up".
    """
    alias = os.environ.get("USER", "")
    return _svc.morning_briefing(alias)


@tool
def review_calendar(view: str = "day", days_ahead: int = 1) -> str:
    """Review calendar and get an AI briefing on upcoming meetings with prep suggestions.
    Cross-references email for context on meeting topics.

    Args:
        view: 'day' for today, 'week' for the week ahead
        days_ahead: Number of days to look ahead (used with 'week' view)
    """
    return _svc.review_calendar(view, days_ahead=days_ahead)


@tool
def calendar_events(start_date: str = "", days: int = 1, search: str = "") -> str:
    """Get raw calendar events with exact start/end times. No AI summary — just the events.
    Use this when you need precise event details, times, or want to search/filter events.

    Args:
        start_date: Start date in MM-DD-YYYY format (default: today)
        days: Number of days to fetch (default: 1)
        search: Optional keyword filter — only show events whose subject contains this text
    """
    return _svc.calendar_events(start_date, days, search)


@tool
def outlook_calendar(operation: str, start_date: str = "", end_date: str = "",
                     subject: str = "", start: str = "", end: str = "",
                     attendees: str = "", location: str = "", body: str = "",
                     meeting_id: str = "", meeting_change_key: str = "",
                     rsvp_response: str = "", view: str = "day",
                     resources: str = "", recurrence: str = "",
                     is_all_day: bool = False) -> str:
    """Full calendar control — create, read, update, delete, and RSVP to meetings.

    Args:
        operation: 'create', 'read', 'update', 'delete', or 'search'
        start_date: For view/search — start date MM-DD-YYYY
        end_date: For view — end date MM-DD-YYYY
        subject: Meeting subject (create/update/search)
        start: Meeting start ISO datetime e.g. 2026-03-25T09:00:00.000 (create/update)
        end: Meeting end ISO datetime (create/update)
        attendees: Comma-separated attendee emails (create/update)
        location: Meeting location (create/update)
        body: Meeting description HTML (create/update)
        meeting_id: Meeting ID (read/update/delete)
        meeting_change_key: Change key (update/delete)
        rsvp_response: 'accept', 'decline', or 'tentative' (update)
        view: 'day', 'week', or 'month' (for view operation)
        resources: Comma-separated room emails (create/update)
        recurrence: JSON string for recurrence e.g. '{"pattern":"weekly","daysOfWeek":["Monday"]}'
        is_all_day: Whether this is an all-day event
    """
    args = {"operation": operation}
    if operation == "search":
        return _svc.outlook_tool("calendar_search", {"query": subject, "limit": 25})
    if operation in ("create", "update"):
        if subject: args["subject"] = subject
        if start: args["start"] = start
        if end: args["end"] = end
        if attendees: args["attendees"] = [a.strip() for a in attendees.split(",")]
        if location: args["location"] = location
        if body: args["body"] = body
        if resources: args["resources"] = [r.strip() for r in resources.split(",")]
        if is_all_day: args["isAllDay"] = True
        if recurrence:
            import json as _json
            try: args["recurrence"] = _json.loads(recurrence)
            except: pass
    if meeting_id: args["meetingId"] = meeting_id
    if meeting_change_key: args["meetingChangeKey"] = meeting_change_key
    if rsvp_response: args["rsvpResponse"] = rsvp_response
    if operation == "create" and "start" not in args:
        return "Need at least subject, start, and end to create a meeting."
    # View mode
    if operation not in ("create", "read", "update", "delete", "search"):
        view_args = {"view": view, "start_date": start_date or __import__("datetime").datetime.now().strftime("%m-%d-%Y")}
        if end_date: view_args["end_date"] = end_date
        return _svc.outlook_tool("calendar_view", view_args)
    return _svc.outlook_tool("calendar_meeting", args)


@tool
def outlook_email(operation: str, conversation_id: str = "", query: str = "",
                  to: str = "", subject: str = "", body: str = "",
                  cc: str = "", bcc: str = "", folder: str = "",
                  limit: int = 25, mark_as: str = "",
                  item_id: str = "", item_change_key: str = "",
                  reply_all: bool = False, target_folder: str = "") -> str:
    """Full email control — read, search, send, reply, forward, draft, move, and manage emails.

    Args:
        operation: 'inbox', 'read', 'search', 'send', 'reply', 'forward', 'draft', 'move', 'folders', 'update'
        conversation_id: Conversation ID (read/move)
        query: Search query (search)
        to: Comma-separated recipient emails (send/reply/forward/draft)
        subject: Email subject (send/draft)
        body: Email body HTML (send/reply/forward/draft)
        cc: Comma-separated CC emails (send/draft)
        bcc: Comma-separated BCC emails (send/draft)
        folder: Folder name — inbox, sentitems, drafts, archive, junkemail, deleteditems (folders)
        limit: Max results (inbox/search)
        mark_as: 'read' or 'unread' (read)
        item_id: Item ID (reply/forward/update)
        item_change_key: Item change key (reply/forward/update)
        reply_all: Reply to all recipients (reply)
        target_folder: Target folder for move operation
    """
    def _emails(s): return [e.strip() for e in s.split(",") if e.strip()]

    if operation == "inbox":
        return _svc.outlook_tool("email_inbox", {"limit": limit})
    elif operation == "read":
        args = {"conversationId": conversation_id}
        if mark_as: args["markAs"] = mark_as
        return _svc.outlook_tool("email_read", args)
    elif operation == "search":
        args = {"query": query, "limit": limit}
        if folder: args["folder"] = folder
        return _svc.outlook_tool("email_search", args)
    elif operation == "send":
        return _svc.outlook_tool("email_send", {"to": _emails(to), "subject": subject, "body": body,
                                                 **({} if not cc else {"cc": _emails(cc)}),
                                                 **({} if not bcc else {"bcc": _emails(bcc)})})
    elif operation == "reply":
        return _svc.outlook_tool("email_reply", {"itemId": item_id, "itemChangeKey": item_change_key,
                                                  "body": body, "replyAll": reply_all})
    elif operation == "forward":
        return _svc.outlook_tool("email_forward", {"itemId": item_id, "itemChangeKey": item_change_key,
                                                    "to": _emails(to), **({"body": body} if body else {})})
    elif operation == "draft":
        args = {"operation": "create", "to": _emails(to), "subject": subject, "body": body}
        if cc: args["cc"] = _emails(cc)
        return _svc.outlook_tool("email_draft", args)
    elif operation == "move":
        return _svc.outlook_tool("email_move", {"conversationId": conversation_id, "targetFolder": target_folder})
    elif operation == "folders":
        if folder:
            return _svc.outlook_tool("email_folders", {"folder": folder, "limit": limit})
        return _svc.outlook_tool("email_list_folders", {})
    elif operation == "update":
        return _svc.outlook_tool("email_update", {"itemId": item_id, "itemChangeKey": item_change_key})
    return f"Unknown operation '{operation}'. Use: inbox, read, search, send, reply, forward, draft, move, folders."


@tool
def send_to_ea(message: str, category: str = "task", ea_alias: str = "") -> str:
    """Send a message to the user's executive assistant via Slack DM (email fallback).
    Use this when the user wants to delegate a task, send a reminder, ask a question, or leave a note for their EA.
    The message is tagged with 'From [User]'s Envoy' so the EA knows it came from the AI assistant.

    Args:
        message: The message to send to the EA (task description, question, reminder, etc.)
        category: Type of message — one of: task, reminder, request, question, note
        ea_alias: EA's Amazon login (optional — reads from envoy.md if not provided)
    """
    return _svc.send_to_ea(message, ea_alias=ea_alias or None, category=category)


@tool
def send_slack_dm(recipient: str, message: str) -> str:
    """Send a Slack direct message to anyone by their Amazon login/alias.
    Use this when the user wants to DM someone on Slack — a teammate, manager, or anyone.

    Args:
        recipient: The Amazon login/alias of the person to DM
        message: The message text to send
    """
    return _svc.send_slack_dm(recipient, message)


@tool
def find_time(attendees: str = "", duration: int = 30, days_ahead: int = 5) -> str:
    """Find available meeting times across multiple attendees' calendars.

    Args:
        attendees: Comma-separated email addresses to check availability for
        duration: Meeting duration in minutes
        days_ahead: How many days ahead to search
    """
    att_list = [a.strip() for a in attendees.split(",") if a.strip()]
    if not att_list:
        return "No attendees provided."
    return _svc.find_available_times(att_list, duration, days_ahead)


@tool
def book_meeting_room(building: str, start_time: str, end_time: str) -> str:
    """Find available meeting rooms in a building for a time slot.

    Args:
        building: Building code (e.g., SEA54, JFK27)
        start_time: Start time in ISO format
        end_time: End time in ISO format
    """
    return _svc.book_room(building, start_time, end_time)


@tool
def create_meeting(subject: str, start: str, end: str, attendees: str = "", location: str = "", body: str = "") -> str:
    """Create a calendar meeting with attendees and optional room.

    Args:
        subject: Meeting title
        start: Start time in ISO format (YYYY-MM-DDTHH:MM:SS.SSS)
        end: End time in ISO format
        attendees: Comma-separated attendee email addresses
        location: Meeting location or room
        body: Meeting description/agenda in HTML
    """
    att_list = [a.strip() for a in attendees.split(",") if a.strip()] if attendees else []
    return _svc.create_meeting(subject, start, end, att_list, location, body)


@tool
def mark_slack_read(channel_ids: str = "") -> str:
    """Mark Slack channels as read. Call this after presenting a Slack scan to clean up notifications.

    Args:
        channel_ids: Comma-separated channel IDs (empty = mark all unread channels)
    """
    ids = [c.strip() for c in channel_ids.split(",") if c.strip()] if channel_ids else None
    return _svc.mark_slack_read(ids)


@tool
def search_slack_messages(query: str) -> str:
    """Search Slack message history for past conversations, decisions, or information.

    Args:
        query: Search query — supports Slack search syntax (in:#channel, from:@user, etc.)
    """
    return _svc.search_slack(query)


@tool
def reply_to_email(conversation_id: str, body: str, reply_all: bool = False) -> str:
    """Reply to an email thread. Use conversation IDs from previous email scans.

    Args:
        conversation_id: The conversation ID of the email to reply to
        body: Reply body text
        reply_all: Whether to reply to all recipients
    """
    return _svc.reply_to_email(conversation_id, body, reply_all)


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email to one or more recipients. Always confirm with user before calling.

    Args:
        to: Comma-separated recipient email addresses
        subject: Email subject
        body: Email body in HTML format
    """
    to_list = [t.strip() for t in to.split(",") if t.strip()]
    return _svc.send_email(to_list, subject, body)


@tool
def draft_email(to: str, subject: str, body: str) -> str:
    """Create an email draft without sending it. User can review and send later.

    Args:
        to: Comma-separated recipient email addresses
        subject: Email subject
        body: Email body in HTML format
    """
    to_list = [t.strip() for t in to.split(",") if t.strip()]
    return _svc.draft_email(to_list, subject, body)


@tool
def add_subtasks(list_name: str, task_title: str, subtasks: str) -> str:
    """Add checklist subtasks to an existing To-Do task.

    Args:
        list_name: Name of the To-Do list containing the task
        task_title: Title (or partial title) of the task to add subtasks to
        subtasks: Newline-separated list of subtask items
    """
    items = [s.strip() for s in subtasks.split("\n") if s.strip()]
    if not items:
        return "No subtasks provided."
    return _svc.add_todo_subtasks(list_name, task_title, items)


@tool
def teamsnap_auth() -> str:
    """Authenticate with TeamSnap via AWS-hosted OAuth.
    Call this before using any other TeamSnap tools if not yet authenticated.
    """
    return _svc.teamsnap_auth()


@tool
def teamsnap_schedule(team_id: str = "", start_date: str = "", end_date: str = "") -> str:
    """Get TeamSnap schedule/events. Lists teams if no team_id given.

    Args:
        team_id: TeamSnap team ID (empty = list all teams)
        start_date: Filter from date (ISO 8601, optional)
        end_date: Filter until date (ISO 8601, optional)
    """
    return _svc.get_teamsnap_schedule(team_id, start_date, end_date)


@tool
def teamsnap_roster(team_id: str) -> str:
    """Get the roster (players and coaches) for a TeamSnap team.

    Args:
        team_id: TeamSnap team ID
    """
    return _svc.get_teamsnap_roster(team_id)


@tool
def teamsnap_availability(event_id: str) -> str:
    """Get availability responses for a TeamSnap event.

    Args:
        event_id: TeamSnap event ID
    """
    return _svc.get_teamsnap_availability(event_id)


@tool
def scan_tickets(alias: str = "") -> str:
    """Scan open tickets and SIMs assigned to you or your team. Flags high-severity and stale tickets.

    Args:
        alias: Your alias (defaults to $USER)
    """
    return _svc.scan_tickets(alias or os.environ.get("USER", ""))


@tool
def eod_summary() -> str:
    """Generate an end-of-day summary — what happened today, what's pending, what to prep for tomorrow.
    Use this at the end of the workday or when the user asks to wrap up.
    """
    return _svc.eod_summary(os.environ.get("USER", ""))


@tool
def weekly_review() -> str:
    """Generate a weekly review — meetings, email volume, action items, patterns, and next week focus.
    Use this on Fridays or when the user asks for a week-in-review.
    """
    return _svc.weekly_review(os.environ.get("USER", ""))


@tool
def remember(text: str, entry_type: str = "action") -> str:
    """Save something to Envoy's persistent memory so it's available across sessions.

    Args:
        text: What to remember (key actions, decisions, context, user preferences). Keep concise.
        entry_type: 'action' for things done, 'context' for important background, 'decision' for user choices.
    """
    return _svc.remember(text, entry_type)


@tool
def todo_review() -> str:
    """Review the To-Do list, cross-reference items with email/Slack/calendar, and suggest a burndown plan.
    Use when the user wants to tackle their to-do list, asks "what should I work on?", or wants to prioritize tasks.
    """
    return _svc.todo_review(os.environ.get("USER", ""))


@tool
def check_replies() -> str:
    """Check for replies to messages the agent previously sent via Slack or email.
    Scans sent message history and looks for responses in threads or email chains.
    Use this when the user asks "did anyone reply?" or "any responses?" or during briefings.
    """
    return _svc.check_replies()


@tool
def recommend_responses(days: int = 3) -> str:
    """Scan recent emails and Slack DMs sent directly to the user and generate recommended responses.
    Returns AI-drafted replies with urgency levels. Use when the user asks "what should I reply to?"
    or "any messages I need to respond to?" or "draft my replies".

    Args:
        days: Number of days to look back (default 3)
    """
    return _svc.recommend_responses(os.environ.get("USER", ""), days)


@tool
def learn_response(context: str, response: str, medium: str = "email") -> str:
    """Save a response the user approved/sent so future recommendations match their style.
    Call this AFTER the user sends or approves a recommended response.

    Args:
        context: Brief description of what the message was about (sender + topic)
        response: The actual response text that was sent
        medium: "email" or "slack"
    """
    return _svc.learn_response(context, response, medium)


@tool
def manage_cron(action: str = "list", name: str = "", schedule: str = "", command: str = "") -> str:
    """Manage Envoy scheduled jobs (cron).

    Args:
        action: 'list' to show all jobs, 'add' to create one, 'remove' to delete by name, 'presets' to show templates
        name: Job name (for add/remove). Used as a comment tag to identify the job.
        schedule: Cron expression (for add). e.g. '0 8 * * 1-5' for weekdays at 8am.
        command: Envoy command to run (for add). e.g. 'digest --days 7 --email'
    """
    import subprocess
    MARKER = "# envoy:"

    def _get_crontab():
        try:
            return subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        except Exception:
            return ""

    def _set_crontab(content):
        proc = subprocess.run(["crontab", "-"], input=content, capture_output=True, text=True)
        if proc.returncode != 0:
            return f"Error: {proc.stderr}"
        return None

    def _envoy_path():
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "envoy"))
        return script if os.path.exists(script) else "envoy"

    if action == "presets":
        return """Available presets:
- **morning-briefing**: Weekdays 8am — Slack DM yourself a full briefing
  `0 8 * * 1-5  envoy digest --days 1 --slack --no-display`
- **weekly-digest**: Monday 8am — weekly team digest via Slack DM
  `0 8 * * 1  envoy digest --days 7 --slack --no-display`
- **customer-scan**: Weekdays 9am — daily customer email scan via Slack DM
  `0 9 * * 1-5  envoy customers --days 1 --slack`
- **inbox-cleanup**: Friday 4pm — weekly cleanup suggestions
  `0 16 * * 5  envoy cleanup --days 7`

Add `--email` instead of `--slack` if you prefer email delivery.
Tell me which preset to add, or describe a custom schedule."""

    if action == "list":
        crontab = _get_crontab()
        jobs = [l for l in crontab.splitlines() if MARKER in l]
        if not jobs:
            return "No Envoy cron jobs found. Use action='presets' to see templates, or action='add' to create one."
        lines = []
        for job in jobs:
            tag = job.split(MARKER)[1].strip()
            cron_part = job.split(MARKER)[0].strip()
            lines.append(f"- **{tag}**: `{cron_part}`")
        return f"Envoy scheduled jobs:\n" + "\n".join(lines)

    if action == "add":
        if not name or not schedule or not command:
            return "Need name, schedule, and command. Example: action='add', name='weekly-digest', schedule='0 8 * * 1', command='digest --days 7 --email --no-display'"
        exe = _envoy_path()
        full_cmd = f"{schedule}  {exe} {command}  {MARKER} {name}"
        crontab = _get_crontab()
        # Remove existing job with same name
        lines = [l for l in crontab.splitlines() if f"{MARKER} {name}" not in l]
        lines.append(full_cmd)
        err = _set_crontab("\n".join(lines) + "\n")
        return err or f"✓ Added cron job '{name}': `{schedule}` → `envoy {command}`"

    if action == "remove":
        if not name:
            return "Need name of job to remove. Use action='list' to see current jobs."
        crontab = _get_crontab()
        lines = crontab.splitlines()
        filtered = [l for l in lines if f"{MARKER} {name}" not in l]
        if len(filtered) == len(lines):
            return f"No job named '{name}' found."
        err = _set_crontab("\n".join(filtered) + "\n")
        return err or f"✓ Removed cron job '{name}'"

    return "Unknown action. Use 'list', 'add', 'remove', or 'presets'."


_ALL_TOOLS_RAW = [
    get_team_digest,
    get_boss_tracker,
    scan_inbox_for_cleanup,
    delete_emails,
    scan_customer_emails,
    scan_slack_channels,
    review_calendar,
    calendar_events,
    outlook_calendar,
    outlook_email,
    morning_briefing,
    send_email_to_self,
    send_to_ea,
    send_slack_dm,
    find_time,
    book_meeting_room,
    create_meeting,
    mark_slack_read,
    search_slack_messages,
    reply_to_email,
    send_email,
    draft_email,
    add_subtasks,
    scan_tickets,
    eod_summary,
    weekly_review,
    add_todo_items,
    manage_cron,
    check_replies,
    recommend_responses,
    learn_response,
    todo_review,
    remember,
    update_soul,
    update_envoy,
    update_personality,
    teamsnap_auth,
    teamsnap_schedule,
    teamsnap_roster,
    teamsnap_availability,
]

ALL_TOOLS = [_demo_wrap(t) for t in _ALL_TOOLS_RAW] if _DEMO_MODE else _ALL_TOOLS_RAW
