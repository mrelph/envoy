"""Command dispatch — shared between TUI and plain REPL.

dispatch(raw_input, agent) → (result_or_cmd, handled)

If handled is True, result_or_cmd is the final output text (caller just prints it).
If handled is False, result_or_cmd is the raw cmd string — a system command the
UI layer must handle itself (e.g., /help, /status, /settings, /exit).
"""

import os

_USER = os.environ.get("USER", "")

# --- Slash command table: cmd → (description, prompt_template | None) ---
# prompt_template uses {days} and {arg} placeholders.

COMMANDS = {
    # Briefings
    "/briefing":  ("Full briefing (calendar+email+slack)", "Give me a full briefing — calendar, inbox, and Slack"),
    "/calendar":  ("Review today's calendar",              "Review my calendar for today"),
    "/week":      ("Calendar for the week ahead",          "Review my calendar for the week ahead"),
    "/todo":      ("Show my action items",                 "What action items do I have pending?"),
    # Scans & Digests
    "/digest":    ("Team email digest",                    "Generate a team digest for the last {days} days"),
    "/boss":      ("Boss tracker",                         "Track my management chain's recent emails"),
    "/customers": ("Customer email scan",                  "Scan for external customer emails with action items from the last {days} days"),
    "/cleanup":   ("Inbox cleanup scan",                   "Scan my inbox for junk to clean up, last {days} days"),
    "/slack":     ("Slack scan",                           "Scan my Slack channels for critical info and actions"),
    "/tickets":   ("Scan open tickets",                    "Scan my open tickets and SIMs"),
    # Catch-up
    "/catchup":   ("PTO catch-up report",                  "I was out of office for {days} days, give me a full catch-up"),
    "/slack-catchup": ("Focused Slack catch-up",           "Give me a focused Slack catch-up for the last {days} days — unread channels, mentions, and DMs"),
    "/yesterbox":     ("Yesterbox — yesterday's DMs",       "Run yesterbox for yesterday's messages"),
    # Analysis
    "/cal-audit":      ("Calendar audit",                  "Audit my calendar for the next {days} days — meeting load, focus time, and what to decline"),
    "/response-times": ("Email response time analysis",    "Analyze my email response time patterns for the last {days} days"),
    "/followup":       ("Unanswered sent emails",          "Scan my sent emails for unanswered threads from the last {days} days"),
    "/commitments":    ("Promises & commitments tracker",  "Scan my sent messages for commitments and promises from the last {days} days"),
    # Prep (needs {arg})
    "/prep-1on1":    ("1:1 prep brief",                    "Generate a 1:1 prep brief for my meeting with {arg}"),
    "/prep-meeting": ("Meeting prep brief",                "Generate a prep brief for my meeting: {arg}"),
    # Actions (needs {arg})
    "/reply":     ("Reply to an email",                    "Reply to the email about {arg}"),
    "/ea":        ("Send something to your EA",            "Send this to my EA: {arg}"),
    "/book":      ("Book a meeting room",                  "Find me a room in {arg}"),
    "/findtime":  ("Find available meeting times",         "Find me available meeting times this week"),
    "/search":    ("Search Slack history",                 "Search Slack for: {arg}"),
    "/sharepoint": ("Search or browse SharePoint/OneDrive", "On SharePoint/OneDrive: {arg}"),
    # Reviews
    "/eod":       ("End-of-day summary",                   "Activate the eod skill and generate my end-of-day summary"),
    "/weekly":    ("Weekly review",                        "Activate the weekly skill and generate my weekly review"),
    "/cron":      ("Manage scheduled jobs",                "Show my cron jobs and available presets"),
    # Heartbeat
    "/routine":   ("Add a routine",                        None),
    "/routines":  ("View routines",                        None),
    "/heartbeat": ("Run heartbeat now",                    None),
    "/suggest-routines": ("AI-suggested routines",         None),
    # System (handled by UI layer, not dispatch)
    "/help":      ("Show available commands",              None),
    "/status":    ("Refresh MCP server status",            None),
    "/mwinit":    ("Re-authenticate Midway",               None),
    "/models":    ("Show/edit AI model assignments",       None),
    "/settings":  ("Edit personality and config",          None),
    "/skills":    ("List configured skills",               None),
    "/backup":    ("Back up config, memory, and state",    None),
    "/exit":      ("Exit Envoy",                           None),
}

# Commands that need an {arg} and should prompt if missing
ARG_COMMANDS = {"/prep-1on1", "/prep-meeting", "/reply", "/ea", "/book", "/search", "/sharepoint"}

# Default days per command
DEFAULT_DAYS = {
    "/digest": 7, "/customers": 14, "/cleanup": 14, "/catchup": 5,
    "/slack-catchup": 3, "/cal-audit": 5, "/response-times": 7,
    "/followup": 7, "/commitments": 7,
}

# Command groups for help display
COMMAND_GROUPS = [
    ("Briefings", ["/briefing", "/calendar", "/week", "/todo"]),
    ("Digests & Scans", ["/digest", "/boss", "/customers", "/cleanup", "/slack", "/tickets"]),
    ("Catch-up", ["/catchup", "/slack-catchup", "/yesterbox"]),
    ("Analysis", ["/cal-audit", "/response-times", "/followup", "/commitments"]),
    ("Prep", ["/prep-1on1", "/prep-meeting"]),
    ("Actions", ["/reply", "/ea", "/book", "/findtime", "/search", "/sharepoint"]),
    ("Reviews", ["/eod", "/weekly", "/cron"]),
    ("Heartbeat", ["/routine", "/routines", "/heartbeat", "/suggest-routines"]),
    ("System", ["/status", "/mwinit", "/models", "/skills", "/settings", "/backup", "/help", "/exit"]),
]


def dispatch(raw: str, agent):
    """Parse input and return (response_text, handled).

    If handled is True, response_text is the final output (no agent call needed).
    If handled is False, response_text is None and the caller should call agent(prompt).
    Returns (prompt_or_result, handled_internally).
    """
    stripped = raw.strip()
    if not stripped:
        return None, True

    parts = stripped.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    # --- Internally handled commands ---
    if cmd == "/routine":
        from agents.heartbeat import add_routine
        if not arg:
            return ("Usage: /routine <what to check for>", True)
        return (add_routine(arg), True)

    if cmd == "/routines":
        from agents.heartbeat import get_routines
        return (get_routines(), True)

    if cmd == "/heartbeat":
        from agents.heartbeat import run_heartbeat
        return (run_heartbeat(quiet=False, notify="none"), True)

    if cmd == "/suggest-routines":
        from agents.heartbeat import suggest_routines
        return (suggest_routines(), True)

    if cmd == "/skills":
        from agents.skills import get_skills
        skills = get_skills()
        if not skills:
            return ("No skills configured. Add a SKILL.md to ~/.envoy/skills/<name>/", True)
        lines = ["**Configured Skills**\n"]
        for s in skills.values():
            lines.append(f"- **{s['name']}** — {s['description']}")
        lines.append(f"\n{len(skills)} skills loaded from ~/.envoy/skills/ and ~/.agents/skills/")
        return ("\n".join(lines), True)

    if cmd == "/models":
        return (_handle_models(arg), True)

    # --- Commands needing an arg ---
    if cmd in ARG_COMMANDS and not arg:
        labels = {
            "/prep-1on1": "alias", "/prep-meeting": "meeting subject",
            "/reply": "which email + your reply", "/ea": "message for EA",
            "/book": "building + time", "/search": "query", "/sharepoint": "query",
        }
        return (f"Usage: {cmd} <{labels.get(cmd, 'argument')}>", True)

    # --- Slash command with template ---
    entry = COMMANDS.get(cmd)
    if entry and entry[1]:
        template = entry[1]
        days = int(arg) if arg.isdigit() else DEFAULT_DAYS.get(cmd, 7)
        if not arg:
            arg = "my next meeting" if cmd == "/prep-meeting" else ""
        prompt = template.format(days=days, arg=arg)
        return (agent(prompt), True)

    # --- System commands return None — caller handles ---
    if cmd in ("/help", "/status", "/settings", "/backup", "/exit"):
        return (cmd, False)  # signal to caller

    # --- Freeform natural language ---
    return (agent(stripped), True)


def _handle_models(arg: str) -> str:
    """Show current model assignments, or update one via: /models <tier> <model_id>"""
    import json
    from agents.base import _load_models, MODEL_CATALOG, MODELS_FILE, DEFAULT_MODELS, reload_models
    parts = arg.split() if arg else []

    if len(parts) >= 2:
        tier, model_id = parts[0].lower(), parts[1]
        if tier not in DEFAULT_MODELS:
            return f"Unknown tier '{tier}'. Valid: {', '.join(DEFAULT_MODELS)}"
        current = {}
        try:
            with open(MODELS_FILE) as f:
                current = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        current[tier] = model_id
        os.makedirs(os.path.dirname(MODELS_FILE), exist_ok=True)
        with open(MODELS_FILE, "w") as f:
            json.dump(current, f, indent=2)
        reload_models()
        return f"✓ {tier} → {model_id}"

    models = _load_models()
    lines = ["**Current Model Assignments**\n"]
    for tier in DEFAULT_MODELS:
        mid = models.get(tier, DEFAULT_MODELS[tier])
        label = next((c[1] for c in MODEL_CATALOG if c[0] == mid), mid)
        lines.append(f"- `{tier:<7}` {label}  *({mid})*")
    lines.append("\n**Available Models**")
    for mid, name, desc in MODEL_CATALOG:
        lines.append(f"- **{name}** — {desc}  \n  `{mid}`")
    lines.append("\n**Usage:** `/models <tier> <model_id>`")
    lines.append("**Example:** `/models light us.amazon.nova-micro-v1:0`")
    return "\n".join(lines)
