"""Meta tools — time, tokens, skills, memory, observer."""

from strands import tool
from agents.base import invoke_ai, format_token_usage
from agents import memory2 as memory


@tool
def current_time() -> str:
    """Get the current date, time, and timezone."""
    from datetime import datetime, timezone, timedelta
    import time as _time
    is_dst = _time.localtime().tm_isdst > 0
    utc_offset = timedelta(seconds=-_time.altzone if is_dst else -_time.timezone)
    now = datetime.now(timezone(utc_offset))
    tz_name = _time.tzname[1] if is_dst else _time.tzname[0]
    return now.strftime(f'%A, %B %d %Y at %I:%M %p {tz_name} (UTC%z)')


@tool
def token_usage() -> str:
    """Show AI token usage for the current session."""
    return format_token_usage()


@tool
def recall_memory(query: str = "", limit: int = 20) -> str:
    """Recall memory by topic, person, or project.

    Args:
        query: Entity name, person, project, or topic (empty = general recall)
        limit: Max entries to return
    """
    return memory.recall(query, limit)


@tool
def observe_interaction(interaction_summary: str, outcome: str, domain: str = "") -> str:
    """Log an interaction observation.

    Args:
        interaction_summary: What happened
        outcome: What the user preferred
        domain: Category — Email, Meetings, Cleanup, Slack, Calendar, or blank
    """
    return memory.remember(f"{interaction_summary} → {outcome}", entry_type="observation")


@tool
def analyze_patterns(days: int = 7) -> str:
    """Analyze recent memory entries to identify recurring patterns.

    Args:
        days: How many days back to analyze
    """
    entries = memory._load_entries(days)
    observations = [e for e in entries if e.get("type") == "observation"]
    if not observations:
        return f"No observations in the last {days} days."
    log = "\n".join(f"- [{e.get('entities',[])}] {e['text']}" for e in observations[-50:])
    return invoke_ai(
        f"Analyze these {len(observations)} observations. Identify recurring patterns. "
        f"For each, suggest a rule for process.md (sections: Email, Meetings, Cleanup, Slack, Calendar, General).\n"
        f"Format: one per line as '- [Section] rule'\n\n{log}",
        max_tokens=600, tier="light"
    )


@tool
def get_observer_insights() -> str:
    """Get a summary of what the observer has learned."""
    entries = memory._load_entries(days=7)
    observations = [e for e in entries if e.get("type") == "observation"]
    if not observations:
        return "No observations recorded yet."
    domains = {}
    for e in observations:
        for ent in e.get("entities", []):
            domains[ent] = domains.get(ent, 0) + 1
    domain_summary = ", ".join(f"{k}: {v}" for k, v in sorted(domains.items(), key=lambda x: -x[1])[:10])
    recent = "\n".join(f"- {e['ts'][:16]} {e['text'][:100]}" for e in observations[-20:])
    return f"## Observer Insights\n\n**{len(observations)} observations** (last 7 days): {domain_summary}\n\n### Recent\n{recent}"


ALL_META_TOOLS = [current_time, token_usage, recall_memory, observe_interaction,
                  analyze_patterns, get_observer_insights]
