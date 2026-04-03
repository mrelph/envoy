"""Observer agent — watches interactions and learns patterns over time."""

import json
import os
from datetime import datetime, timedelta

from agents.base import invoke_ai

OBSERVATIONS_FILE = os.path.expanduser("~/.envoy/memory/observations.jsonl")
PROCESS_FILE = os.path.expanduser("~/.envoy/process.md")

_ANALYZE_EVERY = 20  # analyze patterns every N observations
_obs_count = 0       # count since last analysis


def _ensure_dir():
    os.makedirs(os.path.dirname(OBSERVATIONS_FILE), exist_ok=True)


def observe(interaction_summary: str, outcome: str, domain: str = "") -> str:
    """Log an interaction and its outcome."""
    global _obs_count
    _ensure_dir()
    entry = json.dumps({
        "ts": datetime.now().isoformat(),
        "summary": interaction_summary[:500],
        "outcome": outcome[:500],
        "domain": domain,
    })
    with open(OBSERVATIONS_FILE, "a") as f:
        f.write(entry + "\n")
    _obs_count += 1
    return f"Observed: {interaction_summary[:80]}"


def maybe_analyze():
    """Run pattern analysis if enough observations have accumulated."""
    global _obs_count
    if _obs_count >= _ANALYZE_EVERY:
        _obs_count = 0
        try:
            _analyze_and_apply()
        except Exception:
            pass


def _analyze_and_apply():
    """Analyze recent patterns and auto-apply high-confidence learnings to process.md."""
    entries = _load_recent(7)
    if len(entries) < 10:
        return

    log = "\n".join(
        f"- [{e.get('domain','general')}] {e['summary'][:200]}"
        for e in entries[-50:]
    )

    # Load current process.md so AI doesn't suggest duplicates
    current_process = ""
    if os.path.exists(PROCESS_FILE):
        with open(PROCESS_FILE) as f:
            current_process = f.read()

    prompt = (
        f"Analyze these {len(entries)} user interactions from the last 7 days.\n"
        f"Identify clear, recurring patterns — things the user consistently does or prefers.\n\n"
        f"Current process rules (DO NOT duplicate these):\n{current_process[:2000]}\n\n"
        f"Interactions:\n{log}\n\n"
        f"Return ONLY new rules not already in the process doc. Format each as:\n"
        f"SECTION: rule text\n\n"
        f"Where SECTION is one of: Email, Slack, Calendar, Cleanup, General\n"
        f"Only include rules you're highly confident about (seen 3+ times). "
        f"Return NONE if no clear new patterns."
    )
    result = invoke_ai(prompt, max_tokens=400, tier="light")

    if not result or "NONE" in result.upper():
        return

    # Parse and apply each rule
    for line in result.strip().splitlines():
        line = line.strip().lstrip("- ")
        if ":" in line and not line.startswith("#"):
            section, rule = line.split(":", 1)
            section = section.strip()
            rule = rule.strip()
            if rule and section in ("Email", "Slack", "Calendar", "Cleanup", "General"):
                apply_learning(rule, section)


def _load_recent(days: int = 7) -> list:
    if not os.path.exists(OBSERVATIONS_FILE):
        return []
    cutoff = datetime.now() - timedelta(days=days)
    entries = []
    with open(OBSERVATIONS_FILE) as f:
        for line in f:
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

    with open(PROCESS_FILE) as f:
        content = f.read()
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
