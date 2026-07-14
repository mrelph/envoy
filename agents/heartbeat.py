"""Heartbeat agent — autonomous chief of staff that wakes on cron.

Reads routines (user-requested + learned), checks each using
existing tools, deduplicates against recent alerts, and notifies via Slack DM.
"""

import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from agents.base import invoke_ai, outlook, MCPConnectionError, run, agent_name
from agents import email, slack_agent, calendar, todo, tickets, people, memory2 as memory

from agents.base import current_user as _USER  # call-time alias resolution
from agents.paths import config_dir
_ENVOY_DIR = config_dir()
_ROUTINES_FILE = _ENVOY_DIR / "routines.md"
_STATE_FILE = _ENVOY_DIR / "heartbeat_state.json"
_MAX_ALERTS_PER_RUN = 10

# --- Dedup tuning ---
# Stable-ID/fingerprint dedup window (separate from the 24h "recent_alerts"
# prompt hint below, which is a much shorter-lived secondary layer).
_DEDUP_WINDOW_ENTRIES = 200
_DEDUP_WINDOW_DAYS = 7
_ITEM_TRUNCATE_BUDGET = 2000

# Severity → rank, used to keep the most severe alerts when truncating to
# _MAX_ALERTS_PER_RUN. Higher rank == more severe == kept first.
_SEVERITY_RANK = {"🔴": 3, "🟡": 2, "🔵": 1}

# Migrate old filenames silently
_OLD_ORDERS = _ENVOY_DIR / "standing_orders.md"
_OLD_STATE = _ENVOY_DIR / "patrol_state.json"
if _OLD_ORDERS.exists() and not _ROUTINES_FILE.exists():
    _OLD_ORDERS.rename(_ROUTINES_FILE)
if _OLD_STATE.exists() and not _STATE_FILE.exists():
    _OLD_STATE.rename(_STATE_FILE)


# --- Routines ---

def _ensure_files():
    _ENVOY_DIR.mkdir(parents=True, exist_ok=True)
    if not _ROUTINES_FILE.exists():
        _ROUTINES_FILE.write_text("# Routines\n\n## User-requested\n\n## Learned\n")


def get_routines() -> str:
    _ensure_files()
    return _ROUTINES_FILE.read_text()


def add_routine(instruction: str, learned: bool = False) -> str:
    _ensure_files()
    content = _ROUTINES_FILE.read_text()
    section = "## Learned" if learned else "## User-requested"
    entry = f"- {instruction}"
    if section in content:
        content = content.replace(section, f"{section}\n{entry}", 1)
    else:
        content = content.rstrip() + f"\n\n{section}\n{entry}\n"
    _ROUTINES_FILE.write_text(content)
    return f"Added routine: {instruction}"


def remove_routine(instruction_fragment: str) -> str:
    _ensure_files()
    lines = _ROUTINES_FILE.read_text().splitlines()
    new_lines = [l for l in lines if instruction_fragment.lower() not in l.lower()]
    if len(new_lines) == len(lines):
        return f"No matching routine found for: {instruction_fragment}"
    _ROUTINES_FILE.write_text("\n".join(new_lines) + "\n")
    return f"Removed routine matching: {instruction_fragment}"


# --- Heartbeat state (dedup) ---

def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_run": None, "recent_alerts": []}


def _save_state(state: dict):
    _ENVOY_DIR.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def _prune_old_alerts(state: dict, hours: int = 24) -> dict:
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    state["recent_alerts"] = [a for a in state.get("recent_alerts", []) if a.get("ts", "") > cutoff]
    return state


# --- Stable-ID / fingerprint dedup ---
#
# The "Already Reported" prompt hint (below) asks the model to skip items it
# already reported, but the model regenerates that text from scratch every
# run — timestamps shift, wording changes, ordering changes — so a purely
# text-comparison-in-the-prompt approach re-pings Slack for the same
# underlying item on every cron tick. These helpers add a code-level layer
# on top: dedup on a stable identifier when one is recoverable (e.g. an email
# conversationId embedded by _gather_context as "[id:...]"), falling back to
# a normalized-text fingerprint (hash of the alert with digits/timestamps/
# punctuation stripped) when no such identifier is available. The prompt
# hint remains a secondary layer — it still helps the model avoid restating
# an item within a single response.

_ID_TAG_RE = re.compile(r"\[id:([^\]]+)\]")
_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)


def _extract_stable_id(line: str) -> str | None:
    """Pull a stable identifier out of an alert line, if one is present.

    The prompt instructs the model to copy any "[id:...]" tag from the
    source data verbatim into its alert line (see the instructions block in
    _run_heartbeat_async). That tag currently carries an email conversationId;
    it's a code-supplied value the model can copy but not paraphrase, so it's
    safe to key dedup on directly.
    """
    m = _ID_TAG_RE.search(line)
    val = m.group(1).strip() if m else ""
    return val or None


def _fingerprint(line: str) -> str:
    """Normalized-text fingerprint fallback for alerts with no stable ID.

    Strips the id tag, emoji, digits (timestamps/dates/counts), and
    punctuation, then lowercases and collapses whitespace — so the same
    underlying alert re-worded with a different time or ordering on the next
    run still hashes identically.
    """
    text = _ID_TAG_RE.sub("", line)
    text = _EMOJI_RE.sub("", text)
    text = text.lower()
    text = re.sub(r"\d+", "", text)
    text = re.sub(r"[^a-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _alert_key(line: str) -> tuple:
    """Return (kind, key) for an alert line — a stable ID beats a fingerprint."""
    stable = _extract_stable_id(line)
    if stable:
        return ("id", stable)
    return ("fingerprint", _fingerprint(line))


def _severity_rank(line: str) -> int:
    for emoji, rank in _SEVERITY_RANK.items():
        if emoji in line:
            return rank
    return 0


def _dedup_and_cap(lines: list, state: dict) -> tuple:
    """Filter out already-seen alerts and enforce _MAX_ALERTS_PER_RUN.

    Dedup is keyed on stable ID first, normalized-text fingerprint second
    (see module docstring above). Seen keys are persisted in state under
    "seen_keys", bounded to _DEDUP_WINDOW_ENTRIES entries within
    _DEDUP_WINDOW_DAYS days.

    When more than _MAX_ALERTS_PER_RUN fresh alerts remain, the most severe
    are kept (🔴 > 🟡 > 🔵 > unranked); ties keep original order.

    Returns (kept_lines, num_deduped, num_truncated).
    """
    seen = state.setdefault("seen_keys", [])
    seen_set = {(e.get("kind"), e.get("key")) for e in seen}

    fresh = []
    for line in lines:
        kind, key = _alert_key(line)
        if (kind, key) in seen_set:
            continue
        fresh.append((line, kind, key))

    num_deduped = len(lines) - len(fresh)

    num_truncated = 0
    if len(fresh) > _MAX_ALERTS_PER_RUN:
        ranked = sorted(
            range(len(fresh)),
            key=lambda i: (-_severity_rank(fresh[i][0]), i),
        )
        keep_idx = set(ranked[:_MAX_ALERTS_PER_RUN])
        num_truncated = len(fresh) - _MAX_ALERTS_PER_RUN
        fresh = [item for i, item in enumerate(fresh) if i in keep_idx]

    now = datetime.now().isoformat()
    for line, kind, key in fresh:
        seen.append({"kind": kind, "key": key, "ts": now, "summary": line[:200]})

    cutoff = (datetime.now() - timedelta(days=_DEDUP_WINDOW_DAYS)).isoformat()
    seen = [e for e in seen if e.get("ts", "") > cutoff]
    if len(seen) > _DEDUP_WINDOW_ENTRIES:
        seen = seen[-_DEDUP_WINDOW_ENTRIES:]
    state["seen_keys"] = seen

    return [line for line, _, _ in fresh], num_deduped, num_truncated


def _truncate_by_item(text: str, budget: int = _ITEM_TRUNCATE_BUDGET) -> str:
    """Truncate text to a character budget without slicing an item in half.

    Mirrors the per-item truncation pattern in supervisor._gather_async:
    keep whole lines up to the budget rather than a flat character slice,
    which can cut the last included item off mid-sentence. If a single line
    alone exceeds the budget, hard-cut just that line as a last resort.
    """
    if len(text) <= budget:
        return text
    kept = []
    total = 0
    for line in text.splitlines():
        add = len(line) + 1  # +1 for the joining newline
        if total + add > budget:
            break
        kept.append(line)
        total += add
    if not kept:
        return text[:budget]
    return "\n".join(kept)


# --- Data gathering ---

async def _gather_context(days: int = 1) -> str:
    """Lightweight parallel data fetch for heartbeat checks."""
    sections = []

    async def _safe(name, coro):
        try:
            result = await coro
            return (name, result)
        except Exception as e:
            return (name, f"Error: {e}")

    tasks = [
        _safe("inbox", email.fetch_inbox(days=days, limit=30)),
        _safe("calendar", calendar.get_events_raw(view="day", days_ahead=1)),
        _safe("slack_dms", slack_agent.scan_raw(days=1)),
    ]

    try:
        tasks.append(_safe("tickets", tickets.scan_tickets(_USER())))
    except Exception:
        pass

    results = await asyncio.gather(*tasks, return_exceptions=True)

    failed_sources = []
    for item in results:
        if isinstance(item, Exception):
            failed_sources.append(f"unknown: {item}")
            continue
        name, data = item
        if data and str(data).startswith("Error"):
            failed_sources.append(name)
        elif data:
            if isinstance(data, list):
                if data and isinstance(data[0], dict) and "subject" in data[0]:
                    text = "\n".join(f"- {e['from']}: {e['subject']} ({e['date']}) [id:{e.get('conversationId','')}]"
                                     for e in data[:20])
                else:
                    text = _truncate_by_item(str(data))
            elif isinstance(data, tuple):
                text = _truncate_by_item(str(data[0]))
            else:
                text = _truncate_by_item(str(data))
            sections.append(f"### {name}\n{text}")

    if failed_sources:
        sections.append(f"### unavailable_sources\n{', '.join(failed_sources)} — data from these sources is MISSING, do not assume anything about them")
    return "\n\n".join(sections) if sections else "No data available."


# --- Core heartbeat ---

def run_heartbeat(quiet: bool = False, notify: str = "slack") -> str:
    """Main heartbeat entry point. Called by cron or CLI."""
    return run(_run_heartbeat_async(quiet, notify))


async def _run_heartbeat_async(quiet: bool = False, notify: str = "slack") -> str:
    """Async heartbeat — single event loop avoids MCP process cleanup races."""
    _ensure_files()
    routines = get_routines()
    state = _prune_old_alerts(_load_state())
    recent_memory = memory.recall("", limit=10)

    context = await _gather_context()

    already_reported = "\n".join(
        f"- [{a['ts'][:16]}] {a['summary']}" for a in state.get("recent_alerts", [])
    ) or "None"

    prompt = f"""You are {agent_name()} running autonomously on a schedule. No human is present.
Your job: check routines against current data and report anything that needs attention.

## Routines
{routines}

## Recent Memory
{recent_memory}

## Current Data
{context}

## Already Reported (do NOT re-alert)
{already_reported}

## Instructions
1. Check each routine against the current data.
2. Only report NEW items that haven't been reported already.
3. Be concise — one line per alert with an emoji severity indicator.
4. If nothing needs attention, respond with exactly: ALL_CLEAR
5. Format alerts as a numbered list. Include enough context to be actionable.
6. Prefix each with: 🔴 (urgent), 🟡 (important), 🔵 (informational)
7. If the data item you're alerting on carries a "[id:...]" tag (e.g. an
   email conversationId), copy that exact tag to the end of your alert
   line, unchanged. It's used for reliable duplicate detection across runs
   — do not invent one, and omit it entirely if the source item has none.

Respond with ONLY the alerts or ALL_CLEAR. No preamble."""

    # invoke_ai() is a blocking Bedrock call (10-60s). This coroutine already
    # runs on the shared MCP event loop, so calling it inline would stall all
    # other MCP traffic (watcher, gather, etc.) for the duration.
    result = await asyncio.to_thread(invoke_ai, prompt, max_tokens=800, tier="medium")

    if not result or "ALL_CLEAR" in result.upper():
        state["last_run"] = datetime.now().isoformat()
        _save_state(state)
        if not quiet:
            print("✅ Heartbeat complete — all clear.")
        return "All clear."

    alert_lines = [
        line.strip() for line in result.strip().splitlines()
        if line.strip() and (line.strip()[0].isdigit() or line.strip()[0] in "🔴🟡🔵")
    ]

    kept_lines, num_deduped, num_truncated = _dedup_and_cap(alert_lines, state)

    if num_truncated:
        print(f"⚠️ Heartbeat: dropped {num_truncated} lowest-severity alert(s) to "
              f"stay within _MAX_ALERTS_PER_RUN={_MAX_ALERTS_PER_RUN} (kept the most severe).")

    # Secondary layer: the short-lived "Already Reported" prompt hint, fed
    # from the alerts that actually got sent this run.
    now_iso = datetime.now().isoformat()
    for line in kept_lines:
        state["recent_alerts"].append({"ts": now_iso, "summary": line[:200]})

    state["last_run"] = now_iso
    _save_state(state)

    if not kept_lines:
        if not quiet:
            if num_deduped:
                print(f"✅ Heartbeat complete — all {num_deduped} alert(s) already reported, nothing new.")
            else:
                print("✅ Heartbeat complete — all clear.")
        return "All clear."

    deduped_result = "\n".join(kept_lines)

    header = f"🔔 Envoy Heartbeat — {datetime.now().strftime('%a %I:%M%p')}"
    message = f"{header}\n\n{deduped_result}"

    if notify == "slack":
        await slack_agent.send_dm(_USER(), message)
    elif notify == "email":
        await email.email_digest(message, _USER(), 0)

    if not quiet:
        print(message)

    # --- Weekly learning loop (piggybacks on heartbeat, rate-limited internally) ---
    await _run_weekly_learning(notify)

    return deduped_result


async def _run_weekly_learning(notify: str = "none"):
    """Run self-analysis + skill suggestion if due (rate-limited to weekly).

    Called from _run_heartbeat_async, which already runs on the shared MCP
    event loop. self_analyze() makes a blocking invoke_ai() call, so it's
    pushed to a thread rather than run inline (would otherwise stall MCP
    traffic for the duration of the Bedrock call). The Slack DM is a
    coroutine already, so it's awaited directly rather than passed through
    run() — calling run() from the loop thread itself would deadlock (and
    now raises immediately thanks to the guard in agents.base.run()).
    """
    try:
        from agents.learning import self_analyze, auto_apply_analysis, suggest_skill
        analysis = await asyncio.to_thread(self_analyze)
        if analysis:
            applied = auto_apply_analysis(analysis)
            suggestion = suggest_skill()
            if applied or suggestion:
                msg = "🧠 **Weekly Learning Update**\n"
                if applied:
                    msg += "\nNew process rules learned:\n" + "\n".join(f"- {r}" for r in applied)
                if suggestion:
                    msg += f"\n\n{suggestion}"
                if notify == "slack":
                    await slack_agent.send_dm(_USER(), msg)
    except Exception:
        pass  # Never break heartbeat


# --- Suggest routines from observer patterns ---

def suggest_routines() -> str:
    """Analyze observer patterns and suggest new routines."""
    from agents.learning import analyze_patterns
    patterns = analyze_patterns(days=14)
    current = get_routines()

    prompt = f"""Based on these observed user behavior patterns, suggest routines
for an autonomous heartbeat agent. Only suggest things that would be genuinely useful
as proactive alerts. Don't suggest things already covered.

## Observed Patterns
{patterns}

## Current Routines
{current}

Format each suggestion as:
- [suggestion text] — [why: brief rationale]

Only suggest 1-5 high-value items. If nothing useful, say "No suggestions."
"""
    return invoke_ai(prompt, max_tokens=400, tier="medium")


# Backward compat aliases
run_patrol = run_heartbeat
get_standing_orders = get_routines
add_order = add_routine
remove_order = remove_routine
suggest_orders = suggest_routines
