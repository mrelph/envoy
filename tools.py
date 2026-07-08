"""Envoy Strands tools — supervisor tools that route to worker agents."""
import os
import re
from strands import tool
from envoy_logger import logged_tool, get_logger
from agents.base import outlook, builder, invoke_ai, check_mcp_connections, _load_models, MODEL_CATALOG, MODELS_FILE, get_token_usage, format_token_usage, reset_token_usage, run
from agents import email, slack_agent, calendar, todo, tickets, memory2 as memory, teamsnap_agent, people, internal, export

# --- Filesystem allow-list config ---

_CONFIG_FILE = os.path.expanduser("~/.envoy/config.json")


def _load_config() -> dict:
    """Load ~/.envoy/config.json."""
    if os.path.exists(_CONFIG_FILE):
        try:
            import json as _json
            return _json.loads(open(_CONFIG_FILE).read())
        except Exception:
            pass
    return {}


def _allowed_dirs() -> list:
    """Return the list of allowed filesystem directories from config."""
    return _load_config().get("allowed_dirs", [])


def _is_path_allowed(path: str, allowed: list = None) -> bool:
    """True if `path` is inside (or equal to) one of the allow-listed dirs.

    Uses os.path.commonpath rather than a plain string prefix match, so an
    allowed dir of "~/Documents" does NOT also match a sibling directory
    like "~/Documents-secret" (a `path.startswith(allowed_dir)` check would
    incorrectly allow that).
    """
    if allowed is None:
        allowed = _allowed_dirs()
    real_path = os.path.realpath(os.path.expanduser(path))
    for d in allowed:
        real_dir = os.path.realpath(os.path.expanduser(d))
        try:
            if os.path.commonpath([real_path, real_dir]) == real_dir:
                return True
        except ValueError:
            # e.g. paths on different drives on Windows — never allowed
            continue
    return False
from agents import workflows as wf
from agents.workers import get_worker
from agents.skills import get_skills, activate as activate_skill_fn
from agents import skill_builder

from agents.base import current_user as _USER  # call-time alias resolution


def _outlook_tool(tool_name: str, args: dict) -> str:
    """Direct MCP call to Outlook — used by worker agents."""
    async def _call():
        async with outlook() as session:
            result = await session.call_tool(tool_name, args)
            return result.content[0].text if result.content else "No result."
    return run(_call())


def _check_replies_combined() -> str:
    """Check for replies across email and Slack."""
    async def _check():
        results = []
        email_result = await email.check_replies()
        if email_result and "No sent" not in email_result:
            results.append(email_result)
        try:
            slack_result = await slack_agent.check_slack_replies()
            if slack_result:
                results.append(slack_result)
        except Exception:
            pass
        return "\n".join(results) if results else "Checked sent messages — no replies detected yet."
    try:
        return run(_check())
    except Exception:
        return "⚠️ Slack MCP unavailable — could only check email replies."


def _config_has_similar(path: str, new_rule: str, threshold: float = 0.6) -> str:
    """Check if a config file already has a similar rule. Returns the existing rule or ''."""
    if not os.path.exists(path):
        return ""
    new_words = set(new_rule.lower().split())
    if len(new_words) < 2:
        return ""
    for line in open(path):
        line = line.strip()
        if not line.startswith("- "):
            continue
        existing = line[2:].strip()
        existing_words = set(existing.lower().split())
        if not existing_words:
            continue
        overlap = len(new_words & existing_words) / max(len(new_words | existing_words), 1)
        if overlap >= threshold:
            return existing
    return ""


@tool
def update_soul(rule: str) -> str:
    """Add or update a rule in the agent's soul file (~/.envoy/soul.md).
    Use this when the user corrects behavior, asks you to change your tone/personality,
    or gives you behavioral directives. IMPORTANT: Always confirm with the user before calling this.

    Args:
        rule: The rule or personality directive to add (will be appended)
    """
    path = os.path.expanduser("~/.envoy/soul.md")
    existing = _config_has_similar(path, rule)
    if existing:
        return f"⚠️ Similar rule already exists: \"{existing}\"\nNo change made. Use `/settings` to edit manually."
    with open(path, "a") as f:
        f.write(f"\n- {rule}\n")
    return f"✅ Updated soul: {rule}\n⚠️ This change persists across sessions. Use `/settings` to review."


@tool
def update_envoy(preference: str) -> str:
    """Add or update a preference in the user's envoy config (~/.envoy/envoy.md).
    Use this for specific preferences: favorite Slack channels, email rules, key people,
    calendar preferences, EA info, etc. IMPORTANT: Always confirm with the user before calling this.

    Args:
        preference: The preference to add (will be appended)
    """
    path = os.path.expanduser("~/.envoy/envoy.md")
    existing = _config_has_similar(path, preference)
    if existing:
        return f"⚠️ Similar preference already exists: \"{existing}\"\nNo change made. Use `/settings` to edit manually."
    with open(path, "a") as f:
        f.write(f"\n- {preference}\n")
    return f"✅ Updated preferences: {preference}\n⚠️ This change persists across sessions. Use `/settings` to review."


@tool
def update_process(rule: str, section: str = "General") -> str:
    """Add a learned operational pattern to process memory (~/.envoy/process.md).
    Use this when the agent learns how to handle a recurring situation — email rules,
    meeting preferences, cleanup patterns, Slack behavior, calendar rules.
    IMPORTANT: Always confirm with the user before calling this.

    Args:
        rule: The process rule to add
        section: Section to file it under (Email, Meetings, Cleanup, Slack, Calendar, or any new section)
    """
    path = os.path.expanduser("~/.envoy/process.md")
    header = f"## {section}"
    existing = _config_has_similar(path, rule)
    if existing:
        return f"⚠️ Similar rule already exists: \"{existing}\"\nNo change made. Use `/settings` to edit manually."
    if not os.path.exists(path):
        # Bootstrap from template
        tmpl = os.path.join(os.path.dirname(__file__), "templates", "process.md")
        if os.path.exists(tmpl):
            import shutil
            shutil.copy(tmpl, path)
        else:
            with open(path, "w") as f:
                f.write(f"# Process Memory\n\n{header}\n- {rule}\n")
            return f"Created process memory: [{section}] {rule}"

    content = open(path).read()
    if header in content:
        content = content.replace(header, f"{header}\n- {rule}", 1)
    else:
        content = content.rstrip() + f"\n\n{header}\n- {rule}\n"
    with open(path, "w") as f:
        f.write(content)
    return f"Updated process memory: [{section}] {rule}"


@tool
def add_vip(alias: str) -> str:
    """Look up a person by alias in Phonetool and add them to High Priority People in envoy.md.
    Use this when the user mentions someone important — a key stakeholder, skip-level, customer contact,
    or anyone whose emails/Slack should always be flagged.

    Args:
        alias: The person's Amazon alias (login)
    """
    # Look up in Phonetool
    info = {"alias": alias, "email": f"{alias}@amazon.com", "name": "", "title": ""}
    try:
        async def _lookup():
            async with builder() as session:
                res = await session.call_tool("ReadInternalWebsites",
                    arguments={"inputs": [f"https://phonetool.amazon.com/users/{alias}"]})
                return str(res.content[0].text) if res.content else ""

        text = run(_lookup())
        for line in text.split("\n"):
            line = line.strip()
            if ("Job Title:" in line or "Business Title:" in line) and not info["title"]:
                info["title"] = line.split(":", 1)[1].strip()
            elif line and not info["name"] and not line.startswith(("#", "[", "!", "|", "-", "*")):
                candidate = line.split("|")[0].strip()
                if candidate and len(candidate.split()) <= 5 and candidate[0].isupper():
                    info["name"] = candidate
    except Exception:
        pass

    # Append to envoy.md under # High Priority People
    entry = f"- {info['name'] or alias} | {info['alias']} | {info['email']} | {info['title']}"
    path = os.path.expanduser("~/.envoy/envoy.md")
    content = open(path).read() if os.path.exists(path) else ""
    section = "# High Priority People"
    if section in content:
        # Check for duplicate
        if alias in content.split(section)[1].split("\n#")[0]:
            return f"{info['name'] or alias} ({alias}) is already in High Priority People."
        content = content.replace(section, f"{section}\n{entry}", 1)
    else:
        content = content.rstrip() + f"\n\n{section}\n{entry}\n"
    with open(path, "w") as f:
        f.write(content)

    label = f"{info['name']} ({alias})" if info["name"] else alias
    title_part = f" — {info['title']}" if info["title"] else ""
    return f"Added {label}{title_part} to High Priority People."

@tool
def teamsnap_schedule(team_id: str = "", start_date: str = "", end_date: str = "") -> str:
    """Get TeamSnap schedule/events. Lists teams if no team_id given.

    Args:
        team_id: TeamSnap team ID (empty = list all teams)
        start_date: Filter from date (ISO 8601, optional)
        end_date: Filter until date (ISO 8601, optional)
    """
    return run(teamsnap_agent.get_schedule(team_id, start_date, end_date))


@tool
def teamsnap_roster(team_id: str) -> str:
    """Get the roster (players and coaches) for a TeamSnap team.

    Args:
        team_id: TeamSnap team ID
    """
    return run(teamsnap_agent.get_roster(team_id))


@tool
def teamsnap_availability(event_id: str) -> str:
    """Get availability responses for a TeamSnap event.

    Args:
        event_id: TeamSnap event ID
    """
    return run(teamsnap_agent.get_availability(event_id))


@tool
def teamsnap_event_detail(event_id: str) -> str:
    """Get full details for a TeamSnap event — location, uniform, arrival time, notes.

    Args:
        event_id: TeamSnap event ID
    """
    return run(teamsnap_agent.get_event_detail(event_id))


@tool
def teamsnap_location(event_id: str) -> str:
    """Get location details for a TeamSnap event — address, map link, parking notes.

    Args:
        event_id: TeamSnap event ID
    """
    return run(teamsnap_agent.get_location(event_id))


@tool
def teamsnap_contacts(team_id: str = "", member_id: str = "") -> str:
    """Get parent/guardian contact info (phone, email) for a TeamSnap team or member.

    Args:
        team_id: TeamSnap team ID (all contacts on team)
        member_id: TeamSnap member ID (contacts for one player)
    """
    return run(teamsnap_agent.get_contacts(team_id, member_id))


@tool
def teamsnap_announcements(team_id: str) -> str:
    """Get recent team announcements and broadcasts from TeamSnap.

    Args:
        team_id: TeamSnap team ID
    """
    return run(teamsnap_agent.get_announcements(team_id))


@tool
def teamsnap_rsvp(event_id: str, member_id: str, status: str) -> str:
    """Set RSVP for a TeamSnap event. Status must be yes, no, or maybe.

    Args:
        event_id: TeamSnap event ID
        member_id: TeamSnap member ID
        status: RSVP status — yes, no, or maybe
    """
    return run(teamsnap_agent.set_availability(event_id, member_id, status))


@tool
def teamsnap_assignments(team_id: str = "", event_id: str = "") -> str:
    """Get volunteer/snack/carpool assignments for a TeamSnap team or event.

    Args:
        team_id: TeamSnap team ID (all assignments)
        event_id: TeamSnap event ID (assignments for one event)
    """
    return run(teamsnap_agent.get_assignments(team_id, event_id))


@tool
def teamsnap_standings(team_id: str) -> str:
    """Get win/loss record and division standings for a TeamSnap team.

    Args:
        team_id: TeamSnap team ID
    """
    return run(teamsnap_agent.get_standings(team_id))


@tool
def check_replies() -> str:
    """Check for replies to messages the agent previously sent via Slack or email.
    Scans sent message history and looks for responses in threads or email chains.
    Use this when the user asks "did anyone reply?" or "any responses?" or during briefings.
    """
    return _check_replies_combined()


@tool
def recommend_responses(days: int = 3) -> str:
    """Scan recent emails and Slack DMs sent directly to the user and generate recommended responses.
    Returns AI-drafted replies with urgency levels. Use when the user asks "what should I reply to?"
    or "any messages I need to respond to?" or "draft my replies".

    Args:
        days: Number of days to look back (default 3)
    """
    return wf.recommend_responses(_USER(), days)


@tool
def learn_response(context: str, response: str, medium: str = "email") -> str:
    """Save a response the user approved/sent so future recommendations match their style.
    Call this AFTER the user sends or approves a recommended response.

    Args:
        context: Brief description of what the message was about (sender + topic)
        response: The actual response text that was sent
        medium: "email" or "slack"
    """
    return wf.learn_response(context, response, medium)


@tool
def manage_cron(action: str = "list", name: str = "", schedule: str = "", command: str = "") -> str:
    """Manage Envoy scheduled jobs (cron).

    Args:
        action: 'list' to show all jobs, 'add' to create one, 'remove' to delete by name, 'presets' to show templates
        name: Job name (for add/remove). Used as a comment tag to identify the job.
        schedule: Cron expression (for add). e.g. '0 8 * * 1-5' for weekdays at 8am.
        command: Envoy command to run (for add). e.g. 'digest --days 7 --email'
    """
    import subprocess
    MARKER = "# envoy:"

    def _get_crontab():
        try:
            return subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        except Exception:
            return ""

    def _set_crontab(content):
        proc = subprocess.run(["crontab", "-"], input=content, capture_output=True, text=True)
        if proc.returncode != 0:
            return f"Error: {proc.stderr}"
        return None

    def _envoy_path():
        import shutil
        # Prefer installed binary on PATH (symlink survives repo moves)
        found = shutil.which("envoy")
        if found:
            return found
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "envoy"))
        return script if os.path.exists(script) else "envoy"

    if action == "presets":
        return """Available presets:
- **morning-briefing**: Weekdays 8am — Slack DM yourself a full briefing
  `0 8 * * 1-5  envoy digest --days 1 --slack --no-display`
- **weekly-digest**: Monday 8am — weekly team digest via Slack DM
  `0 8 * * 1  envoy digest --days 7 --slack --no-display`
- **customer-scan**: Weekdays 9am — daily customer email scan via Slack DM
  `0 9 * * 1-5  envoy customers --days 1 --slack`
- **inbox-cleanup**: Friday 4pm — weekly cleanup suggestions
  `0 16 * * 5  envoy cleanup --days 7`

Add `--email` instead of `--slack` if you prefer email delivery.
Tell me which preset to add, or describe a custom schedule."""

    if action == "list":
        crontab = _get_crontab()
        jobs = [l for l in crontab.splitlines() if MARKER in l]
        if not jobs:
            return "No Envoy cron jobs found. Use action='presets' to see templates, or action='add' to create one."
        lines = []
        for job in jobs:
            tag = job.split(MARKER)[1].strip()
            cron_part = job.split(MARKER)[0].strip()
            lines.append(f"- **{tag}**: `{cron_part}`")
        return f"Envoy scheduled jobs:\n" + "\n".join(lines)

    if action == "add":
        if not name or not schedule or not command:
            return "Need name, schedule, and command. Example: action='add', name='weekly-digest', schedule='0 8 * * 1', command='digest --days 7 --email --no-display'"
        # Security: validate command is a safe envoy subcommand
        _ALLOWED_SUBCMDS = {"digest", "cleanup", "customers", "catchup", "slack-catchup", "yesterbox",
                            "cal-audit", "response-times", "followup", "commitments", "prep-1on1", "prep-meeting",
                            "heartbeat"}
        _DANGEROUS_CHARS = set(";|&`$(){}!><\n")
        tokens = command.strip().split()
        if not tokens:
            return "Rejected: empty command."
        # Allow optional leading 'envoy' for users who copy from presets
        if tokens[0] == "envoy":
            tokens = tokens[1:]
            command = " ".join(tokens)
        first_word = tokens[0] if tokens else ""
        if first_word not in _ALLOWED_SUBCMDS:
            return f"Rejected: '{first_word}' is not a known envoy subcommand. Allowed: {', '.join(sorted(_ALLOWED_SUBCMDS))}"
        if any(c in command for c in _DANGEROUS_CHARS):
            return "Rejected: command contains unsafe shell characters."
        if any(c in schedule for c in _DANGEROUS_CHARS):
            return "Rejected: schedule contains unsafe shell characters."
        # Cron schedule: 5 whitespace-separated fields of [0-9,*/-]
        if not re.fullmatch(r"[\d,*/\-\s]+", schedule) or len(schedule.split()) != 5:
            return "Rejected: schedule must be 5 fields of numbers/*/-/, (e.g. '0 8 * * 1-5')."
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
            return "Rejected: name may only contain letters, digits, '_' and '-'."
        import shlex
        exe = shlex.quote(_envoy_path())
        full_cmd = f"{schedule}  {exe} {command}  {MARKER} {name}"
        crontab = _get_crontab()
        # Remove existing job with same name
        lines = [l for l in crontab.splitlines() if f"{MARKER} {name}" not in l]
        lines.append(full_cmd)
        err = _set_crontab("\n".join(lines) + "\n")
        return err or f"✓ Added cron job '{name}': `{schedule}` → `envoy {command}`"

    if action == "remove":
        if not name:
            return "Need name of job to remove. Use action='list' to see current jobs."
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", name):
            return "Rejected: name may only contain letters, digits, '_' and '-'."
        crontab = _get_crontab()
        lines = crontab.splitlines()
        filtered = [l for l in lines if f"{MARKER} {name}" not in l]
        if len(filtered) == len(lines):
            return f"No job named '{name}' found."
        err = _set_crontab("\n".join(filtered) + "\n")
        return err or f"✓ Removed cron job '{name}'"

    return "Unknown action. Use 'list', 'add', 'remove', or 'presets'."


@tool
def pto_catchup(days: int = 5) -> str:
    """Comprehensive catch-up report after being out of office.
    Combines team digest, boss tracker, Slack, customer emails, and to-dos into one report.
    Use when the user says "I was out", "catch me up", "what did I miss?", or "PTO catch-up".

    Args:
        days: Number of days you were out (default 5)
    """
    return wf.pto_catchup(_USER(), days)


@tool
def slack_catchup(days: int = 3) -> str:
    """Focused Slack catch-up — unread channels, @mentions, and unanswered DMs.
    Use when the user says "catch me up on Slack", "what did I miss on Slack?", or "unread Slack".

    Args:
        days: Number of days to look back (default 3)
    """
    return wf.slack_catchup(_USER(), days)


@tool
def yesterbox(days: int = 1) -> str:
    """Yesterbox — focused queue of yesterday's direct messages (TO-line emails + Slack DMs),
    prioritized with action items extracted.
    Use when the user says "yesterbox", "yesterday's messages", or "what came in yesterday?".

    Args:
        days: Number of days to look back (default: 1 for yesterday)
    """
    alias = _USER()
    return wf.yesterbox(alias, days)


@tool
def calendar_audit(days: int = 5) -> str:
    """Audit your calendar — meeting load, focus time, back-to-backs, and decline suggestions.
    Use when the user says "audit my calendar", "too many meetings", or "optimize my week".

    Args:
        days: Number of days ahead to analyze (default 5)
    """
    return wf.calendar_audit(_USER(), days)


@tool
def response_time_tracker(days: int = 7) -> str:
    """Analyze email response patterns — how fast you reply and how fast others reply to you.
    Use when the user asks "how's my response time?", "who haven't I replied to?", or "email patterns".

    Args:
        days: Number of days to analyze (default 7)
    """
    return wf.response_time_tracker(_USER(), days)


@tool
def follow_up_tracker(days: int = 7) -> str:
    """Scan your sent emails for unanswered threads — things you sent that never got a reply.
    Surfaces them ranked by urgency with suggested follow-up actions.
    Use when the user asks "what's pending?", "any unanswered emails?", or "what fell through the cracks?".

    Args:
        days: Number of days to look back (default 7)
    """
    return wf.follow_up_tracker(_USER(), days)


@tool
def one_on_one_prep(person_alias: str) -> str:
    """Generate a 1:1 prep brief for a meeting with a specific person.
    Pulls their Phonetool profile, recent email threads between you, shared to-do items,
    and upcoming shared meetings. Suggests talking points.
    Use when the user says "prep for my 1:1 with [person]" or "what should I discuss with [person]?".

    Args:
        person_alias: Amazon login/alias of the person you're meeting with
    """
    return wf.one_on_one_prep(person_alias, _USER())


@tool
def commitment_tracker(days: int = 7) -> str:
    """Scan your sent emails and Slack messages for commitments and promises you made to others.
    Identifies things like "I'll send that by Friday", "let me follow up", "action on me".
    Use when the user asks "what did I promise?", "any open commitments?", or "what do I owe people?".

    Args:
        days: Number of days to look back (default 7)
    """
    return wf.commitment_tracker(_USER(), days)


@tool
def meeting_prep(meeting_subject: str = "") -> str:
    """Generate a prep brief for an upcoming meeting. Looks up attendees on Phonetool,
    finds related email threads, and suggests talking points.
    If no subject given, preps for the next upcoming meeting.
    Use when the user says "prep me for [meeting]" or "what's my next meeting about?".

    Args:
        meeting_subject: Meeting title to search for (empty = next upcoming meeting)
    """
    return wf.meeting_prep(meeting_subject, _USER())


# --- Utility tools ---

@tool
def current_time() -> str:
    """Get the current date, time, and timezone. Use this whenever you need to know the current time,
    especially for calendar operations, scheduling, or when the user asks about time."""
    from datetime import datetime, timezone, timedelta
    import time as _time
    is_dst = _time.localtime().tm_isdst > 0
    utc_offset = timedelta(seconds=-_time.altzone if is_dst else -_time.timezone)
    now = datetime.now(timezone(utc_offset))
    tz_name = _time.tzname[1] if is_dst else _time.tzname[0]
    return now.strftime(f'%A, %B %d %Y at %I:%M %p {tz_name} (UTC%z)')


# --- Internal websites tools ---

@tool
def token_usage() -> str:
    """Show AI token usage for the current session — total input/output tokens and per-tier breakdown."""
    return format_token_usage()


# --- Skill-gated tools (available for activation, not in ALL_TOOLS by default) ---

_SKILL_TOOLS = {
    "teamsnap_schedule": teamsnap_schedule,
    "teamsnap_roster": teamsnap_roster,
    "teamsnap_availability": teamsnap_availability,
    "teamsnap_event_detail": teamsnap_event_detail,
    "teamsnap_location": teamsnap_location,
    "teamsnap_contacts": teamsnap_contacts,
    "teamsnap_announcements": teamsnap_announcements,
    "teamsnap_rsvp": teamsnap_rsvp,
    "teamsnap_assignments": teamsnap_assignments,
    "teamsnap_standings": teamsnap_standings,
}

_active_agent = None  # set by agent.py after creation


def set_active_agent(agent):
    """Called by agent.py to allow skill activation to inject tools at runtime."""
    global _active_agent
    _active_agent = agent


def _skill_tool_registry() -> dict:
    """Name -> raw tool callable for every tool Envoy knows about.

    Combines the skill-gated extras in _SKILL_TOOLS (not registered on the
    agent by default — originally just the TeamSnap set) with every tool in
    _ALL_TOOLS_RAW (registered by default). Built data-driven off the actual
    tool list rather than a hardcoded per-skill mapping, so a skill-builder
    skill's `allowed-tools` can reference *any* real tool — not just the
    original 10 TeamSnap ones — instead of silently no-op'ing.
    """
    registry = dict(_SKILL_TOOLS)
    for fn in _ALL_TOOLS_RAW:
        name = getattr(fn, "__name__", None)
        if name:
            registry[name] = fn
    return registry


def _inject_skill_tools(skill_name: str, allowed_tools: str):
    """Inject a skill's allowed-tools into the running agent's tool registry.

    Unknown tool names (typos, or a skill referencing a tool that doesn't
    exist) are logged at DEBUG and skipped rather than silently no-op'd with
    no trace.
    """
    if not _active_agent or not allowed_tools:
        return
    registry = _skill_tool_registry()
    for name in allowed_tools.split():
        tool_fn = registry.get(name)
        if not tool_fn:
            try:
                get_logger().log_debug(f"Skill '{skill_name}' requested unknown tool '{name}' — skipping",
                                        skill=skill_name, tool_name=name)
            except Exception:
                pass
            continue
        # Skip if already registered
        try:
            existing = _active_agent.tool_registry.registry
            dynamic = _active_agent.tool_registry.dynamic_tools
            if name in existing or name in dynamic:
                continue
        except AttributeError:
            continue
        try:
            _active_agent.tool_registry.process_tools([logged_tool(tool_fn)])
        except Exception:
            pass


@tool
def activate_skill(name: str) -> str:
    """Activate an Agent Skill by name to load its full instructions.
    Use when a task matches a skill's description from the available_skills catalog.

    Args:
        name: Skill name from the catalog
    """
    skills = get_skills()
    skill = skills.get(name)
    if skill and skill.get("allowed_tools"):
        _inject_skill_tools(name, skill["allowed_tools"])
    return activate_skill_fn(name, skills)


@tool
def build_skill(description: str, slug: str = "", tools: str = "") -> str:
    """Build a new Agent Skill from a natural language description and save it.
    The skill will be generated as a SKILL.md and installed to ~/.envoy/skills/.
    IMPORTANT: Show the user the generated skill and confirm before saving.

    Args:
        description: What the skill should do (natural language)
        slug: Optional short name (auto-generated if blank)
        tools: Optional comma-separated worker tools the skill needs (default: email_worker, comms_worker)
    """
    content, slug = skill_builder.generate_skill(description, slug, tools)
    path = skill_builder.save_skill(content, slug)
    return f"✅ Skill created: **{slug}**\nSaved to: `{path}`\n\nActivate with: `/activate {slug}` or it will auto-activate when relevant.\n\n<details>\n{content}\n</details>"


@tool
def suggest_skills(days: int = 14) -> str:
    """Analyze recent activity and memory to suggest new skills that could automate recurring patterns.

    Args:
        days: How many days of history to analyze (default 14)
    """
    return skill_builder.suggest_skills(days)


@tool
def observe_interaction(interaction_summary: str, outcome: str, domain: str = "") -> str:
    """Log an interaction observation — what happened and what the user preferred.

    Args:
        interaction_summary: What happened (e.g. "User deleted all vendor newsletters")
        outcome: What the user preferred (e.g. "Prefers aggressive cleanup of marketing emails")
        domain: Category — Email, Meetings, Cleanup, Slack, Calendar, or blank
    """
    text = f"{interaction_summary} → {outcome}"
    return memory.remember(text, entry_type="observation")


@tool
def analyze_patterns(days: int = 7) -> str:
    """Analyze recent memory entries to identify recurring user patterns and suggest process rules.

    Args:
        days: How many days back to analyze (default 7)
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
    """Get a summary of what the observer has learned — recent observations and patterns."""
    entries = memory._load_entries(days=7)
    observations = [e for e in entries if e.get("type") == "observation"]
    if not observations:
        return "No observations recorded yet."
    domains = {}
    for e in observations:
        for ent in e.get("entities", []):
            domains[ent] = domains.get(ent, 0) + 1
    domain_summary = ", ".join(f"{k}: {v}" for k, v in sorted(domains.items(), key=lambda x: -x[1])[:10])
    recent = "\n".join(
        f"- {e['ts'][:16]} {e['text'][:100]}" for e in observations[-20:]
    )
    return f"## Observer Insights\n\n**{len(observations)} observations** (last 7 days): {domain_summary}\n\n### Recent\n{recent}"


@tool
def recall_memory(query: str = "", limit: int = 20) -> str:
    """Recall memory by topic, person, or project. Empty query returns recent entries + summary.

    Args:
        query: Entity name, person, project, or topic to search for (empty = general recall)
        limit: Max entries to return
    """
    return memory.recall(query, limit)


@tool
def manage_memory_vaults(action: str, path: str = "") -> str:
    """Manage external memory vaults (Obsidian vaults, note directories).

    Args:
        action: "list", "add", or "remove"
        path: Directory path (required for add/remove). Supports ~ for home.
    """
    if action == "list":
        paths = memory.list_vault_paths()
        if not paths:
            return "No external vaults configured. Use add with a path to an Obsidian vault or notes directory."
        return "Configured vaults:\n" + "\n".join(f"  • {p}" for p in paths)
    elif action == "add":
        if not path:
            return "Please provide a path to add."
        return memory.add_vault_path(path)
    elif action == "remove":
        if not path:
            return "Please provide a path to remove."
        return memory.remove_vault_path(path)
    return "Unknown action. Use: list, add, remove"


# ============================================================
# Worker agent routing — supervisor delegates to specialists
# ============================================================

def _worker_credentials_expired(e: Exception) -> bool:
    """True if `e` is the same AWS credential-expiry error invoke_ai retries on.

    Reuses agents.base's classifier rather than duplicating its error-code
    list here.
    """
    try:
        from agents.base import _is_expired_credentials_error
        return _is_expired_credentials_error(e)
    except Exception:
        return False


def _refresh_worker_credentials() -> None:
    """Mirror invoke_ai's one-shot credential refresh (agents/base.py
    `invoke_ai`) for the Strands worker path: reload .env, then drop the
    cached Bedrock client so the next call picks up fresh credentials.

    Doesn't edit agents/base.py — it just pokes the same module-level globals
    invoke_ai's own retry does, from the outside.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.expanduser("~/.envoy/.env"), override=True)
        load_dotenv(override=True)
    except Exception:
        pass
    try:
        import agents.base as _base
        _base._bedrock_client = None
    except Exception:
        pass


def _record_worker_token_usage(worker_name: str, result) -> None:
    """Fold a Strands worker call's token usage into the same session-wide
    tracker invoke_ai populates (agents.base._token_usage).

    _token_usage previously only saw invoke_ai calls, so /token_usage
    under-reported the dominant Strands spend (H6 in
    PROJECT-REVIEW-2026-07-06.md). There's no public recorder function on the
    Strands path in agents.base to call into, so — per that item — we update
    the shared dict directly, in the same {'input','output','calls','by_tier'}
    shape `_invoke_ai_once` uses (agents/base.py:881-892). Best-effort: the
    exact metrics attribute shape is an implementation detail of the strands
    package (EventLoopMetrics.accumulated_usage with inputTokens/
    outputTokens), and conftest's stubbed strands has no real metrics at all,
    so any shape drift must never break a worker call.
    """
    try:
        metrics = getattr(result, "metrics", None)
        usage = getattr(metrics, "accumulated_usage", None)
        if not usage:
            return
        in_tok = int(usage.get("inputTokens", 0) or 0)
        out_tok = int(usage.get("outputTokens", 0) or 0)
        if not in_tok and not out_tok:
            return
        from agents.base import _token_usage
        _token_usage['input'] += in_tok
        _token_usage['output'] += out_tok
        _token_usage['calls'] += 1
        tier_entry = _token_usage['by_tier'].setdefault(f"worker:{worker_name}",
                                                          {'input': 0, 'output': 0, 'calls': 0})
        tier_entry['input'] += in_tok
        tier_entry['output'] += out_tok
        tier_entry['calls'] += 1
    except Exception:
        pass


def _delegate(worker_name: str, request: str, _retries: int = 1) -> str:
    """Route to a worker agent with retry and graceful degradation."""
    from agents.workers import reset_worker_session
    import sys
    last_err = None
    for attempt in range(_retries + 1):
        try:
            result = get_worker(worker_name)(request)
            response = str(result.message) if hasattr(result, 'message') else str(result)
            _record_worker_token_usage(worker_name, result)

            # Empty-prompt artifact: the worker model received no user message
            # (session corruption — usually a stale toolUse with no toolResult)
            # and politely asks "what would you like help with?". Treat as a
            # silent failure: reset and retry the request once.
            if attempt < _retries and _looks_like_empty_prompt(response):
                print(f"[{worker_name}] empty-prompt artifact detected — resetting session", file=sys.stderr)
                reset_worker_session(worker_name)
                continue

            try:
                memory.remember(f"[{worker_name}] {request[:200]} → {response[:200]}", entry_type="observation")
            except Exception:
                pass
            return response
        except Exception as e:
            last_err = e
            print(f"[{worker_name}] attempt {attempt+1} failed: {e}", file=sys.stderr)
            if attempt < _retries:
                # Clear corrupted session if Bedrock rejects the message history
                err_msg = str(e)
                if "ValidationException" in err_msg and "toolResult" in err_msg:
                    reset_worker_session(worker_name)
                elif _worker_credentials_expired(e):
                    # Same refresh invoke_ai's retry path does, plus drop the
                    # cached worker instance/session so the next call builds a
                    # fresh BedrockModel — keeps hour-plus sessions alive past
                    # STS token expiry on the Strands path too.
                    print(f"[{worker_name}] credentials expired — refreshing and retrying", file=sys.stderr)
                    _refresh_worker_credentials()
                    reset_worker_session(worker_name)
    return f"⚠️ {worker_name} worker unavailable: {last_err}. Other sources may still have the information you need."


_EMPTY_PROMPT_HINTS = (
    "<<HUMAN_CONVERSATION_START>>",
    "started a message but it came through empty",
    "nothing followed",
    "appears to be empty",
)


def _looks_like_empty_prompt(response: str) -> bool:
    """Detect the worker artifact emitted when its user message arrives empty.

    Scoped to short responses (<300 chars, down from 4000) — legitimate
    substantive answers (e.g. "Your inbox is empty, nothing to triage") can
    contain these boilerplate phrases too; short length is what makes it an
    empty-prompt artifact rather than actual content.
    """
    if not response or len(response) > 300:
        return False
    low = response.lower()
    return any(h.lower() in low for h in _EMPTY_PROMPT_HINTS)


@tool
def email_worker(request: str) -> str:
    """Delegate email tasks to the Email specialist: inbox scan, search, send, reply, draft,
    cleanup, customer scan, team digest, boss tracker. Use for ANY email-related request.

    Args:
        request: Natural language description of what to do with email
    """
    return _delegate("email", request)


@tool
def comms_worker(request: str) -> str:
    """Delegate Slack and communication tasks: scan channels, send DMs, search messages,
    mark as read, delegate to EA. Use for ANY Slack or messaging request.

    Args:
        request: Natural language description of the communication task
    """
    return _delegate("comms", request)


@tool
def calendar_worker(request: str) -> str:
    """Delegate calendar tasks: view schedule, create meetings, find available times,
    book rooms via meetings.amazon.com. Use for ANY calendar or scheduling request.

    Args:
        request: Natural language description of the calendar task
    """
    return _delegate("calendar", request)


@tool
def productivity_worker(request: str) -> str:
    """Delegate productivity tasks: to-do list, tickets, memory, cron jobs, briefings
    (morning/eod/weekly). Use for task management, ticket scanning, or briefing requests.

    Args:
        request: Natural language description of the productivity task
    """
    return _delegate("productivity", request)


@tool
def research_worker(request: str) -> str:
    """Delegate research and lookup tasks: Phonetool profiles, Kingpin goals/projects/milestones
    (view, list, filter by owner/team/year/status, update status, add comments, list teams),
    Wiki pages, Taskei tasks, Broadcast videos, tiny links, web search,
    InstructAI business queries (21 specialized agents: revenue, pipeline, partner goals/attach/PAR,
    marketplace GSS/renewals/private offers, funding, migrations, SIFT, PSA/APOTech, pipeline risk),
    QuickSight dashboards and data topics (query data, list topics, GenAI trends, attach rates).
    Use for ANY internal lookup, external web search, business data query, or dashboard request.

    Args:
        request: Natural language description of what to look up
    """
    return _delegate("research", request)


@tool
def sharepoint_worker(request: str) -> str:
    """Delegate SharePoint/OneDrive tasks: search content, browse files, read documents,
    upload files, manage lists. Use for ANY SharePoint or OneDrive request.

    Args:
        request: Natural language description of the SharePoint task
    """
    return _delegate("sharepoint", request)


@tool
def coding_worker(task: str, working_directory: str = "", allow_edits: bool = False) -> str:
    """Run an autonomous coding agent (Claude Code or Kiro) to completion on a task.
    The agent can read files and, only if explicitly permitted, write files and run commands,
    iterating until done. Use for: writing code, fixing bugs, refactoring, creating scripts,
    code review, generating config files, or any software development task.

    Calls straight through to the coding CLI subprocess — there is no intermediate agent
    to fill in gaps, so pass a complete, self-contained task description (what to change,
    expected behavior/edge cases, and any language/framework/style constraints).

    Runs in read-only/plan mode by default. Edits, file writes, and shell commands require
    explicit allow_edits=True — only set that when the user has clearly asked for changes
    to be made, not just analyzed.

    Args:
        task: Detailed, self-contained description of the coding task to accomplish
        working_directory: Directory to work in (default: current directory). Must be
            under an allow-listed directory (see local_files' allowed_dirs config).
        allow_edits: Whether the agent may edit files / run commands (default: False —
            read-only plan mode). Requires explicit allow_edits=True to permit edits.
    """
    from agents.workers.coding_worker import run_coding_agent
    return run_coding_agent(task, working_directory=working_directory, allow_edits=allow_edits)


# --- Export tools (stay on supervisor — they take content from other tools) ---

@tool
def export_word(content: str, filename: str = "") -> str:
    """Export any report or content to a Word document (.docx). Saves locally and uploads to configured Exports Folder on OneDrive if set.

    Args:
        content: Markdown content to convert
        filename: Output filename (default: auto-generated)
    """
    path = export.to_docx(content, filename)
    result = f"✅ Word document saved: {path}"
    folders = export._configured_folders()
    if folders["exports"]:
        try:
            from agents.sharepoint_agent import upload_to_folder
            run(upload_to_folder(path, folders["exports"]))
            result += f"\n📁 Uploaded to OneDrive: {folders['exports']}/{os.path.basename(path)}"
        except Exception as e:
            result += f"\n⚠️ OneDrive upload failed: {e}"
    return result


@tool
def export_pptx(content: str, filename: str = "", title: str = "Envoy Report") -> str:
    """Export any report to a PowerPoint deck (.pptx). Each ## section becomes a slide. Saves locally and uploads to configured Exports Folder on OneDrive if set.

    Args:
        content: Markdown content to convert
        filename: Output filename (default: auto-generated)
        title: Title for the cover slide
    """
    path = export.to_pptx(content, filename, title)
    result = f"✅ PowerPoint saved: {path}"
    folders = export._configured_folders()
    if folders["exports"]:
        try:
            from agents.sharepoint_agent import upload_to_folder
            run(upload_to_folder(path, folders["exports"]))
            result += f"\n📁 Uploaded to OneDrive: {folders['exports']}/{os.path.basename(path)}"
        except Exception as e:
            result += f"\n⚠️ OneDrive upload failed: {e}"
    return result


@tool
def local_files(action: str, path: str = "", content: str = "") -> str:
    """Read, write, list, or tree local files. Restricted to allow-listed directories
    configured in ~/.envoy/config.json under "allowed_dirs".
    Use when the user asks to read a local file, save notes, or browse a directory.

    Args:
        action: 'read', 'write', 'list', or 'tree'
        path: File or directory path (absolute or ~ relative)
        content: Content to write (for 'write' action only)
    """
    allowed = _allowed_dirs()
    if not allowed:
        return ("⚠️ No directories allowed. Add allowed_dirs to ~/.envoy/config.json:\n"
                '{"allowed_dirs": ["~/Documents", "~/Projects"]}')

    path = os.path.expanduser(path)
    path = os.path.realpath(path)

    # Enforce allow-list (commonpath equality, not a prefix/startswith match —
    # startswith would let "/x/Documents-secret" through when "/x/Documents"
    # is the allowed dir).
    if not _is_path_allowed(path, allowed):
        return f"⚠️ Access denied. Path not in allowed_dirs: {allowed}"

    if action == "list":
        if not os.path.isdir(path):
            return f"Not a directory: {path}"
        entries = sorted(os.listdir(path))
        dirs = [e + "/" for e in entries if os.path.isdir(os.path.join(path, e))]
        files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
        return "\n".join(dirs + files) or "(empty)"

    elif action == "tree":
        if not os.path.isdir(path):
            return f"Not a directory: {path}"
        lines = []
        for root, dirs_list, files_list in os.walk(path):
            depth = root.replace(path, "").count(os.sep)
            if depth > 3:
                dirs_list.clear()
                continue
            indent = "  " * depth
            lines.append(f"{indent}{os.path.basename(root)}/")
            for f in sorted(files_list)[:20]:
                lines.append(f"{indent}  {f}")
        return "\n".join(lines[:200]) or "(empty)"

    elif action == "read":
        if not os.path.isfile(path):
            return f"Not a file: {path}"
        if os.path.getsize(path) > 500_000:
            return f"File too large ({os.path.getsize(path)} bytes). Max 500KB."
        return open(path).read()

    elif action == "write":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        return f"✅ Written {len(content)} bytes to {path}"

    return f"Unknown action: {action}. Use read, write, list, or tree."


_ALL_TOOLS_RAW = [
    # --- Worker agent routing (5 tools → replaces ~40 direct tools) ---
    email_worker,
    comms_worker,
    calendar_worker,
    productivity_worker,
    research_worker,
    sharepoint_worker,
    coding_worker,
    # --- Compound workflows (stay on supervisor for cross-domain orchestration) ---
    pto_catchup,
    slack_catchup,
    yesterbox,
    calendar_audit,
    response_time_tracker,
    follow_up_tracker,
    one_on_one_prep,
    commitment_tracker,
    meeting_prep,
    check_replies,
    recommend_responses,
    learn_response,
    # --- Config tools (supervisor-only) ---
    update_soul,
    update_envoy,
    update_process,
    add_vip,
    # --- Export ---
    export_word,
    export_pptx,
    # --- Memory & Observer ---
    recall_memory,
    manage_memory_vaults,
    observe_interaction,
    analyze_patterns,
    get_observer_insights,
    # --- Meta ---
    current_time,
    token_usage,
    activate_skill,
    build_skill,
    suggest_skills,
    # --- Filesystem ---
    local_files,
]

# Add supervisor tools (gather, read_email_thread, lookup_person, search_emails, show_context)
try:
    from supervisor import SUPERVISOR_TOOLS
    _ALL_TOOLS_RAW.extend(SUPERVISOR_TOOLS)
except ImportError:
    pass

ALL_TOOLS = [logged_tool(t) for t in _ALL_TOOLS_RAW]
