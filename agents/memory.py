"""Memory agent — persistent memory across sessions."""

import json
import os
from datetime import datetime, timedelta

from agents.base import invoke_ai

MEMORY_DIR = os.path.expanduser("~/.envoy/memory")
MEMORY_TODAY = os.path.join(MEMORY_DIR, "today.jsonl")
MEMORY_DAYS_DIR = os.path.join(MEMORY_DIR, "days")
MEMORY_MONTHLY = os.path.join(MEMORY_DIR, "monthly.json")
MAX_ENTRY_LEN = 500
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB hard limit
DAILY_SUMMARY_MAX = 600
MONTHLY_MAX = 2500
KEEP_DAYS = 7
KEEP_WEEKS = 4


def _ensure_dirs():
    os.makedirs(MEMORY_DAYS_DIR, exist_ok=True)


def remember(text: str, entry_type: str = "action") -> str:
    _ensure_dirs()
    _compact_if_new_day()
    # Guard against unbounded growth
    if os.path.exists(MEMORY_TODAY) and os.path.getsize(MEMORY_TODAY) > MAX_FILE_SIZE:
        return "Memory file at capacity — run compress or wait for daily rotation."
    entry = json.dumps({
        "ts": datetime.now().isoformat(),
        "type": entry_type,
        "text": text[:MAX_ENTRY_LEN],
    })
    with open(MEMORY_TODAY, "a") as f:
        f.write(entry + "\n")
    return f"Remembered: {text[:80]}"


def recall() -> str:
    _ensure_dirs()
    _compact_if_new_day()
    sections = []

    if os.path.exists(MEMORY_MONTHLY):
        try:
            data = json.loads(open(MEMORY_MONTHLY).read())
            if data.get("text"):
                sections.append(f"### This month (patterns & threads)\n{data['text']}")
        except (json.JSONDecodeError, KeyError):
            pass

    day_lines = []
    for i in range(KEEP_DAYS, 0, -1):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        path = os.path.join(MEMORY_DAYS_DIR, f"{day}.json")
        if os.path.exists(path):
            try:
                data = json.loads(open(path).read())
                label = "Yesterday" if i == 1 else (datetime.now() - timedelta(days=i)).strftime("%a %b %d")
                day_lines.append(f"- {label}: {data.get('text', '(empty)')}")
            except (json.JSONDecodeError, KeyError):
                pass
    if day_lines:
        sections.append("### This week\n" + "\n".join(day_lines))

    if os.path.exists(MEMORY_TODAY):
        try:
            entries = [json.loads(l) for l in open(MEMORY_TODAY) if l.strip()]
            if entries:
                today_lines = []
                for e in entries:
                    ts = e.get("ts", "")
                    try:
                        t = datetime.fromisoformat(ts).strftime("%H:%M")
                    except Exception:
                        t = "?"
                    today_lines.append(f"- {t} {e.get('text', '')}")
                sections.append("### Today so far\n" + "\n".join(today_lines))
        except Exception:
            pass

    if not sections:
        return ""
    return "## Memory\n\n" + "\n\n".join(sections)


def _compact_if_new_day():
    if not os.path.exists(MEMORY_TODAY):
        return
    try:
        first_line = open(MEMORY_TODAY).readline().strip()
        if not first_line:
            return
        first_entry = json.loads(first_line)
        entry_date = first_entry["ts"][:10]
        today_str = datetime.now().strftime("%Y-%m-%d")
        if entry_date == today_str:
            return
        entries = [json.loads(l) for l in open(MEMORY_TODAY) if l.strip()]
        _compress_day(entry_date, entries)
        os.remove(MEMORY_TODAY)
        _prune_old_days()
    except Exception:
        pass


def _compress_day(date_str: str, entries: list):
    raw = "\n".join(f"- {e.get('ts', '')[11:16]} [{e.get('type','')}] {e.get('text','')}" for e in entries)
    try:
        summary = invoke_ai(
            f"Compress this day's activity log into a single concise paragraph (max 500 chars). "
            f"Focus on: key actions taken, decisions made, unresolved items, and people involved. "
            f"No headers or bullets — just a dense narrative summary.\n\nDate: {date_str}\n\n{raw[:4000]}",
            max_tokens=300, tier="memory"
        )
    except Exception:
        summary = f"{len(entries)} entries logged."
    path = os.path.join(MEMORY_DAYS_DIR, f"{date_str}.json")
    with open(path, "w") as f:
        json.dump({"date": date_str, "text": summary[:DAILY_SUMMARY_MAX]}, f)


def _prune_old_days():
    cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    expiring = []
    for fname in sorted(os.listdir(MEMORY_DAYS_DIR)):
        if fname.endswith(".json") and fname[:10] < cutoff:
            path = os.path.join(MEMORY_DAYS_DIR, fname)
            try:
                expiring.append(json.loads(open(path).read()))
            except Exception:
                pass
            os.remove(path)
    if expiring:
        _fold_into_monthly(expiring)


def _fold_into_monthly(expiring_days: list):
    existing = ""
    if os.path.exists(MEMORY_MONTHLY):
        try:
            existing = json.loads(open(MEMORY_MONTHLY).read()).get("text", "")
        except Exception:
            pass
    new_entries = "\n".join(f"- {d.get('date','')}: {d.get('text','')}" for d in expiring_days)
    cutoff_date = (datetime.now() - timedelta(weeks=KEEP_WEEKS)).strftime("%Y-%m-%d")
    try:
        summary = invoke_ai(
            f"Update this rolling monthly memory summary. Drop anything before {cutoff_date}. "
            f"Keep: recurring patterns, ongoing threads, key people, unresolved items, user preferences. "
            f"Max 2000 chars, dense narrative, no headers.\n\n"
            f"Existing monthly summary:\n{existing or '(none yet)'}\n\n"
            f"New days to fold in:\n{new_entries}",
            max_tokens=1000, tier="memory"
        )
    except Exception:
        summary = existing + "\n" + new_entries if existing else new_entries
    with open(MEMORY_MONTHLY, "w") as f:
        json.dump({"updated": datetime.now().isoformat(), "text": summary[:MONTHLY_MAX]}, f)
