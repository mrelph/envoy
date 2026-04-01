"""Worker agents — domain-specific Strands agents with focused toolsets.

The supervisor routes natural language requests to these workers.
Each worker has 5-8 tools and runs on an appropriate model tier.
"""

import os
from strands import Agent, tool
from strands.models import BedrockModel
from agents.base import model_for

_USER = os.environ.get('USER', '')


def _model(tier: str) -> BedrockModel:
    return BedrockModel(
        model_id=model_for(tier),
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
    )


# ============================================================
# Email Worker (Sonnet) — inbox, search, send, reply, cleanup
# ============================================================

def _create_email_worker():
    from agents import email as email_mod
    from agents import workflows as wf
    import asyncio

    def _format_html(text: str) -> str:
        """Convert plain text to simple HTML with paragraph breaks."""
        if text.strip().startswith("<"):
            return text  # already HTML
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        return "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{text}</p>"

    @tool
    def inbox(days: int = 1, limit: int = 30) -> str:
        """Fetch recent inbox emails. Results are numbered — use the number to reference specific emails.
        Args:
            days: Days to look back
            limit: Max emails to return
        """
        emails = asyncio.run(email_mod.fetch_inbox(days, limit))
        if not emails:
            return "No emails found."
        return "\n".join(
            f"[{i+1}] {e['from']}: {e['subject']} ({e['date']}) [id:{e.get('conversationId','')}]"
            for i, e in enumerate(emails[:limit])
        )

    @tool
    def read_email(conversation_id: str) -> str:
        """Read the full content of an email thread.
        Args:
            conversation_id: Conversation ID from inbox or search results
        """
        from tools import _outlook_tool
        return _outlook_tool("email_read", {"conversationId": conversation_id})

    @tool
    def search_email(query: str, folder: str = "", limit: int = 25) -> str:
        """Search emails by keyword, sender, subject, or date.
        Args:
            query: Search query (e.g. "from:alice budget", "project update")
            folder: Optional folder: inbox, sentitems, drafts, archive
            limit: Max results
        """
        from tools import _outlook_tool
        args = {"query": query, "limit": limit}
        if folder:
            args["folder"] = folder
        return _outlook_tool("email_search", args)

    @tool
    def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> str:
        """Send a new email.
        Args:
            to: Comma-separated recipient emails
            subject: Email subject
            body: Email body (plain text — will be formatted as HTML automatically)
            cc: Comma-separated CC emails
            bcc: Comma-separated BCC emails
        """
        from tools import _outlook_tool
        def _emails(s): return [e.strip() for e in s.split(",") if e.strip()]
        args = {"to": _emails(to), "subject": subject, "body": _format_html(body)}
        if cc: args["cc"] = _emails(cc)
        if bcc: args["bcc"] = _emails(bcc)
        return _outlook_tool("email_send", args)

    @tool
    def reply_email(conversation_id: str, body: str, reply_all: bool = False) -> str:
        """Reply to an email thread. Automatically finds the latest message and replies in-thread.
        Args:
            conversation_id: Conversation ID from reading or searching the email
            body: Reply body (plain text — will be formatted as HTML automatically)
            reply_all: Reply to all recipients
        """
        return asyncio.run(email_mod.reply_to_email(conversation_id, _format_html(body), reply_all))

    @tool
    def forward_email(item_id: str, item_change_key: str, to: str, body: str = "") -> str:
        """Forward an email.
        Args:
            item_id: Item ID from reading the email
            item_change_key: Change key from reading the email
            to: Comma-separated recipient emails
            body: Optional additional message (plain text — will be formatted as HTML)
        """
        from tools import _outlook_tool
        def _emails(s): return [e.strip() for e in s.split(",") if e.strip()]
        args = {"itemId": item_id, "itemChangeKey": item_change_key, "to": _emails(to)}
        if body: args["body"] = _format_html(body)
        return _outlook_tool("email_forward", args)

    @tool
    def manage_email(operation: str, conversation_id: str = "", item_id: str = "",
                     item_change_key: str = "", target_folder: str = "",
                     flag_status: str = "", categories: str = "",
                     query: str = "", folder: str = "", limit: int = 25) -> str:
        """Move, flag, categorize emails, list folders, search contacts, or get attachments.
        Args:
            operation: move, flag, folders, contacts, attachments, draft
            conversation_id: For move
            item_id: For flag/attachments
            item_change_key: For flag
            target_folder: For move (e.g. archive, deleteditems)
            flag_status: Flagged, Complete, or NotFlagged
            categories: Comma-separated category names
            query: For contacts search
            folder: For folder listing
            limit: Max results
        """
        from tools import _outlook_tool
        def _emails(s): return [e.strip() for e in s.split(",") if e.strip()]
        ops = {
            "move": lambda: _outlook_tool("email_move", {"conversationId": conversation_id, "targetFolder": target_folder}),
            "flag": lambda: _outlook_tool("email_update", {"itemId": item_id, "itemChangeKey": item_change_key,
                **({"flag": {"status": flag_status}} if flag_status else {}),
                **({"categories": _emails(categories)} if categories else {})}),
            "folders": lambda: _outlook_tool("email_folders", {"folder": folder, "limit": limit}) if folder else _outlook_tool("email_list_folders", {}),
            "contacts": lambda: _outlook_tool("email_contacts", {"query": query, "limit": limit}),
            "attachments": lambda: _outlook_tool("email_attachments", {"attachmentId": item_id}),
        }
        fn = ops.get(operation)
        return fn() if fn else f"Unknown operation: {operation}"

    @tool
    def cleanup(days: int = 14, limit: int = 100) -> str:
        """Classify inbox emails as DELETE/REVIEW/KEEP for cleanup.
        Args:
            days: Days to look back
            limit: Max emails to scan
        """
        emails = asyncio.run(email_mod.fetch_inbox(days, limit))
        classified = email_mod.classify_emails(emails, _USER)
        return "\n".join(f"[{e.get('classification','KEEP')}] {e['from']} — {e['subject']} | {e.get('reason','')}" for e in classified) or "No emails found."

    @tool
    def delete(conversation_ids: str) -> str:
        """Delete emails by moving to Deleted Items.
        Args:
            conversation_ids: Comma-separated conversation IDs
        """
        ids = [c.strip() for c in conversation_ids.split(",") if c.strip()]
        if not ids:
            return "No IDs provided."
        result = asyncio.run(email_mod.delete_emails(ids))
        return f"Deleted {result.get('deleted',0)}, {result.get('failed',0)} failed."

    @tool
    def customer_scan(alias: str = "", days: int = 14, team: str = "") -> str:
        """Scan for external customer emails with action items.
        Args:
            alias: Your alias (default: $USER)
            days: Days to look back
            team: Comma-separated team aliases
        """
        alias = alias or _USER
        team_list = [t.strip() for t in team.split(",") if t.strip()] or None
        return asyncio.run(email_mod.scan_customer_emails(alias, days, team_list))

    @tool
    def digest(alias: str = "", days: int = 14, selected: str = "", vip: bool = False) -> str:
        """Generate team email digest or boss tracker.
        Args:
            alias: Manager alias (default: $USER)
            days: Days to look back
            selected: Comma-separated aliases to include
            vip: Track management chain instead of directs
        """
        alias = alias or _USER
        sel = [s.strip() for s in selected.split(",") if s.strip()] or None
        raw = wf.generate_digest(alias, days, sel, vip_mode=vip)
        return wf.generate_ai_summary(raw, alias, days)

    @tool
    def send_to_self(subject: str, body: str) -> str:
        """Email a report/digest to yourself.
        Args:
            subject: Email subject
            body: Email body (markdown or plain text)
        """
        asyncio.run(email_mod.email_digest(body, _USER, 0))
        return f"Email sent to {_USER}@amazon.com"

    return Agent(
            model=_model("medium"),
            system_prompt="You are an email specialist. You fetch, search, classify, send, and manage emails. Be concise and action-oriented.",
            tools=[inbox, read_email, search_email, send_email, reply_email, forward_email, manage_email, cleanup, delete, customer_scan, digest, send_to_self],
            callback_handler=None,
        )


# ============================================================
# Comms Worker (Sonnet) — Slack + EA delegation
# ============================================================

def _create_comms_worker():
    from agents import slack_agent as slack_mod
    from agents import workflows as wf
    import asyncio

    @tool
    def scan_channels(channels: str = "", days: int = 7) -> str:
        """Scan Slack channels for activity and action items. Resolves user names and includes thread replies.
        Args:
            channels: Comma-separated channel IDs (empty = auto-detect)
            days: Days to look back
        """
        ch_list = [c.strip() for c in channels.split(",") if c.strip()] or None
        return asyncio.run(slack_mod.scan(ch_list, days))

    @tool
    def send_message(recipient: str, message: str, thread_ts: str = "") -> str:
        """Send a Slack message to a person, group, or channel. Supports threaded replies.
        Args:
            recipient: Single alias, comma-separated aliases for group DM, or channel ID (C/G/D prefix)
            message: Message text
            thread_ts: Parent message timestamp for threaded reply (optional)
        """
        return asyncio.run(slack_mod.send_dm(recipient, message, thread_ts))

    @tool
    def mark_read(channel_ids: str = "") -> str:
        """Mark Slack channels as read.
        Args:
            channel_ids: Comma-separated channel IDs (empty = all unread)
        """
        ids = [c.strip() for c in channel_ids.split(",") if c.strip()] if channel_ids else None
        return asyncio.run(slack_mod.mark_read(ids))

    @tool
    def search_messages(query: str) -> str:
        """Search Slack message history.
        Args:
            query: Search query (supports in:#channel, from:@user)
        """
        return asyncio.run(slack_mod.search_slack(query))

    @tool
    def send_to_ea(message: str, category: str = "task", ea_alias: str = "") -> str:
        """Send a task/message to your EA via Slack or email.
        Args:
            message: Message to send
            category: task, reminder, request, question, note
            ea_alias: EA alias (reads from config if empty)
        """
        return wf.send_to_ea(message, ea_alias=ea_alias or None, category=category)

    @tool
    def slack_extras(operation: str, channel_id: str = "", timestamp: str = "",
                     emoji: str = "eyes", text: str = "", thread_ts: str = "",
                     file_id: str = "", slack_url: str = "",
                     list_id: str = "", item_id: str = "", limit: int = 50) -> str:
        """Additional Slack operations — reactions, drafts, file downloads, channel sections, Slack Lists.
        Args:
            operation: react, draft, list_drafts, download_file, sections, list_items, list_item_detail
            channel_id: Channel ID (for react, draft)
            timestamp: Message timestamp (for react)
            emoji: Emoji name without colons (for react, default: eyes)
            text: Draft message text (for draft)
            thread_ts: Thread timestamp (for draft threaded reply)
            file_id: Slack file/canvas ID (for download_file)
            slack_url: Slack message URL (alternative to channel_id+timestamp for react)
            list_id: Slack List ID (for list_items, list_item_detail)
            item_id: Slack List item ID (for list_item_detail)
            limit: Max items (for list_items)
        """
        ops = {
            "react": lambda: asyncio.run(slack_mod.add_reaction(channel_id, timestamp, emoji, slack_url)),
            "draft": lambda: asyncio.run(slack_mod.create_slack_draft(channel_id, text, thread_ts)),
            "list_drafts": lambda: asyncio.run(slack_mod.list_slack_drafts()),
            "download_file": lambda: asyncio.run(slack_mod.download_file(file_id)),
            "sections": lambda: asyncio.run(slack_mod.get_sections()),
            "list_items": lambda: asyncio.run(slack_mod.get_slack_list_items(list_id, limit)),
            "list_item_detail": lambda: asyncio.run(slack_mod.get_slack_list_item(list_id, item_id)),
        }
        fn = ops.get(operation)
        return fn() if fn else f"Unknown operation: {operation}"

    return Agent(
            model=_model("medium"),
            system_prompt="You are a Slack and communications specialist. You scan channels (with user name resolution and thread context), send messages (DMs, channels, threaded replies), search, add reactions, manage drafts, download files, and delegate to EAs. Be concise.",
            tools=[scan_channels, send_message, mark_read, search_messages, send_to_ea, slack_extras],
            callback_handler=None,
        )


# ============================================================
# Calendar Worker (Haiku) — schedule, meetings, rooms
# ============================================================

def _create_calendar_worker():
    from agents import calendar as cal_mod
    import asyncio

    @tool
    def view(view_type: str = "day", days_ahead: int = 1) -> str:
        """View calendar with AI briefing.
        Args:
            view_type: 'day' or 'week'
            days_ahead: Days to look ahead
        """
        return asyncio.run(cal_mod.review(view_type, days_ahead=days_ahead))

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
            return asyncio.run(cal_mod.find_available_times(att_list, duration, days_ahead))
        if operation == "find_room":
            return asyncio.run(cal_mod.book_room(building, start, end))
        if operation == "search":
            return _outlook_tool("calendar_search", {"query": subject, "limit": 25})
        if operation == "shared_calendars":
            return asyncio.run(cal_mod.list_shared_calendars())
        if operation == "view_shared":
            return asyncio.run(cal_mod.view_shared_calendar(calendar_id, start_date, days_ahead))
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
        return asyncio.run(internal.find_rooms(building, start_time=start_time, end_time=end_time))

    return Agent(
            model=_model("light"),
            system_prompt="You are a calendar specialist. You view schedules, create meetings (including recurring with optional attendees and room resources), find available times, book rooms, and access shared calendars. Use Outlook for calendar operations and meetings.amazon.com only for finding meeting rooms. Return structured data.",
            tools=[view, calendar_operation, find_meeting_room],
            callback_handler=None,
        )


# ============================================================
# Productivity Worker (Sonnet) — todos, tickets, memory, cron
# ============================================================

def _create_productivity_worker():
    from agents import todo as todo_mod, tickets as tix_mod, memory2 as mem_mod
    from agents import workflows as wf
    import asyncio

    @tool
    def todo_items(operation: str = "list", items: str = "", list_name: str = "",
                   task_title: str = "", subtasks: str = "",
                   due_date: str = "", importance: str = "", new_title: str = "",
                   status: str = "", body: str = "") -> str:
        """Manage To-Do items — list, add, complete, update, delete, or add subtasks.
        Args:
            operation: list, add, complete, update, delete, subtasks, review
            items: Newline-separated items to add (for add)
            list_name: To-Do list name
            task_title: Task title (for complete/update/delete/subtasks)
            subtasks: Newline-separated subtask items
            due_date: Due date ISO format (for add/update)
            importance: low, normal, or high (for add/update)
            new_title: New title (for update)
            status: notStarted, inProgress, completed, waitingOnOthers, deferred (for update)
            body: Task body/notes (for add/update)
        """
        if operation == "review":
            return wf.todo_review(_USER)
        if operation == "add":
            action_items = []
            for l in items.split("\n"):
                l = l.strip()
                if not l:
                    continue
                item = {"title": l}
                if due_date: item["due_date"] = due_date
                if importance: item["importance"] = importance
                if body: item["body"] = body
                action_items.append(item)
            if not action_items:
                return "No items provided."
            ok = asyncio.run(todo_mod.add_tasks(action_items, list_name or None))
            return f"Added {len(action_items)} items." if ok else "Failed to add items."
        if operation == "complete":
            return asyncio.run(todo_mod.complete_task(list_name or "Envoy Action Items", task_title))
        if operation == "update":
            return asyncio.run(todo_mod.update_task(
                list_name or "Envoy Action Items", task_title,
                new_title=new_title, due_date=due_date, importance=importance,
                status=status, body=body))
        if operation == "delete":
            return asyncio.run(todo_mod.delete_task(list_name or "Envoy Action Items", task_title))
        if operation == "subtasks":
            sub_list = [s.strip() for s in subtasks.split("\n") if s.strip()]
            return asyncio.run(todo_mod.add_subtasks(list_name, task_title, sub_list))
        return asyncio.run(todo_mod.fetch_todos())

    @tool
    def tickets(alias: str = "") -> str:
        """Scan open tickets assigned to you or your team.
        Args:
            alias: Your alias (default: $USER)
        """
        return asyncio.run(tix_mod.scan_tickets(alias or _USER))

    @tool
    def remember_item(text: str, entry_type: str = "action") -> str:
        """Save something to persistent memory.
        Args:
            text: What to remember
            entry_type: action, context, or decision
        """
        return mem_mod.remember(text, entry_type)

    @tool
    def cron_jobs(action: str = "list", name: str = "", schedule: str = "", command: str = "") -> str:
        """Manage scheduled cron jobs.
        Args:
            action: list, add, remove, presets
            name: Job name
            schedule: Cron expression
            command: Envoy command
        """
        from tools import manage_cron
        return manage_cron(action=action, name=name, schedule=schedule, command=command)

    @tool
    def briefing_report(type: str = "morning") -> str:
        """Generate a briefing — morning, end-of-day, or weekly.
        Args:
            type: morning, eod, weekly
        """
        funcs = {"morning": wf.morning_briefing, "eod": wf.eod_summary, "weekly": wf.weekly_review}
        fn = funcs.get(type, wf.morning_briefing)
        return fn(_USER)

    return Agent(
            model=_model("medium"),
            system_prompt="You are a productivity specialist. You manage to-dos (list, add with due dates/importance, complete, update, delete), scan tickets, maintain memory, run briefings, and manage cron jobs. Be action-oriented.",
            tools=[todo_items, tickets, remember_item, cron_jobs, briefing_report],
            callback_handler=None,
        )


# ============================================================
# Research Worker (Haiku) — internal websites, people lookup
# ============================================================

def _create_research_worker():
    from agents import internal, people as people_mod
    import asyncio

    @tool
    def lookup_person(alias: str) -> str:
        """Look up someone's Phonetool profile.
        Args:
            alias: Amazon login alias
        """
        async def _fetch():
            from agents.base import builder
            async with builder() as session:
                result = await session.call_tool("ReadInternalWebsites",
                    {"inputs": [f"https://phonetool.amazon.com/users/{alias}"]})
                return result.content[0].text if result.content else f"No profile for {alias}"
        return asyncio.run(_fetch())

    @tool
    def kingpin(goal_id: str, children: bool = False) -> str:
        """Look up a Kingpin goal. Set children=True to see child goals.
        Args:
            goal_id: Kingpin goal ID
            children: Also fetch child goals/milestones
        """
        result = asyncio.run(internal.get_goal(goal_id))
        if children:
            result += "\n\n## Children\n" + asyncio.run(internal.get_goal_children(goal_id))
        return result

    @tool
    def wiki(path: str) -> str:
        """Read an internal Wiki page.
        Args:
            path: Wiki path after /bin/view/
        """
        return asyncio.run(internal.get_wiki(path))

    @tool
    def taskei(task_id: str) -> str:
        """Look up a Taskei/SIM task.
        Args:
            task_id: Task ID like XYZ-1234
        """
        return asyncio.run(internal.get_task(task_id))

    @tool
    def broadcast(query: str) -> str:
        """Search internal Broadcast videos.
        Args:
            query: Search terms
        """
        return asyncio.run(internal.search_broadcast(query))

    @tool
    def tiny(shortlink: str) -> str:
        """Resolve a tiny.amazon.com shortlink.
        Args:
            shortlink: The shortlink code
        """
        return asyncio.run(internal.resolve_tiny(shortlink))

    @tool
    def web_search(query: str, count: int = 5) -> str:
        """Search the web using Brave Search. Use for external/public information.
        Args:
            query: Search query
            count: Number of results (default 5, max 20)
        """
        import os, requests as req
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return "BRAVE_API_KEY not set. Add it to ~/.envoy/.env or your environment."
        resp = req.get("https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": min(count, 20)}, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("web", {}).get("results", [])
        if not results:
            return f"No results for: {query}"
        return "\n\n".join(
            f"**{r['title']}**\n{r.get('description', '')}\n{r['url']}"
            for r in results
        )

    return Agent(
            model=_model("medium"),
            system_prompt="You are a research specialist. You look up people, Kingpin goals, wiki pages, Taskei tasks, Broadcast videos, resolve links, and search the web. Return data concisely.",
            tools=[lookup_person, kingpin, wiki, taskei, broadcast, tiny, web_search],
            callback_handler=None,
        )


# ============================================================
# SharePoint Worker (Sonnet) — files, search, lists on SharePoint/OneDrive
# ============================================================

def _create_sharepoint_worker():
    from agents import sharepoint_agent as sp
    import asyncio
    import json

    @tool
    def sp_search(query: str, limit: int = 20) -> str:
        """Search SharePoint content across all sites using KQL.
        Args:
            query: Search keywords or KQL query
            limit: Max results (default 20)
        """
        return asyncio.run(sp.search(query, limit))

    @tool
    def sp_files(operation: str = "list", library: str = "Documents", folder: str = "",
                 personal: bool = True, site_url: str = "") -> str:
        """Browse files and libraries on SharePoint/OneDrive.
        Args:
            operation: list (files), libraries (list libraries), sites (list sites)
            library: Document library name (default: Documents)
            folder: Subfolder path within library
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        if operation == "sites":
            return asyncio.run(sp.list_sites())
        if operation == "libraries":
            return asyncio.run(sp.list_libraries(personal, site_url))
        return asyncio.run(sp.list_files(library, folder, personal, site_url))

    @tool
    def sp_read(file_path: str, personal: bool = True, site_url: str = "") -> str:
        """Read a file from SharePoint/OneDrive. Handles .docx, .pptx, and text files.
        Binary files are downloaded and text-extracted automatically.
        Args:
            file_path: Server-relative URL of the file
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        return asyncio.run(sp.read_file(file_path, personal=personal, site_url=site_url))

    @tool
    def sp_write(library: str, file_name: str, content: str = "", source_path: str = "",
                 folder: str = "", personal: bool = True, site_url: str = "") -> str:
        """Write or upload a file to SharePoint/OneDrive.
        For text content, provide content. For binary files (docx, pptx, etc.), provide source_path.
        Args:
            library: Document library name
            file_name: File name to create
            content: Text content to upload
            source_path: Local file path to upload (for binary files)
            folder: Subfolder path (created automatically)
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        if source_path:
            return asyncio.run(sp.upload_file(library, file_name, source_path, folder, personal, site_url))
        return asyncio.run(sp.write_file(library, file_name, content, folder, personal, site_url))

    @tool
    def sp_manage(operation: str, path: str = "", library: str = "Documents",
                  folder_path: str = "", list_title: str = "", description: str = "",
                  item_id: int = 0, personal: bool = True, site_url: str = "") -> str:
        """File and list management — delete files, create folders, create/delete lists, delete list items.
        Args:
            operation: delete_file, create_folder, create_list, delete_list, delete_item
            path: Server-relative URL (for delete_file)
            library: Library name (for create_folder)
            folder_path: Folder path to create
            list_title: List name (for create_list, delete_list, delete_item)
            description: Description (for create_list)
            item_id: Item ID (for delete_item)
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        ops = {
            "delete_file": lambda: asyncio.run(sp.delete_file(path, personal, site_url)),
            "create_folder": lambda: asyncio.run(sp.create_folder(library, folder_path, personal, site_url)),
            "create_list": lambda: asyncio.run(sp.create_list(list_title, description, personal, site_url)),
            "delete_list": lambda: asyncio.run(sp.delete_list(list_title, personal, site_url)),
            "delete_item": lambda: asyncio.run(sp.delete_item(list_title, item_id, personal, site_url)),
        }
        fn = ops.get(operation)
        return fn() if fn else f"Unknown operation: {operation}. Available: {list(ops.keys())}"

    @tool
    def sp_lists(operation: str = "browse", list_title: str = "", fields: str = "",
                 item_id: int = 0, filter_expr: str = "",
                 personal: bool = True, site_url: str = "") -> str:
        """Manage SharePoint lists — browse, read items, create/update items.
        Args:
            operation: browse (list all lists), items (get items), create (add item), update (update item)
            list_title: List name (required for items/create/update)
            fields: JSON string of field key-value pairs (for create/update)
            item_id: Item ID (for update)
            filter_expr: OData filter (for items, e.g. "Status eq 'Active'")
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        if operation == "browse":
            return asyncio.run(sp.list_lists(personal, site_url))
        if operation == "items":
            return asyncio.run(sp.list_items(list_title, personal, site_url, filter_expr))
        if operation == "create":
            return asyncio.run(sp.create_item(list_title, json.loads(fields), personal, site_url))
        if operation == "update":
            return asyncio.run(sp.update_item(list_title, item_id, json.loads(fields), personal, site_url))
        return f"Unknown operation: {operation}"

    @tool
    def sp_analyze(file_path: str, instruction: str = "Summarize this document",
                   personal: bool = True, site_url: str = "") -> str:
        """Read a document from SharePoint/OneDrive and analyze it with a thinking model.
        Use this for summarization, extraction, or any deep analysis of document content.
        Handles .docx, .pptx, and text files. Uses a heavy-tier AI model.
        Args:
            file_path: Server-relative URL of the file
            instruction: What to do with the document (e.g. "Summarize", "Extract action items")
            personal: True for OneDrive, False for team sites
            site_url: SharePoint site URL (for team sites)
        """
        from agents.base import invoke_ai
        text = asyncio.run(sp.read_file(file_path, personal=personal, site_url=site_url))
        if text.startswith("Error") or text.startswith("Could not") or text.startswith("Binary file"):
            return text
        prompt = f"""{instruction}

Document content:
{text}"""
        return invoke_ai(prompt, max_tokens=8000, tier="heavy")

    return Agent(
            model=_model("medium"),
            system_prompt="You are a SharePoint/OneDrive specialist. You search content, browse and read files, upload documents, and manage SharePoint lists. When site_url is provided, target that team site; otherwise default to the user's personal OneDrive. For document summarization or analysis, ALWAYS use sp_analyze instead of sp_read.",
            tools=[sp_search, sp_files, sp_read, sp_write, sp_lists, sp_manage, sp_analyze],
            callback_handler=None,
        )


# ============================================================
# Factory — lazy creation, cached instances
# ============================================================

_workers = {}

def get_worker(name: str) -> Agent:
    """Get or create a worker agent by name."""
    if name not in _workers:
        factories = {
            "email": _create_email_worker,
            "comms": _create_comms_worker,
            "calendar": _create_calendar_worker,
            "productivity": _create_productivity_worker,
            "research": _create_research_worker,
            "sharepoint": _create_sharepoint_worker,
        }
        factory = factories.get(name)
        if not factory:
            raise ValueError(f"Unknown worker: {name}. Available: {list(factories.keys())}")
        _workers[name] = factory()
    return _workers[name]


WORKER_NAMES = ["email", "comms", "calendar", "productivity", "research", "sharepoint"]
