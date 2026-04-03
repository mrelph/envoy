"""Email worker — inbox, search, send, reply, cleanup."""

from strands import Agent, tool
from agents.base import run
from agents.workers import _USER, _model


def _format_html(text: str) -> str:
    """Convert plain text to simple HTML with paragraph breaks."""
    if text.strip().startswith("<"):
        return text
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{text}</p>"


def create():
    from agents import email as email_mod
    from agents import workflows as wf

    @tool
    def inbox(days: int = 1, limit: int = 30) -> str:
        """Fetch recent inbox emails. Results are numbered — use the number to reference specific emails.
        Args:
            days: Days to look back
            limit: Max emails to return
        """
        emails = run(email_mod.fetch_inbox(days, limit))
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
        return run(email_mod.reply_to_email(conversation_id, _format_html(body), reply_all))

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
        emails = run(email_mod.fetch_inbox(days, limit))
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
        result = run(email_mod.delete_emails(ids))
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
        return run(email_mod.scan_customer_emails(alias, days, team_list))

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
        run(email_mod.email_digest(body, _USER, 0))
        return f"Email sent to {_USER}@amazon.com"

    return Agent(
        model=_model("medium"),
        system_prompt="You are an email specialist. You fetch, search, classify, send, and manage emails. Be concise and action-oriented.",
        tools=[inbox, read_email, search_email, send_email, reply_email, forward_email, manage_email, cleanup, delete, customer_scan, digest, send_to_self],
        callback_handler=None,
    )
