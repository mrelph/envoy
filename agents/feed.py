"""Proactive activity feed — ambient insights, alerts, and suggested actions.

Runs as a background loop in the TUI, polling lightweight data sources
and surfacing items the user should know about before they ask.
"""

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from agents.base import run, MCP_CALL_TIMEOUT


# ── Data Model ──────────────────────────────────────────────────────

@dataclass
class FeedItem:
    """A single item in the activity feed."""
    icon: str           # emoji prefix
    text: str           # one-line summary
    category: str       # email, slack, calendar, commitment, pattern, suggestion
    priority: int = 1   # 0=urgent, 1=normal, 2=low
    timestamp: float = field(default_factory=time.time)
    ref: str = ""       # actionable reference (e.g., conversation_id, channel)
    action_hint: str = ""  # what the user can do (e.g., "reply", "prep")
    dedup_key: str = ""    # for deduplication — same key = same item

    def __post_init__(self):
        if not self.dedup_key:
            self.dedup_key = hashlib.md5(f"{self.category}:{self.text[:80]}".encode()).hexdigest()[:12]

    @property
    def age_str(self) -> str:
        ago = time.time() - self.timestamp
        if ago < 60:
            return "just now"
        if ago < 3600:
            return f"{int(ago/60)}m ago"
        return f"{int(ago/3600)}h ago"

    @property
    def display(self) -> str:
        ts = datetime.fromtimestamp(self.timestamp).strftime("%H:%M")
        action = f"  → {self.action_hint}" if self.action_hint else ""
        return f"{ts}  {self.icon} {self.text}{action}"


# ── Feed Manager ────────────────────────────────────────────────────

_MAX_ITEMS = 20
_SEEN_KEYS: set = set()
_items: list = []
_listeners: list = []  # callables notified on new items


def get_items() -> list:
    """Get current feed items (newest first)."""
    return list(reversed(_items))


def add_item(item: FeedItem) -> bool:
    """Add item to feed if not a duplicate. Returns True if added."""
    if item.dedup_key in _SEEN_KEYS:
        return False
    _SEEN_KEYS.add(item.dedup_key)
    _items.append(item)
    # Prune old items
    while len(_items) > _MAX_ITEMS:
        old = _items.pop(0)
        _SEEN_KEYS.discard(old.dedup_key)
    # Notify listeners
    for fn in _listeners:
        try:
            fn(item)
        except Exception:
            pass
    return True


def on_new_item(fn):
    """Register a callback for new feed items (used by TUI)."""
    _listeners.append(fn)


def clear():
    """Clear all feed items and seen keys."""
    _items.clear()
    _SEEN_KEYS.clear()


# ── Insight Generators ──────────────────────────────────────────────
# Each generator is an async function that returns a list of FeedItems.
# They run concurrently in the poll loop.

async def _check_vip_emails() -> list:
    """Check for new emails from VIPs (High Priority People)."""
    items = []
    try:
        from agents.base import outlook
        async with outlook() as session:
            result = await session.call_tool("email_inbox", {"limit": 10, "unreadOnly": True})
            if not result or not result.content:
                return items
            text = str(result.content[0].text)

            # Load VIP list
            vip_aliases = _get_vip_aliases()
            if not vip_aliases:
                return items

            for line in text.splitlines():
                lower = line.lower()
                for alias in vip_aliases:
                    if alias.lower() in lower:
                        # Extract subject if possible
                        subject = line.strip()[:80]
                        items.append(FeedItem(
                            icon="📧",
                            text=f"New from {alias}: {subject}",
                            category="email",
                            priority=0,
                            ref=alias,
                            action_hint="read & reply",
                        ))
                        break
    except Exception:
        pass
    return items


async def _check_calendar_upcoming() -> list:
    """Check for meetings in the next 2 hours that might need prep."""
    items = []
    try:
        from agents.base import outlook
        async with outlook() as session:
            result = await session.call_tool("calendar_view", {"start_date": datetime.now().strftime("%m-%d-%Y"), "view": "day"})
            if not result or not result.content:
                return items
            text = str(result.content[0].text)

            now = datetime.now()
            # Simple heuristic: look for times in the next 2 hours
            for line in text.splitlines():
                if any(kw in line.lower() for kw in ("1:1", "review", "sync", "follow-up", "customer")):
                    items.append(FeedItem(
                        icon="🧩",
                        text=f"Upcoming: {line.strip()[:60]}",
                        category="calendar",
                        priority=1,
                        action_hint="prep?",
                    ))
                    if len(items) >= 2:
                        break
    except Exception:
        pass
    return items


async def _check_slack_mentions() -> list:
    """Check for unanswered @mentions in Slack."""
    items = []
    try:
        from agents.base import _mcp_session
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _slack():
            async with _mcp_session("Slack") as s:
                yield s

        async with _slack() as session:
            result = await session.call_tool("get_unreads", {})
            if not result or not result.content:
                return items
            text = str(result.content[0].text)

            # Look for @mentions
            for line in text.splitlines():
                if "@" in line and len(line) > 10:
                    items.append(FeedItem(
                        icon="💬",
                        text=line.strip()[:70],
                        category="slack",
                        priority=1,
                        action_hint="respond",
                    ))
                    if len(items) >= 3:
                        break
    except Exception:
        pass
    return items


async def _check_stale_commitments() -> list:
    """Surface commitments approaching their deadline."""
    items = []
    try:
        from agents.memory2 import recall
        mem = recall("commitment")
        if not mem:
            return items
        # Look for items with "overdue" or "due" keywords
        for line in mem.splitlines():
            if any(kw in line.lower() for kw in ("overdue", "due today", "due tomorrow", "promised")):
                items.append(FeedItem(
                    icon="⏰",
                    text=line.strip()[:70],
                    category="commitment",
                    priority=0,
                    action_hint="follow up",
                ))
                if len(items) >= 2:
                    break
    except Exception:
        pass
    return items


# ── Poll Loop ───────────────────────────────────────────────────────

_POLL_INTERVAL = 90  # seconds between polls
_running = False
_poll_task: Optional[asyncio.Task] = None

# Generators run in sequence to be gentle on MCP connections.
# Each has its own error isolation.
_GENERATORS = [
    _check_vip_emails,
    _check_calendar_upcoming,
    _check_slack_mentions,
    _check_stale_commitments,
]


async def _poll_once():
    """Run all generators once and add new items to feed."""
    for gen in _GENERATORS:
        try:
            new_items = await asyncio.wait_for(gen(), timeout=15)
            for item in (new_items or []):
                add_item(item)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass
        # Small delay between generators to avoid hammering MCP
        await asyncio.sleep(2)


async def _poll_loop():
    """Background loop that runs generators periodically."""
    global _running
    _running = True
    # Initial delay — let the TUI settle and agent initialize
    await asyncio.sleep(10)
    while _running:
        try:
            await _poll_once()
        except Exception:
            pass
        await asyncio.sleep(_POLL_INTERVAL)


def start():
    """Start the background poll loop (call from TUI on_mount)."""
    global _poll_task, _running
    if _poll_task and not _poll_task.done():
        return  # already running
    _running = True
    try:
        loop = asyncio.get_event_loop()
        _poll_task = loop.create_task(_poll_loop())
    except RuntimeError:
        # No running loop — will be started when TUI event loop is ready
        pass


def stop():
    """Stop the background poll loop."""
    global _running, _poll_task
    _running = False
    if _poll_task:
        _poll_task.cancel()
        _poll_task = None


# ── Helpers ─────────────────────────────────────────────────────────

def _get_vip_aliases() -> list:
    """Load VIP aliases from envoy.md High Priority People section."""
    try:
        from pathlib import Path
        envoy_file = Path.home() / ".envoy" / "envoy.md"
        if not envoy_file.exists():
            return []
        text = envoy_file.read_text()
        if "High Priority People" not in text:
            return []
        # Extract aliases from the section
        in_section = False
        aliases = []
        for line in text.splitlines():
            if "High Priority People" in line:
                in_section = True
                continue
            if in_section:
                if line.startswith("#") or line.startswith("---"):
                    break
                # Lines like "- alias: jsmith | name: John Smith | ..."
                if "alias:" in line.lower():
                    parts = line.split("|")
                    for part in parts:
                        if "alias:" in part.lower():
                            alias = part.split(":", 1)[1].strip()
                            if alias:
                                aliases.append(alias)
                elif line.strip().startswith("- ") and "@" not in line:
                    # Simple list format
                    name = line.strip().lstrip("- ").split()[0]
                    if name:
                        aliases.append(name)
        return aliases[:20]  # cap
    except Exception:
        return []
