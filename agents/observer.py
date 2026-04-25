"""Observer agent — thin wrapper that redirects to memory2.

All observation storage now goes through memory2.remember(entry_type="observation").
This module exists for backward compatibility only.
"""

from agents.memory2 import remember, _load_entries, _extract_entities
from agents.base import invoke_ai

PROCESS_FILE = __import__("os").path.expanduser("~/.envoy/process.md")


def observe(interaction_summary: str, outcome: str, domain: str = "") -> str:
    """Log an interaction — redirects to memory2."""
    text = f"[{domain}] {interaction_summary[:200]} → {outcome[:200]}" if domain else f"{interaction_summary[:200]} → {outcome[:200]}"
    return remember(text, entry_type="observation")


def maybe_analyze():
    """No-op — auto-analysis removed. Use analyze_patterns() explicitly."""
    pass


def analyze_patterns(days: int = 7) -> str:
    """Analyze recent observations for recurring patterns."""
    entries = _load_entries(days)
    observations = [e for e in entries if e.get("type") == "observation"]
    if not observations:
        return f"No observations in the last {days} days."
    log = "\n".join(
        f"- {e['text'][:200]}" for e in observations[-50:]
    )
    return invoke_ai(
        f"Analyze these {len(observations)} user interaction observations from the last {days} days. "
        f"Identify recurring patterns and preferences. For each pattern, suggest a concrete rule "
        f"that could be added to a process doc (sections: Email, Meetings, Cleanup, Slack, Calendar, General).\n"
        f"Format: one pattern per line as '- [Section] rule text'\n\n{log}",
        max_tokens=600, tier="light"
    )


def apply_learning(pattern: str, section: str = "General") -> str:
    """Append a learned rule to process.md."""
    import os
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
    """Return summary of recent observations from memory2."""
    entries = _load_entries(7)
    observations = [e for e in entries if e.get("type") == "observation"]
    if not observations:
        return "No observations recorded yet."
    recent = "\n".join(
        f"- {e.get('ts', '')[:16]} {e['text'][:100]}" for e in observations[-20:]
    )
    return f"## Observer Insights\n\n**{len(observations)} observations** (last 7 days)\n\n### Recent\n{recent}"
