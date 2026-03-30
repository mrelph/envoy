"""Slack agent — scan, search, DM, mark read."""

import json
from datetime import datetime, timedelta
from typing import List

from agents.base import (
    slack, MCPConnectionError, invoke_ai, make_tag, log_sent, load_sent,
)


async def scan_raw(channels: List[str] = None, days: int = 7) -> str:
    """Fetch raw Slack messages — DMs first (priority), then channels."""
    from datetime import timezone
    oldest = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        async with slack() as session:
            if channels:
                channel_ids = [(c, c, "channel") for c in channels]
            else:
                channel_ids = []
                for ch_type in ["dm", "group_dm"]:
                    try:
                        result = await session.call_tool(
                            "list_channels",
                            arguments={"channelTypes": [ch_type], "unreadOnly": True, "limit": 20}
                        )
                        ch_data = json.loads(result.content[0].text) if result.content else {}
                        for c in ch_data.get('channels', []):
                            channel_ids.append((c['id'], c.get('name', c['id']), ch_type))
                    except Exception:
                        pass
                try:
                    result = await session.call_tool(
                        "list_channels",
                        arguments={"channelTypes": ["public_and_private"], "unreadOnly": True, "limit": 20}
                    )
                    ch_data = json.loads(result.content[0].text) if result.content else {}
                    for c in ch_data.get('channels', []):
                        channel_ids.append((c['id'], c.get('name', c['id']), "channel"))
                except Exception:
                    pass

            if not channel_ids:
                return "No Slack channels or DMs found to scan."

            ch_only = [cid for cid, _, kind in channel_ids if kind == "channel"]
            name_map = {}
            if ch_only:
                info_result = await session.call_tool("batch_get_channel_info", arguments={"channelIds": ch_only})
                for item in (json.loads(info_result.content[0].text) if info_result.content else []):
                    if 'result' in item:
                        name_map[item['channelId']] = item['result'].get('name', item['channelId'])

            batch = [{"channelId": cid, "oldest": oldest, "limit": 30} for cid, _, _ in channel_ids]
            result = await session.call_tool("batch_get_conversation_history", arguments={"channels": batch})
            raw = json.loads(result.content[0].text) if result.content else []

        lookup = {}
        for cid, name, kind in channel_ids:
            lookup[cid] = (name_map.get(cid, name), kind)

        lines = []
        for item in raw:
            ch_id = item.get('channelId', '')
            display, kind = lookup.get(ch_id, (ch_id, "channel"))
            prefix = "🔴 DM" if kind == "dm" else ("🟡 GroupDM" if kind == "group_dm" else f"#{display}")
            for msg in item.get('result', {}).get('messages', []):
                text = msg.get('text', '')[:500]
                if text:
                    lines.append(f"[{prefix}] {msg.get('user', '?')}: {text}")

        return "\n".join(lines[:200]) if lines else "No Slack messages found in the specified period."
    except MCPConnectionError:
        raise
    except Exception as e:
        return f"Error scanning Slack: {e}"


async def scan(channels: List[str] = None, days: int = 7) -> str:
    """Fetch + AI-analyze Slack messages."""
    raw = await scan_raw(channels, days)
    if raw.startswith("No ") or raw.startswith("Error"):
        return raw

    prompt = f"""Analyze these Slack messages (pre-sorted by priority: 🔴 DM > 🟡 GroupDM > #channel).

# Slack Scan Report

## 🔴 Direct Messages (Action Required)
- **DM from @user** — [what they need]

## ⚠️ Important Updates
- **#channel** or **GroupDM** — [summary]

## 🔑 Key Discussions
- **#channel** — [topic and status]

## 📋 FYI
- **#channel** — [brief note]

## Summary
[2-3 sentences]

Skip empty sections. DMs always outrank channel noise. Only last {days} days.

Messages:
{raw[:8000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="medium")
    except Exception as e:
        return f"# Slack Scan Report\n\n**Error:** {e}\n"


async def send_dm(recipient: str, message: str) -> str:
    track_tag = make_tag()
    tagged_msg = f"{message}\n\n`{track_tag}`"
    try:
        async with slack() as session:
            dm_result = await session.call_tool("open_conversation", arguments={"users": [recipient]})
            dm_data = json.loads(dm_result.content[0].text) if dm_result.content else {}
            channel_id = dm_data.get("channelId") or dm_data.get("channel", {}).get("id")
            if not channel_id:
                raise Exception("Could not open DM channel")
            await session.call_tool("post_message", arguments={"channelId": channel_id, "text": tagged_msg})
            log_sent(track_tag, channel_id, recipient, "slack", message)
            return f"✅ Sent DM to {recipient} ({track_tag}):\n\n> {message}"
    except Exception as e:
        return f"❌ Failed to DM {recipient}: {e}"


async def mark_read(channel_ids: List[str] = None) -> str:
    from datetime import timezone
    try:
        async with slack() as session:
            if not channel_ids:
                result = await session.call_tool("list_channels", arguments={
                    "channelTypes": ["public_and_private"], "unreadOnly": True, "limit": 50
                })
                data = json.loads(result.content[0].text) if result.content else {}
                channel_ids = [c['id'] for c in data.get('channels', [])]
            if not channel_ids:
                return "No unread channels to mark."
            now_iso = datetime.now(timezone.utc).isoformat()
            channels = [{"channelId": cid, "tsIso": now_iso} for cid in channel_ids]
            await session.call_tool("batch_set_last_read", arguments={"channels": channels})
            return f"✅ Marked {len(channel_ids)} channels as read."
    except Exception as e:
        return f"Error marking channels read: {e}"


async def search_slack(query: str) -> str:
    try:
        async with slack() as session:
            result = await session.call_tool("search", arguments={"query": query})
            return str(result.content[0].text) if result.content else "No results found."
    except Exception as e:
        return f"Error searching Slack: {e}"


async def check_slack_replies() -> str:
    entries = load_sent()
    slack_entries = [e for e in entries if e["medium"] == "slack" and e.get("channel")]
    if not slack_entries:
        return ""
    results = []
    try:
        async with slack() as session:
            for entry in slack_entries[-20:]:
                try:
                    search_result = await session.call_tool("search", arguments={"query": entry["tag"]})
                    search_text = str(search_result.content[0].text) if search_result.content else ""
                    if "thread_ts" in search_text or "reply" in search_text.lower():
                        results.append(f"💬 **Reply found** to message for {entry['recipient']} ({entry['tag']}): {entry['summary'][:80]}")
                    elif entry["tag"] in search_text:
                        results.append(f"⏳ **No reply yet** from {entry['recipient']} — sent {entry['sent_at'][:10]}: {entry['summary'][:80]}")
                except Exception:
                    pass
    except Exception:
        pass
    return "\n".join(results)
