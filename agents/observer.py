"""Observer agent — watches interactions and learns patterns over time."""

import json
import os
from datetime import datetime, timedelta

from agents.base import invoke_ai

OBSERVATIONS_FILE = os.path.expanduser("~/.envoy/memory/observations.jsonl")
PROCESS_FILE = os.path.expanduser("~/.envoy/process.md")


def _ensure_dir():
    os.makedirs(os.path.dirname(OBSERVATIONS_FILE), exist_ok=True)


def observe(interaction_summary: str, outcome: str, domain: str = "") -> str:
    """Log an interaction and its outcome."""
    _ensure_dir()
    entry = json.dumps({
        "ts": datetime.now().isoformat(),
        "summary": interaction_summary[:500],
        "outcome": outcome[:500],
        "domain": domain,
    })
    with open(OBSERVATIONS_FILE, "a") as f:
        f.write(entry + "\n")
    return f"Observed: {interaction_summary[:80]}"


def _load_recent(days: int = 7) -> list:
    if not os.path.exists(OBSERVATIONS_FILE):
        return []
    cutoff = datetime.now() - timedelta(days=days)
    entries = []
    for line in open(OBSERVATIONS_FILE):
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if datetime.fromisoformat(e["ts"]) >= cutoff:
                entries.append(e)
        except Exception:
            pass
    return entries


def analyze_patterns(days: int = 7) -> str:
    """Analyze recent observations for recurring patterns."""
    entries = _load_recent(days)
    if not entries:
        return "No observations in the last {} days.".format(days)

    log = "\n".join(
        f"- [{e.get('domain','general')}] {e['summary']} → {e['outcome']}"
        for e in entries[-50:]
    )
    prompt = (
        f"Analyze these {len(entries)} user interaction observations from the last {days} days. "
        f"Identify recurring patterns and preferences. For each pattern, suggest a concrete rule "
        f"that could be added to a process doc (sections: Email, Meetings, Cleanup, Slack, Calendar, General).\n"
        f"Format: one pattern per line as '- [Section] rule text'\n\n{log}"
    )
    result = invoke_ai(prompt, max_tokens=600, tier="light")
    return f"## Pattern Analysis ({len(entries)} observations, {days}d)\n\n{result}"


def apply_learning(pattern: str, section: str = "General") -> str:
    """Append a learned rule to the appropriate section of process.md."""
    header = f"## {section}"
    if not os.path.exists(PROCESS_FILE):
        tmpl = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "process.md")
        if os.path.exists(tmpl):
            import shutil
            shutil.copy(tmpl, PROCESS_FILE)
        else:
            with open(PROCESS_FILE, "w") as f:
                f.write(f"# Process Memory\n\n{header}\n- {pattern}\n")
            return f"Created process memory: [{section}] {pattern}"

    content = open(PROCESS_FILE).read()
    if header in content:
        content = content.replace(header, f"{header}\n- {pattern}", 1)
    else:
        content = content.rstrip() + f"\n\n{header}\n- {pattern}\n"
    with open(PROCESS_FILE, "w") as f:
        f.write(content)
    return f"Learned: [{section}] {pattern}"


def get_insights() -> str:
    """Return summary of recent observations and identified patterns."""
    entries = _load_recent(7)
    if not entries:
        return "No observations recorded yet."

    recent = "\n".join(
        f"- {e.get('ts','')[:16]} [{e.get('domain','general')}] {e['summary'][:100]}"
        for e in entries[-20:]
    )

    domains = {}
    for e in entries:
        d = e.get("domain", "general") or "general"
        domains[d] = domains.get(d, 0) + 1
    domain_summary = ", ".join(f"{k}: {v}" for k, v in sorted(domains.items(), key=lambda x: -x[1]))

    return (
        f"## Observer Insights\n\n"
        f"**{len(entries)} observations** (last 7 days) across: {domain_summary}\n\n"
        f"### Recent\n{recent}"
    )
