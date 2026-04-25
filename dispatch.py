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
    "/doctor":    ("Health check — MCP, AWS, config, memory", None),
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
    ("System", ["/doctor", "/status", "/mwinit", "/models", "/skills", "/settings", "/backup", "/help", "/exit"]),
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

    if cmd == "/doctor":
        return (_run_doctor(), True)

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


def _run_doctor() -> str:
    """Comprehensive health check — MCP, AWS, config, models, memory, skills."""
    import json
    from pathlib import Path

    lines = ["# 🩺 Envoy Doctor\n"]
    ok_count = 0
    warn_count = 0
    err_count = 0

    def _ok(msg):
        nonlocal ok_count; ok_count += 1; lines.append(f"  ✅ {msg}")
    def _warn(msg):
        nonlocal warn_count; warn_count += 1; lines.append(f"  ⚠️  {msg}")
    def _err(msg):
        nonlocal err_count; err_count += 1; lines.append(f"  ❌ {msg}")

    # --- MCP Connections ---
    lines.append("\n## MCP Servers")
    try:
        from agents.base import check_mcp_connections
        status = check_mcp_connections()
        for name, connected in status.items():
            if connected:
                _ok(name)
            elif name in ("Outlook", "Phonetool"):
                _err(f"{name} — not connected (core functionality affected)")
            else:
                _warn(f"{name} — not connected")
    except Exception as e:
        _err(f"Could not check MCP: {e}")

    # --- AWS / Bedrock ---
    lines.append("\n## AWS Credentials")
    try:
        import boto3
        sts = boto3.client('sts', region_name='us-west-2')
        identity = sts.get_caller_identity()
        _ok(f"Authenticated as {identity.get('Arn', 'unknown')[:80]}")
    except Exception as e:
        _err(f"AWS credentials invalid — run `aws login` or check .env ({e})")

    # --- Models ---
    lines.append("\n## AI Models")
    try:
        from agents.base import _load_models, DEFAULT_MODELS
        models = _load_models()
        models_file = Path.home() / ".envoy" / "models.json"
        customized = models_file.exists()
        for tier in DEFAULT_MODELS:
            mid = models.get(tier, DEFAULT_MODELS[tier])
            is_default = mid == DEFAULT_MODELS[tier]
            label = f"{tier}: {mid.split('.')[-1][:30]}"
            if is_default:
                _ok(f"{label} (default)")
            else:
                _ok(f"{label} (custom)")
        if not customized:
            lines.append("  ℹ️  Using defaults — run `/models` to customize")
    except Exception as e:
        _warn(f"Could not load models: {e}")

    # --- Config Files ---
    lines.append("\n## Configuration")
    config_dir = Path.home() / ".envoy"
    for name, required_fields in [
        ("soul.md", ["Agent name"]),
        ("envoy.md", ["Alias"]),
        ("process.md", []),
    ]:
        path = config_dir / name
        if not path.exists():
            _warn(f"{name} — missing (run `envoy init`)")
            continue
        content = path.read_text()
        size = len(content)
        empty_fields = [f for f in required_fields if f"{f}:" in content and not content.split(f"{f}:")[1].split("\n")[0].strip()]
        if empty_fields:
            _warn(f"{name} ({size:,} chars) — empty fields: {', '.join(empty_fields)}")
        else:
            _ok(f"{name} ({size:,} chars)")

    # --- Knowledge Folder ---
    try:
        from agents.export import _configured_folders
        folders = _configured_folders()
        if folders.get("knowledge"):
            _ok(f"Knowledge Folder: {folders['knowledge']}")
        else:
            lines.append("  ℹ️  No Knowledge Folder configured (optional — for vault/second-brain)")
        if folders.get("exports"):
            _ok(f"Exports Folder: {folders['exports']}")
    except Exception:
        pass

    # --- Memory ---
    lines.append("\n## Memory")
    try:
        from agents.memory2 import ENTRIES_FILE, ENTITIES_FILE, SUMMARY_FILE, _load_entries, known_entities
        entries = _load_entries(days=14)
        entities = known_entities()
        entry_size = Path(ENTRIES_FILE).stat().st_size if Path(ENTRIES_FILE).exists() else 0
        _ok(f"{len(entries)} entries (last 14d), {len(entities)} entities, {entry_size:,} bytes on disk")
        if entry_size > 1_500_000:
            _warn(f"Memory file large ({entry_size:,} bytes) — run compression")
        summary_exists = Path(SUMMARY_FILE).exists()
        if summary_exists:
            import json as _json
            summaries = _json.loads(Path(SUMMARY_FILE).read_text())
            _ok(f"{len(summaries)} entity summaries")
        else:
            lines.append("  ℹ️  No compressed summaries yet (created automatically)")
    except Exception as e:
        _warn(f"Memory check failed: {e}")

    # --- Skills ---
    lines.append("\n## Skills")
    try:
        from agents.skills import get_skills
        skills = get_skills()
        if skills:
            _ok(f"{len(skills)} skills: {', '.join(skills.keys())}")
        else:
            lines.append("  ℹ️  No skills installed — add to ~/.envoy/skills/")
    except Exception as e:
        _warn(f"Skills check failed: {e}")

    # --- Routines ---
    try:
        from agents.heartbeat import get_routines
        routines = get_routines()
        routine_count = routines.count("\n- ")
        if routine_count:
            _ok(f"{routine_count} heartbeat routines")
        else:
            lines.append("  ℹ️  No routines — use `/routine` to add one")
    except Exception:
        pass

    # --- Cron ---
    try:
        import subprocess
        crontab = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        envoy_jobs = [l for l in crontab.splitlines() if "# envoy:" in l]
        if envoy_jobs:
            _ok(f"{len(envoy_jobs)} cron jobs")
        else:
            lines.append("  ℹ️  No cron jobs — use `/cron` to schedule automation")
    except Exception:
        pass

    # --- Summary ---
    total = ok_count + warn_count + err_count
    lines.append(f"\n---\n**{ok_count}** ✅  **{warn_count}** ⚠️  **{err_count}** ❌  ({total} checks)")
    if err_count:
        lines.append("\nFix ❌ items first — they affect core functionality.")
    elif warn_count:
        lines.append("\nLooking good! Address ⚠️ items when convenient.")
    else:
        lines.append("\nAll systems healthy. 🚀")

    return "\n".join(lines)


def _handle_models(arg: str) -> str:
    """Show current model assignments, change via /models <tier> <model>, or /models refresh."""
    import json
    from agents.base import _load_models, MODEL_CATALOG, MODELS_FILE, DEFAULT_MODELS, reload_models
    from ui import _fetch_model_catalog

    parts = arg.split() if arg else []
    tiers = list(DEFAULT_MODELS.keys())

    # /models refresh → re-fetch Bedrock catalog
    if len(parts) == 1 and parts[0].lower() == "refresh":
        live = _fetch_model_catalog(refresh=True)
        if not live:
            return "⚠️ Could not fetch Bedrock catalog — check AWS credentials. Using static list."
        return f"✓ Refreshed — {len(live)} models/profiles available. Run `/models` to see them."

    # Unrecognized single arg
    if len(parts) == 1:
        return (f"Usage: `/models` (show) · `/models refresh` · "
                f"`/models <tier#|name> <model#|id>`")

    # Live catalog (merge with static fallback so nothing disappears if Bedrock is down)
    live = _fetch_model_catalog(refresh=False)
    if live:
        catalog = live
    else:
        catalog = [(mid, name, desc) for mid, name, desc in MODEL_CATALOG]

    # /models <tier> <model> → update (accepts tier name or #, model id or #)
    if len(parts) >= 2:
        tier_sel, model_sel = parts[0], parts[1]
        # Resolve tier (numeric or name)
        if tier_sel.isdigit() and 1 <= int(tier_sel) <= len(tiers):
            tier = tiers[int(tier_sel) - 1]
        elif tier_sel.lower() in DEFAULT_MODELS:
            tier = tier_sel.lower()
        else:
            return f"Unknown tier '{tier_sel}'. Valid: {', '.join(tiers)} (or 1–{len(tiers)})"
        # Resolve model (numeric index into catalog, or raw id)
        if model_sel.isdigit() and 1 <= int(model_sel) <= len(catalog):
            model_id = catalog[int(model_sel) - 1][0]
        else:
            model_id = model_sel
            if not any(c[0] == model_id for c in catalog):
                return (f"⚠️ '{model_id}' not in catalog. Saving anyway — "
                        f"run `/models refresh` to verify. ")
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
        # Drop the cached supervisor agent so it picks up the new tier on next
        # call. Without this, the running session keeps the previous BedrockModel.
        from agent import reload_agent
        reload_agent()
        return f"✓ {tier} → {model_id}"

    # /models → show assignments + numbered catalog
    models = _load_models()
    lines = ["**Current Model Assignments**\n"]
    for i, tier in enumerate(tiers, 1):
        mid = models.get(tier, DEFAULT_MODELS[tier])
        label = next((c[1] for c in catalog if c[0] == mid), mid)
        lines.append(f"  `{i}` **{tier:<7}** → {label}  \n       *{mid}*")
    lines.append(f"\n**Available Models** ({'live' if live else 'static fallback'} — {len(catalog)} total)\n")
    for i, (mid, name, desc) in enumerate(catalog, 1):
        short = (desc or '')[:60]
        lines.append(f"  `{i:>3}` **{name}** — {short}  \n       `{mid}`")
    lines.append("")
    lines.append("**Change a tier:** `/models <tier#|name> <model#|id>`")
    lines.append("**Examples:** `/models 3 5`  ·  `/models light us.amazon.nova-micro-v1:0`")
    lines.append("**Refresh from Bedrock:** `/models refresh`")
    lines.append("")
    lines.append("*Tip: type just `<tier#> <model#>` (e.g. `3 5`) or `cancel` at the next prompt.*")
    return "\n".join(lines)
