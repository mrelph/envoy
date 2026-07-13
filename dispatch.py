"""Command dispatch — shared between TUI and plain REPL.

dispatch(raw_input, agent) → (result_or_cmd, handled)

If handled is True, result_or_cmd is the final output text (caller just prints it).
If handled is False, result_or_cmd is the raw cmd string — a system command the
UI layer must handle itself (e.g., /help, /status, /settings, /exit).
"""

import os
import threading

_last_response = ""  # tracks last agent response for correction detection

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
    "/yesterbox":     ("Yesterbox — yesterday's DMs",       "Run yesterbox for the last {days} days of messages"),
    # Analysis
    "/team-health":    ("Team health dashboard",           None),
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
    "/schedule":  ("Smart scheduling — find times, book rooms", None),
    "/search":    ("Search Slack history",                 "Search Slack for: {arg}"),
    "/sharepoint": ("Search or browse SharePoint/OneDrive", "On SharePoint/OneDrive: {arg}"),
    # Reviews
    "/eod":       ("End-of-day summary",                   "Activate the eod skill and generate my end-of-day summary"),
    "/weekly":    ("Weekly review",                        "Activate the weekly skill and generate my weekly review"),
    "/cron":      ("Manage scheduled jobs",                "Show my cron jobs and available presets"),
    # Vault / Knowledge
    "/vault":     ("Search your Second Brain vault",       "Activate the brain-query skill and search my vault for: {arg}"),
    "/synthesize": ("Connect the dots across vault pages", "Activate the brain-synthesize skill and synthesize what I know about: {arg}"),
    "/pulse":     ("Partner relationship health check",    "Activate the partner-pulse skill and show me the partner pulse"),
    "/dossier":   ("Build a partner dossier",             "Activate the partner-dossier skill and build a dossier on: {arg}"),
    "/pre-game":  ("Deep meeting prep (super brief)",     "Activate the pre-game skill and pre-game for: {arg}"),
    "/daily-note": ("Daily reflection note",              "Activate the daily-note skill and create my daily note"),
    "/vault-health": ("Vault structural health check",    "Activate the brain-lint skill and lint my vault"),
    "/ingest":    ("Process vault inbox/sources",         "Activate the brain-ingest skill and ingest my brain inbox"),
    "/exec-sponsor": ("Executive sponsor intel brief",    "Activate the exec-sponsor-insights skill and build an exec sponsor brief for: {arg}"),
    "/save-email": ("Save an email to your vault",        "Activate the email-to-vault skill and save that email to my vault: {arg}"),
    # Heartbeat
    "/routine":   ("Add a routine",                        None),
    "/routines":  ("View routines",                        None),
    "/heartbeat": ("Run heartbeat now",                    None),
    "/suggest-routines": ("AI-suggested routines",         None),
    # Skills
    "/build-skill":      ("Build a new skill from description", None),
    "/suggest-skills":   ("AI-suggested skills from history",   None),
    # System (handled by UI layer, not dispatch)
    "/help":      ("Show available commands",              None),
    "/status":    ("Refresh MCP server status",            None),

    "/models":    ("Show/edit AI model assignments",       None),
    "/settings":  ("Edit personality and config",          None),
    "/mcp":       ("Manage MCP servers (add/remove/list)", None),
    "/skills":    ("List configured skills",               None),
    "/backup":    ("Back up config, memory, and state",    None),
    "/doctor":    ("Health check — MCP, AWS, config, memory", None),
    "/learn":     ("Review/confirm/reject learned rules",  None),
    "/exit":      ("Exit Envoy",                           None),
}

# Commands that need an {arg} and should prompt if missing.
# Note: /prep-meeting is intentionally NOT here — it defaults to "my next meeting".
ARG_COMMANDS = {"/prep-1on1", "/reply", "/ea", "/book", "/schedule", "/search", "/sharepoint", "/vault", "/synthesize", "/dossier", "/pre-game", "/exec-sponsor", "/save-email"}

# Default days per command
DEFAULT_DAYS = {
    "/digest": 7, "/customers": 14, "/cleanup": 14, "/catchup": 5,
    "/slack-catchup": 3, "/cal-audit": 5, "/response-times": 7,
    "/followup": 7, "/commitments": 7, "/yesterbox": 1, "/team-health": 7,
}

# Command groups for help display
COMMAND_GROUPS = [
    ("Briefings", ["/briefing", "/calendar", "/week", "/todo"]),
    ("Digests & Scans", ["/digest", "/boss", "/customers", "/cleanup", "/slack", "/tickets"]),
    ("Catch-up", ["/catchup", "/slack-catchup", "/yesterbox"]),
    ("Analysis", ["/cal-audit", "/response-times", "/followup", "/commitments", "/team-health"]),
    ("Prep", ["/prep-1on1", "/prep-meeting"]),
    ("Actions", ["/reply", "/ea", "/book", "/findtime", "/schedule", "/search", "/sharepoint"]),
    ("Reviews", ["/eod", "/weekly", "/cron"]),
    ("Heartbeat", ["/routine", "/routines", "/heartbeat", "/suggest-routines"]),
    ("Skills", ["/build-skill", "/suggest-skills", "/skills"]),
    ("System", ["/doctor", "/status", "/models", "/learn", "/mcp", "/settings", "/backup", "/help", "/exit"]),
]


# --- Shared command-prompt template loader ---
#
# templates/commands.md is the documented, user-overridable (~/.envoy/commands.md)
# home for the longer-form prompts behind `envoy <cmd>` CLI subcommands. cli.py and
# dispatch() both build prompts from it via these two helpers so TUI/REPL slash
# commands and CLI subcommands never drift apart. Commands with no matching section
# below fall back to the short hardcoded template strings in COMMANDS above.

def _load_commands() -> dict:
    """Parse commands.md into {name: template} dict.

    User overrides at ~/.envoy/commands.md take precedence over the bundled
    templates/commands.md if present.
    """
    import re
    from agents.paths import commands_file
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'commands.md')
    user_path = str(commands_file())
    if os.path.exists(user_path):
        path = user_path
    with open(path) as f:
        text = f.read()
    commands = {}
    for block in re.split(r'\n## ', text):
        lines = block.strip().splitlines()
        if not lines:
            continue
        name = lines[0].strip().lower()
        body = '\n'.join(lines[1:]).strip()
        if body:
            commands[name] = body
    return commands


def _build_prompt(template: str, **kwargs) -> str:
    """Build an agent prompt from a command template, expanding {if flag} conditionals."""
    import re
    def _expand_if(m):
        key = m.group(1)
        rest = m.group(2).strip()
        val = kwargs.get(key)
        if val:
            return rest.replace(f'{{{key}}}', str(val))
        return ''
    result = re.sub(r'\{if\s+(\w+)\}\s*(.*)', _expand_if, template)
    for k, v in kwargs.items():
        result = result.replace(f'{{{k}}}', str(v) if v else '')
    result = '\n'.join(line for line in result.splitlines() if line.strip())
    return result


def _template_kwargs(cmd: str, days: int, arg: str) -> dict:
    """Extra kwargs for template-sourced prompts, beyond {days}/{arg}.

    Mirrors what cli.py's subcommands pass for the same commands.md sections
    (alias, limit, person, meeting, ...). Slash commands have no CLI-flag
    equivalents for optional extras (--vip, --team, --email, ...), so those
    simply stay unset — their {if ...} lines in the template drop out.
    """
    kwargs = {"days": days, "alias": os.environ.get("USER", "")}
    if cmd == "/cleanup":
        kwargs["limit"] = 100
    elif cmd == "/prep-1on1":
        kwargs["person"] = arg
    elif cmd == "/prep-meeting":
        kwargs["meeting"] = arg
    return kwargs


def dispatch(raw: str, agent):
    """Parse input and return (response_text, handled).

    If handled is True, response_text is the final output (no agent call needed).
    If handled is False, response_text is None and the caller should call agent(prompt).
    Returns (prompt_or_result, handled_internally).
    """
    try:
        from agents.confirm import set_user_turn
        set_user_turn(raw)
    except Exception:
        pass

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

    if cmd == "/build-skill":
        from agents.skill_builder import generate_skill, save_skill
        if not arg:
            return ("Usage: /build-skill <description of what the skill should do>", True)
        content, slug = generate_skill(arg)
        path = save_skill(content, slug)
        return (f"✅ Skill **{slug}** created → `{path}`\n\n{content}", True)

    if cmd == "/suggest-skills":
        from agents.skill_builder import suggest_skills
        days = int(arg) if arg and arg.isdigit() else 14
        return (suggest_skills(days), True)

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

    if cmd == "/learn":
        return (_handle_learn(arg), True)

    # --- Commands needing an arg ---
    if cmd in ARG_COMMANDS and not arg:
        labels = {
            "/prep-1on1": "alias", "/prep-meeting": "meeting subject",
            "/reply": "which email + your reply", "/ea": "message for EA",
            "/book": "building + time",
            "/schedule": "request, e.g. 30m with jsmith next week, find room at SEA54",
            "/search": "query", "/sharepoint": "query",
            "/vault": "topic to search", "/synthesize": "topic to connect",
            "/dossier": "partner name", "/pre-game": "meeting or company name",
            "/exec-sponsor": "account or partner name", "/save-email": "email subject or sender",
        }
        return (f"Usage: {cmd} <{labels.get(cmd, 'argument')}>", True)

    # --- Smart scheduling (multi-step: proposes times, user confirms next turn) ---
    if cmd == "/schedule":
        from agents.scheduling import schedule
        return (schedule(arg), True)

    # --- Team health dashboard ---
    if cmd == "/team-health":
        from agents.workflows import team_health
        days = int(arg) if arg and arg.isdigit() else DEFAULT_DAYS.get("/team-health", 7)
        alias = arg if arg and not arg.isdigit() else ""
        return (team_health(alias, days=days), True)

    # --- Slash command with template ---
    entry = COMMANDS.get(cmd)
    if entry and entry[1]:
        # Days-taking commands (those listed in DEFAULT_DAYS) silently dropped
        # non-numeric args (e.g. "/digest last week") and fell back to the
        # default with no indication anything was ignored. If the command's
        # template actually has a place for free-text ({arg}), pass it through
        # there instead of discarding it.
        day_notice = ""
        supports_arg = "{arg}" in entry[1]
        if arg and not arg.isdigit() and cmd in DEFAULT_DAYS and not supports_arg:
            days = DEFAULT_DAYS.get(cmd, 7)
            day_notice = (
                f"\n\n_(note: '{arg}' isn't a number — used default {days} days; "
                f"try `{cmd} {days}`.)_"
            )
        else:
            days = int(arg) if arg.isdigit() else DEFAULT_DAYS.get(cmd, 7)

        if not arg and cmd == "/prep-meeting":
            arg = "my next meeting"

        # Prefer the shared templates/commands.md source (same one cli.py's
        # subcommands use, with ~/.envoy/commands.md override support) when a
        # matching section exists, so TUI/REPL and `envoy <cmd>` never drift.
        # Fall back to the hardcoded one-liner above for commands with no
        # template section (e.g. /briefing, /reply, /search).
        prompt = None
        try:
            template_body = _load_commands().get(cmd[1:])
            if template_body:
                prompt = _build_prompt(template_body, **_template_kwargs(cmd, days, arg))
        except Exception:
            prompt = None
        if not prompt:
            prompt = entry[1].format(days=days, arg=arg)
        result = agent(prompt)
        if day_notice and isinstance(result, str):
            result = f"{result}{day_notice}"
        return (result, True)

    # --- System commands return None — caller handles ---
    if cmd in ("/help", "/status", "/settings", "/backup", "/exit"):
        return (cmd, False)  # signal to caller

    if cmd == "/mcp":
        from init_cmd import run_mcp
        return (run_mcp(arg), True)

    # --- Unknown slash command: don't burn LLM tokens on a typo ---
    if cmd.startswith("/"):
        return (f"Unknown command: {cmd}. Type /help to see available commands.", True)

    # --- Freeform natural language ---
    # For complex multi-domain requests, run planner first to gather data,
    # then feed context to the agent for synthesis.
    try:
        from agents.planner import needs_planning, plan_and_execute
        if needs_planning(stripped):
            context = plan_and_execute(stripped)
            if context:
                # Feed gathered context + original query to the agent
                augmented = f"""The user asked: "{stripped}"

I've already gathered the following data for you. Synthesize it into a response — do NOT re-fetch this data.

{context}"""
                return (agent(augmented), True)
    except Exception:
        pass  # Planner failed — fall through to direct agent call

    return (agent(stripped), True)


def _learn_async(raw: str, result: str):
    """Fire-and-forget learning in background thread. Never blocks dispatch."""
    global _last_response
    try:
        from agents.learning import reflect, detect_correction, apply_correction

        # 1. Correction detection — check if this input corrects the previous response
        correction = detect_correction(raw, _last_response)
        if correction:
            msg = apply_correction(correction)
            # We can't inject into the response retroactively, but it's saved.
            # The agent will mention it next turn via process.md injection.

        # 2. Reflect on what just happened (no AI, just file append)
        reflect(raw, result)

    except Exception:
        pass  # Never crash the app
    finally:
        _last_response = result if result else _last_response


def dispatch_with_learning(raw: str, agent):
    """Wrapper around dispatch() that adds the active learning loop.
    
    Use this instead of dispatch() directly for learning-enabled sessions.
    Same return signature: (result_or_cmd, handled).
    """
    # Start per-request budget tracking
    try:
        from agents.budget import start_request
        start_request()
    except Exception:
        pass

    result, handled = dispatch(raw, agent)

    # Fire learning in background (non-blocking) for meaningful interactions
    if handled and result and isinstance(result, str) and len(result) > 20:
        threading.Thread(target=_learn_async, args=(raw, result), daemon=True).start()

        # Surface any learned rules awaiting confirmation. Skip this for /learn
        # itself — its own output already shows the full pending list.
        if not raw.strip().lower().startswith("/learn"):
            try:
                from agents.learning import pending_summary
                summary = pending_summary()
                if summary:
                    result = f"{result}\n\n{summary}"
            except Exception:
                pass

    return result, handled


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
        _err(
            "AWS credentials invalid — refresh your AWS credentials (e.g. `mwinit` on "
            f"Amazon-internal setups, or your organization's AWS SSO login) or check .env ({e})"
        )

    # --- Models ---
    lines.append("\n## AI Models")
    try:
        from agents.base import _load_models, DEFAULT_MODELS
        from agents.paths import models_file as _models_file
        models = _load_models()
        models_file = _models_file()
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
    from agents.paths import config_dir as _config_dir
    config_dir = _config_dir()
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


def _handle_learn(arg: str) -> str:
    """Manage the learning pending-rules queue.

    /learn or /learn list       — show numbered rules awaiting confirmation
    /learn confirm <n>          — write rule <n> into process.md
    /learn reject <n>           — discard rule <n>
    """
    try:
        from agents import learning
    except Exception as e:
        return f"⚠️ Learning module unavailable: {e}"

    parts = arg.split() if arg else []
    sub = parts[0].lower() if parts else "list"

    if sub == "list":
        items = learning.list_pending()
        if not items:
            return "No pending learned rules."
        lines = ["**Pending learned rules**\n"]
        for i, item in enumerate(items, 1):
            section = item.get("section", "General")
            rule = item.get("rule", "")
            source = item.get("source", "")
            suffix = f"  _(via {source})_" if source else ""
            lines.append(f"  `{i}` [{section}] {rule}{suffix}")
        lines.append("\nUse `/learn confirm <n>` or `/learn reject <n>`.")
        return "\n".join(lines)

    if sub in ("confirm", "reject"):
        if len(parts) < 2 or not parts[1].isdigit():
            return f"Usage: /learn {sub} <n>  (see `/learn list` for numbers)"
        index = int(parts[1]) - 1  # user-facing numbering is 1-based
        fn = learning.confirm_pending if sub == "confirm" else learning.reject_pending
        return fn(index)

    return "Usage: `/learn` (list) · `/learn confirm <n>` · `/learn reject <n>`"


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
    lines.append("*Tip: run `/models <tier#|name> <model#|id>` again anytime to change a tier — "
                  "there's no separate pending-input mode, so plain text you type next goes to the agent as chat.*")
    return "\n".join(lines)
