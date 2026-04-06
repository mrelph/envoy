"""Comms worker — Slack + EA delegation."""

from strands import Agent, tool
from agents.base import run
from agents.workers import _model


def create():
    from agents import slack_agent as slack_mod
    from agents import workflows as wf

    from agents.workers import _USER

    @tool
    def scan_channels(channels: str = "", days: int = 7) -> str:
        """Scan Slack channels for activity and action items. Resolves user names and includes thread replies.
        Args:
            channels: Comma-separated channel IDs (empty = auto-detect)
            days: Days to look back
        """
        ch_list = [c.strip() for c in channels.split(",") if c.strip()] or None
        return run(slack_mod.scan(ch_list, days, alias=_USER))

    @tool
    def send_message(recipient: str, message: str, thread_ts: str = "") -> str:
        """Send a Slack message to a person, group, or channel. Supports threaded replies.
        Args:
            recipient: Single alias, comma-separated aliases for group DM, or channel ID (C/G/D prefix)
            message: Message text
            thread_ts: Parent message timestamp for threaded reply (optional)
        """
        return run(slack_mod.send_dm(recipient, message, thread_ts))

    @tool
    def mark_read(channel_ids: str = "") -> str:
        """Mark Slack channels as read.
        Args:
            channel_ids: Comma-separated channel IDs (empty = all unread)
        """
        ids = [c.strip() for c in channel_ids.split(",") if c.strip()] if channel_ids else None
        return run(slack_mod.mark_read(ids))

    @tool
    def search_messages(query: str) -> str:
        """Search Slack message history.
        Args:
            query: Search query (supports in:#channel, from:@user)
        """
        return run(slack_mod.search_slack(query))

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
            "react": lambda: run(slack_mod.add_reaction(channel_id, timestamp, emoji, slack_url)),
            "draft": lambda: run(slack_mod.create_slack_draft(channel_id, text, thread_ts)),
            "list_drafts": lambda: run(slack_mod.list_slack_drafts()),
            "download_file": lambda: run(slack_mod.download_file(file_id)),
            "sections": lambda: run(slack_mod.get_sections()),
            "list_items": lambda: run(slack_mod.get_slack_list_items(list_id, limit)),
            "list_item_detail": lambda: run(slack_mod.get_slack_list_item(list_id, item_id)),
        }
        fn = ops.get(operation)
        return fn() if fn else f"Unknown operation: {operation}"

    return Agent(
        model=_model("medium"),
        system_prompt="You are a Slack and communications specialist. You scan channels (with user name resolution and thread context), send messages (DMs, channels, threaded replies), search, add reactions, manage drafts, download files, and delegate to EAs. Be concise.",
        tools=[scan_channels, send_message, mark_read, search_messages, send_to_ea, slack_extras],
        callback_handler=None,
    )
