"""Slack agent — scan, search, DM, channel post, threads, mark read, reactions, drafts, files."""

import json
import re
from datetime import datetime, timedelta
from typing import List, Dict

from agents.base import (
    slack, MCPConnectionError, invoke_ai, make_tag, log_sent, load_sent,
)


async def resolve_user_ids(user_ids: List[str], session=None) -> Dict[str, str]:
    """Resolve Slack user IDs to display names. Returns {id: name} map."""
    if not user_ids:
        return {}
    unique = list(set(user_ids))[:50]
    try:
        async def _resolve(s):
            result = await s.call_tool("batch_get_user_info", arguments={"users": unique})
            raw = result.content[0].text if result.content else "[]"
            data = json.loads(raw) if isinstance(raw, str) else raw
            mapping = {}
            # Handle both list and dict response shapes
            items = data if isinstance(data, list) else data.get('users', data.get('results', []))
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Try multiple key patterns for user ID
                uid = item.get('userId') or item.get('user_id') or item.get('id') or ''
                # Try nested result, or flat structure
                info = item.get('result') or item.get('profile') or item
                if isinstance(info, dict):
                    name = (info.get('real_name') or info.get('realName')
                            or info.get('display_name') or info.get('displayName')
                            or info.get('name') or '')
                else:
                    name = ''
                if uid and name:
                    mapping[uid] = name
            # Fill in any unresolved IDs
            for uid in unique:
                if uid not in mapping:
                    mapping[uid] = uid
            return mapping
        if session:
            return await _resolve(session)
        async with slack() as s:
            return await _resolve(s)
    except Exception:
        return {uid: uid for uid in unique}


async def get_thread_replies(channel_id: str, thread_ts: str, session=None) -> List[Dict]:
    """Fetch replies in a thread."""
    try:
        async def _fetch(s):
            result = await s.call_tool("batch_get_thread_replies", arguments={
                "threads": [{"channelId": channel_id, "threadTs": thread_ts}]
            })
            data = json.loads(result.content[0].text) if result.content else []
            if data and 'result' in data[0]:
                return data[0]['result'].get('messages', [])
            return []
        if session:
            return await _fetch(session)
        async with slack() as s:
            return await _fetch(s)
    except Exception:
        return []


async def download_file(file_id: str) -> str:
    """Download a Slack file/canvas and return its content."""
    try:
        async with slack() as session:
            result = await session.call_tool("download_file_content", arguments={"file": file_id})
            return str(result.content[0].text) if result.content else "No content."
    except Exception as e:
        return f"Error downloading file: {e}"


async def get_sections() -> str:
    """Get channel sidebar sections for prioritization."""
    try:
        async with slack() as session:
            result = await session.call_tool("get_channel_sections", arguments={})
            return str(result.content[0].text) if result.content else "No sections."
    except Exception as e:
        return f"Error fetching sections: {e}"


async def add_reaction(channel_id: str = "", timestamp: str = "",
                       emoji: str = "eyes", slack_url: str = "") -> str:
    """Add an emoji reaction to a message."""
    try:
        async with slack() as session:
            args = {"operation": "add", "emoji": emoji}
            if slack_url:
                args["slackUrl"] = slack_url
            else:
                args["channelId"] = channel_id
                args["timestamp"] = timestamp
            result = await session.call_tool("reaction_tool", arguments=args)
            return str(result.content[0].text) if result.content else f"✅ Reacted with :{emoji}:"
    except Exception as e:
        return f"Error adding reaction: {e}"


async def create_slack_draft(channel_id: str, text: str, thread_ts: str = "") -> str:
    """Create a draft message in a channel."""
    try:
        async with slack() as session:
            args = {"channelId": channel_id, "text": text}
            if thread_ts:
                args["threadTs"] = thread_ts
            result = await session.call_tool("create_draft", arguments=args)
            return str(result.content[0].text) if result.content else "✅ Draft created."
    except Exception as e:
        return f"Error creating draft: {e}"


async def list_slack_drafts() -> str:
    """List all active draft messages."""
    try:
        async with slack() as session:
            result = await session.call_tool("list_drafts", arguments={})
            return str(result.content[0].text) if result.content else "No drafts."
    except Exception as e:
        return f"Error listing drafts: {e}"


async def scan_raw(channels: List[str] = None, days: int = 7, alias: str = "") -> str:
    """Fetch raw Slack messages — DMs first (priority), then channels.
    Resolves user IDs, fetches thread replies, adds timestamps, flags @mentions and own messages."""
    from datetime import timezone
    import os
    alias = alias or os.getenv("USER", "")
    oldest_fallback = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    try:
        async with slack() as session:
            if channels:
                channel_ids = [(c, c, "channel", oldest_fallback) for c in channels]
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
                            lr = c.get('last_read', '')
                            channel_ids.append((c['id'], c.get('name', c['id']), ch_type, lr or oldest_fallback))
                    except Exception:
                        pass
                try:
                    result = await session.call_tool(
                        "list_channels",
                        arguments={"channelTypes": ["public_and_private"], "unreadOnly": True, "limit": 20}
                    )
                    ch_data = json.loads(result.content[0].text) if result.content else {}
                    for c in ch_data.get('channels', []):
                        lr = c.get('last_read', '')
                        channel_ids.append((c['id'], c.get('name', c['id']), "channel", lr or oldest_fallback))
                except Exception:
                    pass

            if not channel_ids:
                return "No Slack channels or DMs found to scan."

            ch_only = [cid for cid, _, kind, _ in channel_ids if kind == "channel"]
            name_map = {}
            if ch_only:
                info_result = await session.call_tool("batch_get_channel_info", arguments={"channelIds": ch_only})
                for item in (json.loads(info_result.content[0].text) if info_result.content else []):
                    if 'result' in item:
                        name_map[item['channelId']] = item['result'].get('name', item['channelId'])

            batch = [{"channelId": cid, "oldest": lr, "limit": 30}
                     for cid, _, _, lr in channel_ids]
            result = await session.call_tool("batch_get_conversation_history", arguments={"channels": batch})
            raw = json.loads(result.content[0].text) if result.content else []

            lookup = {}
            for cid, name, kind, _ in channel_ids:
                lookup[cid] = (name_map.get(cid, name), kind)

            # Collect all user IDs for batch resolution
            all_user_ids = set()
            all_messages = []
            threaded_msgs = []
            for item in raw:
                ch_id = item.get('channelId', '')
                for msg in item.get('result', {}).get('messages', []):
                    uid = msg.get('user', '')
                    if uid:
                        all_user_ids.add(uid)
                    all_messages.append((ch_id, msg))
                    if msg.get('reply_count', 0) > 0 and msg.get('ts'):
                        threaded_msgs.append((ch_id, msg['ts']))

            # Resolve user IDs to names (same session)
            user_names = await resolve_user_ids(list(all_user_ids), session) if all_user_ids else {}

            # Identify current user's Slack ID by matching alias against resolved names
            my_uid = ""
            alias_lower = alias.lower()
            for uid, name in user_names.items():
                if alias_lower and alias_lower in name.lower():
                    my_uid = uid
                    break

            # Fetch thread replies (same session, up to 10)
            thread_lines = {}
            if threaded_msgs:
                try:
                    thread_batch = [{"channelId": cid, "threadTs": ts} for cid, ts in threaded_msgs[:10]]
                    result = await session.call_tool("batch_get_thread_replies", arguments={"threads": thread_batch})
                    thread_data = json.loads(result.content[0].text) if result.content else []
                    for i, item in enumerate(thread_data):
                        if i < len(threaded_msgs):
                            cid, ts = threaded_msgs[i]
                            replies = item.get('result', {}).get('messages', [])
                            reply_texts = []
                            for r in replies[1:5]:
                                r_uid = r.get('user', '?')
                                r_name = user_names.get(r_uid, r_uid)
                                r_text = r.get('text', '')[:300]
                                r_text = re.sub(r'<@(U[A-Z0-9]+)>', lambda m: f"@{user_names.get(m.group(1), m.group(1))}", r_text)
                                if r_text:
                                    r_tag = " [you]" if r_uid == my_uid else ""
                                    reply_texts.append(f"    ↳ {r_name}{r_tag}: {r_text}")
                            if reply_texts:
                                thread_lines[(cid, ts)] = "\n".join(reply_texts)
                except Exception as e:
                    from envoy_logger import get_logger
                    get_logger().log_warning(f"Thread fetch failed: {e}")

        lines = []
        for ch_id, msg in all_messages:
            display, kind = lookup.get(ch_id, (ch_id, "channel"))
            # For DMs, use the sender's resolved name instead of channel ID
            if kind == "dm":
                sender_uid = msg.get('user', '')
                dm_name = user_names.get(sender_uid, display)
                prefix = f"🔴 DM ({dm_name})"
            elif kind == "group_dm":
                prefix = "🟡 GroupDM"
            else:
                prefix = f"#{display}"
            text = msg.get('text', '')[:500]
            uid = msg.get('user', '?')
            name = user_names.get(uid, uid)
            ts = msg.get('ts', '')

            # Resolve <@U...> mentions in message text
            def _resolve_mention(m):
                mentioned_uid = m.group(1)
                return f"@{user_names.get(mentioned_uid, mentioned_uid)}"
            text = re.sub(r'<@(U[A-Z0-9]+)>', _resolve_mention, text)

            # Format timestamp
            ts_str = ""
            if ts:
                try:
                    dt = datetime.fromtimestamp(float(ts))
                    ts_str = dt.strftime('%b %d %I:%M%p').replace(' 0', ' ').lower()
                except Exception:
                    pass

            if text:
                # Tag own messages and @mentions
                is_me = uid == my_uid
                is_mention = alias_lower and (f"<@{my_uid}>" in text or f"@{alias_lower}" in text.lower())
                tag = ""
                if is_me:
                    tag = " [you]"
                elif is_mention:
                    tag = " ⚡@you"

                lines.append(f"[{prefix}] ({ts_str}) {name}{tag}: {text}")
                # Append thread replies if available
                thread_key = (ch_id, msg.get('ts', ''))
                if thread_key in thread_lines:
                    lines.append(thread_lines[thread_key])

        return "\n".join(lines[:300]) if lines else "No Slack messages found in the specified period."
    except MCPConnectionError:
        raise
    except Exception as e:
        return f"Error scanning Slack: {e}"


async def scan(channels: List[str] = None, days: int = 7, alias: str = "") -> str:
    """Fetch + AI-analyze Slack messages."""
    import os
    alias = alias or os.getenv("USER", "")
    raw = await scan_raw(channels, days, alias=alias)
    if raw.startswith("No ") or raw.startswith("Error"):
        return raw

    prompt = f"""Analyze these Slack messages for {alias}. Messages are pre-sorted by priority: 🔴 DM > 🟡 GroupDM > #channel.

Key markers in the data:
- "[you]" = message sent BY {alias} (already handled — no action needed unless no reply came back)
- "⚡@you" = {alias} was @mentioned (likely needs attention)
- Timestamps show when each message was sent

# Slack Scan Report

## 🔴 Needs Your Reply
DMs and @mentions where {alias} hasn't responded yet. Skip conversations where [you] already replied.

## ⚠️ Important Updates
Significant team/project updates {alias} should know about.

## 🔑 Key Discussions
Active threads worth following.

## 📋 FYI
Low-priority noise — brief notes only.

## Summary
2-3 sentences: what needs action vs what's just informational.

Skip empty sections. Prioritize: unanswered DMs > @mentions > channel activity.

Messages:
{raw[:8000]}"""
    try:
        return invoke_ai(prompt, max_tokens=8000, tier="heavy")
    except Exception as e:
        return f"# Slack Scan Report\n\n**Error:** {e}\n"


async def send_dm(recipient: str, message: str, thread_ts: str = "") -> str:
    """Send a Slack message to a person, group, or channel. Supports threaded replies."""
    track_tag = make_tag()
    tagged_msg = f"{message}\n\n`{track_tag}`"
    try:
        async with slack() as session:
            # Support channel IDs (group DM or channel) directly
            if recipient.startswith(("C", "G", "D")):
                channel_id = recipient
            else:
                users = [u.strip() for u in recipient.split(",") if u.strip()]
                dm_result = await session.call_tool("open_conversation", arguments={"users": users})
                dm_data = json.loads(dm_result.content[0].text) if dm_result.content else {}
                channel_id = dm_data.get("channelId") or dm_data.get("channel", {}).get("id")
            if not channel_id:
                raise Exception("Could not open DM channel")
            args = {"channelId": channel_id, "text": tagged_msg}
            if thread_ts:
                args["threadTs"] = thread_ts
            await session.call_tool("post_message", arguments=args)
            log_sent(track_tag, channel_id, recipient, "slack", message)
            return f"✅ Sent to {recipient} ({track_tag}):\n\n> {message}"
    except Exception as e:
        return f"❌ Failed to message {recipient}: {e}"


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


async def get_slack_list_items(list_id: str, limit: int = 50) -> str:
    """Fetch items from a Slack List."""
    try:
        async with slack() as session:
            args = {"list_id": list_id}
            if limit:
                args["limit"] = limit
            result = await session.call_tool("lists_items_list", arguments=args)
            return str(result.content[0].text) if result.content else "No items found."
    except Exception as e:
        return f"Error fetching Slack List: {e}"


async def get_slack_list_item(list_id: str, item_id: str) -> str:
    """Get details of a specific Slack List item."""
    try:
        async with slack() as session:
            result = await session.call_tool("lists_items_info", arguments={
                "list_id": list_id, "item_id": item_id
            })
            return str(result.content[0].text) if result.content else "No item found."
    except Exception as e:
        return f"Error fetching Slack List item: {e}"
