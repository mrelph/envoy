"""Active learning loop — lightweight post-interaction reflection and self-improvement.

Four mechanisms:
1. reflect()          — log what happened after each command (fast, no AI)
2. detect_correction() — spot user corrections and auto-save to process.md (fast regex, AI only on match)
3. self_analyze()     — periodic pattern analysis + auto-apply (AI, runs weekly via heartbeat)
4. suggest_skill()    — detect repeated multi-step patterns and suggest skill creation (AI, rare)
"""

import os
import re
import time
from pathlib import Path

_ENVOY_DIR = Path.home() / ".envoy"
_LAST_ANALYSIS = _ENVOY_DIR / "learning_state.json"
_PROCESS_FILE = os.path.expanduser("~/.envoy/process.md")


def apply_learning(pattern: str, section: str = "General") -> str:
    """Append a learned rule to process.md under the given section."""
    header = f"## {section}"
    if not os.path.exists(_PROCESS_FILE):
        tmpl = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "process.md")
        if os.path.exists(tmpl):
            import shutil
            shutil.copy(tmpl, _PROCESS_FILE)
        else:
            with open(_PROCESS_FILE, "w") as f:
                f.write(f"# Process Memory\n\n{header}\n- {pattern}\n")
            return f"Created process memory: [{section}] {pattern}"
    with open(_PROCESS_FILE) as f:
        content = f.read()
    if header in content:
        content = content.replace(header, f"{header}\n- {pattern}", 1)
    else:
        content = content.rstrip() + f"\n\n{header}\n- {pattern}\n"
    with open(_PROCESS_FILE, "w") as f:
        f.write(content)
    return f"Learned: [{section}] {pattern}"


def analyze_patterns(days: int = 7) -> str:
    """Analyze recent observation entries for recurring patterns and propose rules."""
    from agents.memory2 import _load_entries
    from agents.base import invoke_ai
    entries = _load_entries(days)
    observations = [e for e in entries if e.get("type") == "observation"]
    if not observations:
        return f"No observations in the last {days} days."
    log = "\n".join(f"- {e['text'][:200]}" for e in observations[-50:])
    return invoke_ai(
        f"Analyze these {len(observations)} user interaction observations from the last {days} days. "
        f"Identify recurring patterns and preferences. For each pattern, suggest a concrete rule "
        f"that could be added to a process doc (sections: Email, Meetings, Cleanup, Slack, Calendar, General).\n"
        f"Format: one pattern per line as '- [Section] rule text'\n\n{log}",
        max_tokens=600, tier="light"
    )

# --- Correction detection patterns (no AI needed) ---

_CORRECTION_PATTERNS = re.compile(
    r"^(no[,.]?\s|wrong|don'?t do that|that'?s not|stop doing|never do|"
    r"i said|i meant|not what i|actually[,.]?\s|incorrect|"
    r"i don'?t want|please don'?t|quit|stop\s)",
    re.IGNORECASE
)

_PREFERENCE_PATTERNS = re.compile(
    r"(always|never|prefer|from now on|going forward|in the future|remember that|"
    r"next time|don'?t ever|make sure you)",
    re.IGNORECASE
)


def reflect(command: str, response: str, user_reply: str = "") -> None:
    """Log a clean structured observation after each command. No AI call.
    
    Stores WHAT HAPPENED, not raw output. Format: [domain] action — outcome
    """
    # Skip trivial interactions
    if not command or command.startswith("/help") or command.startswith("/exit"):
        return
    if len(response) < 20:
        return

    # Determine domain from command
    domain = _classify_domain(command)

    # Extract clean action (the command/intent) and outcome (first meaningful line)
    action = command.strip()[:80]
    outcome = _extract_outcome(response)

    entry = f"[{domain}] {action}"
    if outcome:
        entry += f" — {outcome}"

    # Determine importance
    importance = "routine"
    if user_reply:
        entry += f" | user: {user_reply[:60]}"
        # User follow-up suggests this was notable
        importance = "notable"
    if _CORRECTION_PATTERNS.search(user_reply or ""):
        importance = "permanent"

    try:
        from agents.memory2 import remember
        remember(entry, entry_type="observation", importance=importance)
    except Exception:
        pass  # Never break the main flow


def _classify_domain(command: str) -> str:
    """Classify command into a domain tag. Fast, no AI."""
    cmd = command.lower().strip().lstrip("/")
    if any(k in cmd for k in ("email", "inbox", "digest", "cleanup", "reply", "forward")):
        return "email"
    if any(k in cmd for k in ("slack", "dm", "channel", "message")):
        return "comms"
    if any(k in cmd for k in ("calendar", "meeting", "book", "findtime", "week")):
        return "calendar"
    if any(k in cmd for k in ("todo", "ticket", "task", "action")):
        return "tasks"
    if any(k in cmd for k in ("search", "lookup", "phonetool", "wiki", "kingpin")):
        return "research"
    if any(k in cmd for k in ("sharepoint", "onedrive", "file")):
        return "files"
    return "general"


def _extract_outcome(response: str) -> str:
    """Pull a clean one-line outcome from a response. No markdown, no JSON."""
    # Strip markdown formatting
    text = re.sub(r'[#*`\[\](){}|\\]', '', response)
    # Strip JSON-like content
    text = re.sub(r'\{[^}]*\}', '', text)
    # Get first non-empty line that's actually content
    for line in text.split("\n"):
        line = line.strip().strip("-•►▸› ")
        if len(line) > 15 and not line.startswith(("{'", "\"role\"", "Error", "I'm unable")):
            # Truncate to something useful
            return line[:120]
    return ""


def detect_correction(user_input: str, prev_response: str = "") -> str | None:
    """Check if user input is a correction/preference statement.
    
    Returns a process rule string if correction detected, None otherwise.
    Fast path: regex only. AI only called on match to formulate the rule.
    """
    if not user_input or len(user_input) < 5:
        return None

    is_correction = bool(_CORRECTION_PATTERNS.search(user_input))
    is_preference = bool(_PREFERENCE_PATTERNS.search(user_input))

    if not is_correction and not is_preference:
        return None

    # Use AI to formulate a concise process rule (light tier = fast + cheap)
    try:
        from agents.base import invoke_ai
        context = f"Previous response: {prev_response[:200]}\n" if prev_response else ""
        rule = invoke_ai(
            f"{context}User said: \"{user_input}\"\n\n"
            "This is a correction or preference. Write ONE concise process rule (max 15 words) "
            "that captures what the agent should do differently. Start with a verb. "
            "Also output the section it belongs in (Email, Meetings, Cleanup, Slack, Calendar, General).\n"
            "Format: SECTION: rule text",
            max_tokens=50, tier="light"
        ).strip()

        if ":" in rule:
            section, rule_text = rule.split(":", 1)
            section = section.strip().title()
            rule_text = rule_text.strip()
            if section not in ("Email", "Meetings", "Cleanup", "Slack", "Calendar", "General",
                               "Briefings", "Tickets", "Safety & Confirmations"):
                section = "General"
            return f"[{section}] {rule_text}"
    except Exception:
        pass
    return None


def apply_correction(rule: str) -> str:
    """Apply a detected correction to process.md. Returns confirmation message."""
    if not rule or "]" not in rule:
        return ""
    section = rule.split("]")[0].strip("[")
    text = rule.split("]", 1)[1].strip()
    try:
        return apply_learning(text, section)
    except Exception as e:
        return f"Failed to save: {e}"


def self_analyze() -> str:
    """Run periodic pattern analysis on observations. Returns suggested rules.
    
    Designed to run weekly via heartbeat. Uses AI (medium tier) but only on
    accumulated observations — not per-interaction.
    """
    import json

    # Rate limit: at most once per 7 days
    state = _load_state()
    last = state.get("last_analysis", 0)
    if time.time() - last < 7 * 86400:
        return ""

    try:
        from agents.memory2 import _load_entries
        entries = _load_entries(days=7)
        observations = [e for e in entries if e.get("type") == "observation"]
        if len(observations) < 5:
            return ""  # Not enough data

        log = "\n".join(f"- {e['text'][:150]}" for e in observations[-40:])

        from agents.base import invoke_ai
        result = invoke_ai(
            f"Analyze these {len(observations)} agent observations from the past week.\n"
            "Identify 1-3 HIGH-CONFIDENCE recurring patterns (things that happened 3+ times).\n"
            "For each, output a process rule.\n"
            "Format: one per line as 'SECTION: rule text' (sections: Email, Meetings, Cleanup, Slack, Calendar, General)\n"
            "Only output rules you're very confident about. If nothing is clear, output NONE.\n\n"
            f"{log}",
            max_tokens=200, tier="medium"
        ).strip()

        # Save state
        state["last_analysis"] = time.time()
        _save_state(state)

        if not result or result.upper() == "NONE":
            return ""
        return result
    except Exception:
        return ""


def auto_apply_analysis(analysis: str) -> list[str]:
    """Apply high-confidence rules from self_analyze. Returns list of applied rules."""
    if not analysis:
        return []
    applied = []
    for line in analysis.strip().splitlines():
        line = line.strip().lstrip("- ")
        if ":" in line and len(line) > 5:
            section, rule_text = line.split(":", 1)
            section = section.strip().title()
            rule_text = rule_text.strip()
            if not rule_text:
                continue
            try:
                apply_learning(rule_text, section)
                applied.append(f"[{section}] {rule_text}")
            except Exception:
                pass
    return applied


def suggest_skill(observations: list[dict] = None) -> str | None:
    """Detect repeated multi-step patterns that could become a skill.
    
    Only runs during self_analyze (weekly). Returns a suggestion string or None.
    """
    try:
        from agents.memory2 import _load_entries
        if observations is None:
            observations = [e for e in _load_entries(days=14) if e.get("type") == "observation"]

        if len(observations) < 10:
            return None

        # Look for repeated command sequences (cheap heuristic — no AI)
        commands = []
        for e in observations:
            text = e.get("text", "")
            if "→" in text:
                cmd = text.split("→")[0].strip()
                if cmd.startswith("/"):
                    commands.append(cmd.split()[0])

        # Find commands used 5+ times in 14 days
        from collections import Counter
        freq = Counter(commands)
        heavy = [cmd for cmd, count in freq.items() if count >= 5]

        if not heavy:
            return None

        # Check for repeated sequences (2-3 commands in a row, same pattern)
        sequences = []
        for i in range(len(commands) - 1):
            seq = f"{commands[i]} → {commands[i+1]}"
            sequences.append(seq)

        seq_freq = Counter(sequences)
        repeated = [(seq, c) for seq, c in seq_freq.items() if c >= 3]

        if not repeated:
            return None

        top = repeated[0]
        return (
            f"💡 **Skill suggestion:** You frequently run `{top[0]}` ({top[1]} times in 14 days). "
            f"Want me to create a combined skill for this workflow?"
        )
    except Exception:
        return None


def _load_state() -> dict:
    import json
    try:
        return json.loads(_LAST_ANALYSIS.read_text())
    except Exception:
        return {}


def _save_state(state: dict):
    import json
    _ENVOY_DIR.mkdir(parents=True, exist_ok=True)
    _LAST_ANALYSIS.write_text(json.dumps(state))
