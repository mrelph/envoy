"""Attaché Strands tools — thin wrappers around AttacheService methods."""
import os
from strands import tool
from service import AttacheService

_svc = AttacheService()


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
    """Add or update a rule in the agent's soul file (~/.attache/soul.md).
    Use this when the user corrects behavior, asks you to change your tone/personality,
    or gives you behavioral directives.

    Args:
        rule: The rule or personality directive to add (will be appended)
    """
    path = os.path.expanduser("~/.attache/soul.md")
    with open(path, "a") as f:
        f.write(f"\n- {rule}\n")
    return f"Updated soul: {rule}"


@tool
def update_attache(preference: str) -> str:
    """Add or update a preference in the user's attache config (~/.attache/attache.md).
    Use this for specific preferences: favorite Slack channels, email rules, key people,
    calendar preferences, EA info, etc.

    Args:
        preference: The preference to add (will be appended)
    """
    path = os.path.expanduser("~/.attache/attache.md")
    with open(path, "a") as f:
        f.write(f"\n- {preference}\n")
    return f"Updated preferences: {preference}"


@tool
def update_personality(fact: str) -> str:
    """Add or update a fact in the user's personality file (~/.attache/personality.md).
    Use this when the user shares information about themselves, their role, or preferences.

    Args:
        fact: The fact to add (will be appended)
    """
    path = os.path.expanduser("~/.attache/personality.md")
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
def send_to_ea(message: str, category: str = "task", ea_alias: str = "") -> str:
    """Send a message to the user's executive assistant via Slack DM (email fallback).
    Use this when the user wants to delegate a task, send a reminder, ask a question, or leave a note for their EA.
    The message is tagged with 'From [User]'s Attaché' so the EA knows it came from the AI assistant.

    Args:
        message: The message to send to the EA (task description, question, reminder, etc.)
        category: Type of message — one of: task, reminder, request, question, note
        ea_alias: EA's Amazon login (optional — reads from attache.md if not provided)
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
    """Save something to Attaché's persistent memory so it's available across sessions.

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
def manage_cron(action: str = "list", name: str = "", schedule: str = "", command: str = "") -> str:
    """Manage Attaché scheduled jobs (cron).

    Args:
        action: 'list' to show all jobs, 'add' to create one, 'remove' to delete by name, 'presets' to show templates
        name: Job name (for add/remove). Used as a comment tag to identify the job.
        schedule: Cron expression (for add). e.g. '0 8 * * 1-5' for weekdays at 8am.
        command: Attaché command to run (for add). e.g. 'digest --days 7 --email'
    """
    import subprocess
    MARKER = "# attache:"

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

    def _attache_path():
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "attache"))
        return script if os.path.exists(script) else "attache"

    if action == "presets":
        return """Available presets:
- **morning-briefing**: Weekdays 8am — Slack DM yourself a full briefing
  `0 8 * * 1-5  attache digest --days 1 --slack --no-display`
- **weekly-digest**: Monday 8am — weekly team digest via Slack DM
  `0 8 * * 1  attache digest --days 7 --slack --no-display`
- **customer-scan**: Weekdays 9am — daily customer email scan via Slack DM
  `0 9 * * 1-5  attache customers --days 1 --slack`
- **inbox-cleanup**: Friday 4pm — weekly cleanup suggestions
  `0 16 * * 5  attache cleanup --days 7`

Add `--email` instead of `--slack` if you prefer email delivery.
Tell me which preset to add, or describe a custom schedule."""

    if action == "list":
        crontab = _get_crontab()
        jobs = [l for l in crontab.splitlines() if MARKER in l]
        if not jobs:
            return "No Attaché cron jobs found. Use action='presets' to see templates, or action='add' to create one."
        lines = []
        for job in jobs:
            tag = job.split(MARKER)[1].strip()
            cron_part = job.split(MARKER)[0].strip()
            lines.append(f"- **{tag}**: `{cron_part}`")
        return f"Attaché scheduled jobs:\n" + "\n".join(lines)

    if action == "add":
        if not name or not schedule or not command:
            return "Need name, schedule, and command. Example: action='add', name='weekly-digest', schedule='0 8 * * 1', command='digest --days 7 --email --no-display'"
        exe = _attache_path()
        full_cmd = f"{schedule}  {exe} {command}  {MARKER} {name}"
        crontab = _get_crontab()
        # Remove existing job with same name
        lines = [l for l in crontab.splitlines() if f"{MARKER} {name}" not in l]
        lines.append(full_cmd)
        err = _set_crontab("\n".join(lines) + "\n")
        return err or f"✓ Added cron job '{name}': `{schedule}` → `attache {command}`"

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


ALL_TOOLS = [
    get_team_digest,
    get_boss_tracker,
    scan_inbox_for_cleanup,
    delete_emails,
    scan_customer_emails,
    scan_slack_channels,
    review_calendar,
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
    draft_email,
    add_subtasks,
    scan_tickets,
    eod_summary,
    weekly_review,
    add_todo_items,
    manage_cron,
    check_replies,
    todo_review,
    remember,
    update_soul,
    update_attache,
    update_personality,
]
