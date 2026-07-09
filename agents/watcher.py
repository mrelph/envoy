"""Watcher — long-running background agent that reacts to events in near-real-time.

Polls Slack (via MCP) and runs routines on a short interval. When new DMs/mentions
arrive, sends a Slack DM summary. Designed to run as a daemon (systemd/launchd/tmux).

Usage:
    envoy watch                # default 60s interval
    envoy watch --interval 30  # poll every 30s
    envoy watch --once         # one pass then exit (for testing)
"""

import asyncio
import hashlib
import json
import os
import signal
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from agents.base import run, slack
from agents import slack_agent
from agents.heartbeat import _run_heartbeat_async

from agents.base import current_user as _USER  # call-time alias resolution
from agents.paths import CONFIG_DIR as _ENVOY_DIR
_STATE_FILE = _ENVOY_DIR / "watcher_state.json"
_stop = False


def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict):
    _ENVOY_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def _slack_channel_lines(raw_text: str, seen_channels: dict, digest_key: str, state: dict) -> list:
    """Return lines for channels whose unread state actually changed.

    Dedups per-channel, keyed on the Slack channel id (a stable identifier)
    rather than hashing the whole unread payload — hashing the whole blob
    means a single new message in one channel causes every other still-
    unread-but-already-reported channel to be re-announced too. This is the
    same class of bug as heartbeat's model-text dedup (see heartbeat.py's
    module comment): comparing a blob instead of stable IDs.

    Falls back to the old whole-payload content-hash behavior if the tool
    response isn't the expected {"channels": [...]} shape.
    """
    try:
        channels = json.loads(raw_text).get("channels") if raw_text else []
    except Exception:
        channels = None

    if channels is None:
        digest = hashlib.md5(raw_text.encode()).hexdigest() if raw_text else ""
        if not digest or digest == state.get(digest_key):
            state[digest_key] = digest
            return []
        state[digest_key] = digest
        return [raw_text.strip()] if raw_text.strip() else []

    lines = []
    for c in channels:
        cid = c.get("id")
        if not cid:
            continue
        fingerprint = f"{c.get('last_read', '')}|{c.get('unread_count', c.get('unread', ''))}"
        if seen_channels.get(cid) == fingerprint:
            continue
        seen_channels[cid] = fingerprint
        lines.append(f"- {c.get('name', cid)}: {json.dumps(c, default=str)[:300]}")
    return lines


async def _check_slack(state: dict) -> str:
    """Return summary of new unread DMs/mentions since last tick, or ''.

    See _slack_channel_lines() for the per-channel dedup this delegates to.
    """
    try:
        async with slack() as s:
            dm_result = await s.call_tool(
                "list_channels",
                arguments={"channelTypes": ["dm", "group_dm"], "unreadOnly": True, "limit": 20},
            )
            dm_text = dm_result.content[0].text if dm_result.content else ""
            mention_result = await s.call_tool(
                "list_channels",
                arguments={"channelTypes": ["public_and_private"], "unreadOnly": True, "limit": 20},
            )
            mention_text = mention_result.content[0].text if mention_result.content else ""
    except Exception as e:
        return f"⚠️ Slack check failed: {e}"

    seen_channels = state.setdefault("seen_channels", {})
    new_dm_lines = _slack_channel_lines(dm_text, seen_channels, "last_dm_digest", state)
    new_mention_lines = _slack_channel_lines(mention_text, seen_channels, "last_mention_digest", state)

    # Bound the per-channel state so it doesn't grow forever (dict preserves
    # insertion order — drop the oldest-inserted entries first).
    if len(seen_channels) > 500:
        for k in list(seen_channels.keys())[: len(seen_channels) - 500]:
            del seen_channels[k]
    state["seen_channels"] = seen_channels

    parts = []
    if new_dm_lines:
        parts.append("**DMs/group DMs with unread:**\n" + "\n".join(new_dm_lines)[:1500])
    if new_mention_lines:
        parts.append("**Channels with unread:**\n" + "\n".join(new_mention_lines)[:1500])
    return "\n\n".join(parts)


async def _tick(force_heartbeat: bool):
    state = _load_state()
    alerts = []

    slack_summary = await _check_slack(state)
    if slack_summary:
        alerts.append(f"💬 New Slack activity\n{slack_summary}")

    # Heartbeat on slower cadence (15 min) to avoid AI spam
    now = datetime.now(timezone.utc)
    last = state.get("last_heartbeat")
    should_hb = force_heartbeat or not last or \
        (now - datetime.fromisoformat(last)).total_seconds() > 900
    if should_hb:
        try:
            hb = await _run_heartbeat_async(quiet=True, notify="none")
            if hb and "ALL_CLEAR" not in hb.upper() and hb.lower() != "all clear.":
                alerts.append(f"🔔 Heartbeat\n{hb}")
            state["last_heartbeat"] = now.isoformat()
        except Exception as e:
            alerts.append(f"⚠️ Heartbeat failed: {e}")

    if alerts:
        msg = f"👁 Envoy Watcher — {now.astimezone().strftime('%a %I:%M%p')}\n\n" + "\n\n".join(alerts)
        try:
            await slack_agent.send_dm(_USER(), msg)
        except Exception:
            print(msg)

    _save_state(state)
    return len(alerts)


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    print("\n👁 Watcher shutting down…")


def run_watcher(interval: int = 60, once: bool = False) -> str:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if once:
        n = run(_tick(force_heartbeat=True))
        return f"Watcher pass complete — {n} alert group(s)."

    print(f"👁 Envoy Watcher started — polling every {interval}s. Ctrl+C to stop.")
    consecutive_failures = 0
    while not _stop:
        try:
            run(_tick(force_heartbeat=False))
            consecutive_failures = 0
        except Exception as e:
            consecutive_failures += 1
            backoff = min(interval * (2 ** consecutive_failures), 900)  # cap at 15 min
            print(f"⚠️ Watcher tick failed ({consecutive_failures}x): {e} — backing off {backoff}s")
            for _ in range(backoff):
                if _stop:
                    break
                _time.sleep(1)
            continue
        for _ in range(interval):
            if _stop:
                break
            _time.sleep(1)
    return "Watcher stopped."
