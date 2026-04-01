"""Envoy Strands tools — supervisor tools that route to worker agents."""
import asyncio
import os
import re
import hashlib
import functools
from strands import tool
from envoy_logger import logged_tool
from agents.base import outlook, builder, invoke_ai, BUILDER_PARAMS, check_mcp_connections, _load_models, MODEL_CATALOG, MODELS_FILE, mcp_batch, get_token_usage, format_token_usage, reset_token_usage
from agents import email, slack_agent, calendar, todo, tickets, memory2 as memory, teamsnap_agent, people, internal, export
from agents import workflows as wf
from agents.workers import get_worker
from agents.skills import get_skills, activate as activate_skill_fn

_USER = os.environ.get('USER', '')


def _outlook_tool(tool_name: str, args: dict) -> str:
    """Direct MCP call to Outlook — used by worker agents."""
    async def _call():
        async with outlook() as session:
            result = await session.call_tool(tool_name, args)
            return result.content[0].text if result.content else "No result."
    return asyncio.run(_call())


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
        return asyncio.run(_check())
    except Exception:
        return "⚠️ Slack MCP unavailable — could only check email replies."


def _run(coro):
    """Run an async coroutine — shared helper to replace scattered asyncio.run() calls."""
    return asyncio.run(coro)


async def _outlook_batch(calls: list) -> list:
    """Run multiple Outlook MCP calls in a single session."""
    return await mcp_batch("Outlook", calls)


# --- Demo mode masking ---

_DEMO_MODE = os.environ.get("ENVOY_DEMO", "").strip().lower() in ("1", "true", "yes")

_FAKE_FIRST = [
    "Alex", "Jordan", "Morgan", "Casey", "Riley", "Quinn", "Avery", "Taylor",
    "Skyler", "Dakota", "Reese", "Finley", "Rowan", "Sage", "Blair", "Drew",
    "Emery", "Harper", "Kendall", "Logan", "Parker", "Peyton", "Sawyer", "Tatum",
]
_FAKE_LAST = [
    "Chen", "Patel", "Kim", "Santos", "Müller", "Nakamura", "Okafor", "Johansson",
    "Rivera", "Kowalski", "Tanaka", "Gupta", "Larsson", "Moreau", "Novak", "Reyes",
    "Fischer", "Sharma", "Dubois", "Yamamoto", "Costa", "Petrov", "Andersen", "Ortiz",
]
_FAKE_DOMAINS = [
    "acmecorp.com", "globex.io", "initech.co", "umbrella.net", "waynetech.org",
    "starkindustries.com", "oscorp.io", "lexcorp.net", "cyberdyne.co", "soylent.org",
]

def _demo_hash(text: str) -> int:
    """Deterministic hash so same input always maps to same fake output."""
    return int(hashlib.md5(text.lower().encode()).hexdigest(), 16)

def _fake_name(real: str) -> str:
    h = _demo_hash(real)
    return f"{_FAKE_FIRST[h % len(_FAKE_FIRST)]} {_FAKE_LAST[(h >> 8) % len(_FAKE_LAST)]}"

def _fake_alias(real: str) -> str:
    name = _fake_name(real)
    return name.split()[0].lower() + name.split()[1].lower()[:3]

def _fake_email(real: str) -> str:
    local = real.split("@")[0] if "@" in real else real
    h = _demo_hash(local)
    alias = _fake_alias(local)
    domain = _FAKE_DOMAINS[h % len(_FAKE_DOMAINS)]
    return f"{alias}@{domain}"

def _mask_output(text: str) -> str:
    """Replace real PII patterns with deterministic fakes."""
    if not text:
        return text

    # Cache replacements for consistency
    seen = {}

    def _replace_email(m):
        orig = m.group(0)
        if orig not in seen:
            seen[orig] = _fake_email(orig)
        return seen[orig]

    def _replace_alias_ref(m):
        """Replace @alias patterns."""
        orig = m.group(1)
        if orig not in seen:
            seen[orig] = _fake_alias(orig)
        return f"@{seen[orig]}"

    # Emails: user@amazon.com, user@domain.com
    text = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', _replace_email, text)

    # @alias mentions (Slack-style)
    text = re.sub(r'@([a-z]{2,12})\b', _replace_alias_ref, text)

    # Slack channel IDs (C/D/G followed by alphanumeric)
    text = re.sub(r'\b([CDG][A-Z0-9]{8,12})\b',
                  lambda m: f"C{''.join(format(_demo_hash(m.group(1)) >> i & 0xF, 'X') for i in range(10))}",
                  text)

    # Conversation IDs (long base64-ish strings that look like email thread IDs)
    text = re.sub(r'(AAQ[A-Za-z0-9+/=]{20,})',
                  lambda m: f"AAQkDemo{''.join(format(_demo_hash(m.group(1)) >> i & 0xF, 'X') for i in range(16))}==",
                  text)

    # Phone numbers
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '555-867-5309', text)

    # Building codes (SEA54, PDX12, etc.)
    text = re.sub(r'\b([A-Z]{3})\d{1,3}(?:-\d{2}\.\d{3})?\b',
                  lambda m: f"HQ{_demo_hash(m.group(0)) % 99:02d}", text)

    return text

def _demo_wrap(t):
    """If demo mode is on, wrap the tool's inner function to mask output."""
    if not _DEMO_MODE:
        return t
    orig_func = t._tool_func
    @functools.wraps(orig_func)
    def masked(*args, **kwargs):
        result = orig_func(*args, **kwargs)
        return _mask_output(str(result)) if isinstance(result, str) else result
    t._tool_func = masked
    return t


@tool
def update_soul(rule: str) -> str:
    """Add or update a rule in the agent's soul file (~/.envoy/soul.md).
    Use this when the user corrects behavior, asks you to change your tone/personality,
    or gives you behavioral directives. IMPORTANT: Always confirm with the user before calling this.

    Args:
        rule: The rule or personality directive to add (will be appended)
    """
    path = os.path.expanduser("~/.envoy/soul.md")
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

        text = _run(_lookup())
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
def teamsnap_auth() -> str:
    """Authenticate with TeamSnap via AWS-hosted OAuth.
    Call this before using any other TeamSnap tools if not yet authenticated.
    """
    return _run(teamsnap_agent.auth())


@tool
def teamsnap_schedule(team_id: str = "", start_date: str = "", end_date: str = "") -> str:
    """Get TeamSnap schedule/events. Lists teams if no team_id given.

    Args:
        team_id: TeamSnap team ID (empty = list all teams)
        start_date: Filter from date (ISO 8601, optional)
        end_date: Filter until date (ISO 8601, optional)
    """
    return _run(teamsnap_agent.get_schedule(team_id, start_date, end_date))


@tool
def teamsnap_roster(team_id: str) -> str:
    """Get the roster (players and coaches) for a TeamSnap team.

    Args:
        team_id: TeamSnap team ID
    """
    return _run(teamsnap_agent.get_roster(team_id))


@tool
def teamsnap_availability(event_id: str) -> str:
    """Get availability responses for a TeamSnap event.

    Args:
        event_id: TeamSnap event ID
    """
    return _run(teamsnap_agent.get_availability(event_id))


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
    return wf.recommend_responses(_USER, days)


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
                            "cal-audit", "response-times", "followup", "commitments", "prep-1on1", "prep-meeting"}
        _DANGEROUS_CHARS = set(";|&`$(){}!><")
        first_word = command.strip().split()[0] if command.strip() else ""
        if first_word not in _ALLOWED_SUBCMDS:
            return f"Rejected: '{first_word}' is not a known envoy subcommand. Allowed: {', '.join(sorted(_ALLOWED_SUBCMDS))}"
        if any(c in command for c in _DANGEROUS_CHARS):
            return "Rejected: command contains unsafe shell characters."
        exe = _envoy_path()
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
    return wf.pto_catchup(_USER, days)


@tool
def slack_catchup(days: int = 3) -> str:
    """Focused Slack catch-up — unread channels, @mentions, and unanswered DMs.
    Use when the user says "catch me up on Slack", "what did I miss on Slack?", or "unread Slack".

    Args:
        days: Number of days to look back (default 3)
    """
    return wf.slack_catchup(_USER, days)


@tool
def yesterbox(days: int = 1) -> str:
    """Yesterbox — focused queue of yesterday's direct messages (TO-line emails + Slack DMs),
    prioritized with action items extracted.
    Use when the user says "yesterbox", "yesterday's messages", or "what came in yesterday?".

    Args:
        days: Number of days to look back (default: 1 for yesterday)
    """
    alias = _USER
    return wf.yesterbox(alias, days)


@tool
def calendar_audit(days: int = 5) -> str:
    """Audit your calendar — meeting load, focus time, back-to-backs, and decline suggestions.
    Use when the user says "audit my calendar", "too many meetings", or "optimize my week".

    Args:
        days: Number of days ahead to analyze (default 5)
    """
    return wf.calendar_audit(_USER, days)


@tool
def response_time_tracker(days: int = 7) -> str:
    """Analyze email response patterns — how fast you reply and how fast others reply to you.
    Use when the user asks "how's my response time?", "who haven't I replied to?", or "email patterns".

    Args:
        days: Number of days to analyze (default 7)
    """
    return wf.response_time_tracker(_USER, days)


@tool
def follow_up_tracker(days: int = 7) -> str:
    """Scan your sent emails for unanswered threads — things you sent that never got a reply.
    Surfaces them ranked by urgency with suggested follow-up actions.
    Use when the user asks "what's pending?", "any unanswered emails?", or "what fell through the cracks?".

    Args:
        days: Number of days to look back (default 7)
    """
    return wf.follow_up_tracker(_USER, days)


@tool
def one_on_one_prep(person_alias: str) -> str:
    """Generate a 1:1 prep brief for a meeting with a specific person.
    Pulls their Phonetool profile, recent email threads between you, shared to-do items,
    and upcoming shared meetings. Suggests talking points.
    Use when the user says "prep for my 1:1 with [person]" or "what should I discuss with [person]?".

    Args:
        person_alias: Amazon login/alias of the person you're meeting with
    """
    return wf.one_on_one_prep(person_alias, _USER)


@tool
def commitment_tracker(days: int = 7) -> str:
    """Scan your sent emails and Slack messages for commitments and promises you made to others.
    Identifies things like "I'll send that by Friday", "let me follow up", "action on me".
    Use when the user asks "what did I promise?", "any open commitments?", or "what do I owe people?".

    Args:
        days: Number of days to look back (default 7)
    """
    return wf.commitment_tracker(_USER, days)


@tool
def meeting_prep(meeting_subject: str = "") -> str:
    """Generate a prep brief for an upcoming meeting. Looks up attendees on Phonetool,
    finds related email threads, and suggests talking points.
    If no subject given, preps for the next upcoming meeting.
    Use when the user says "prep me for [meeting]" or "what's my next meeting about?".

    Args:
        meeting_subject: Meeting title to search for (empty = next upcoming meeting)
    """
    return wf.meeting_prep(meeting_subject, _USER)


# --- Utility tools ---

@tool
def current_time() -> str:
    """Get the current date, time, and timezone. Use this whenever you need to know the current time,
    especially for calendar operations, scheduling, or when the user asks about time."""
    from datetime import datetime, timezone, timedelta
    import time as _time
    utc_offset = timedelta(seconds=-_time.timezone if _time.daylight == 0 else -_time.altzone)
    now = datetime.now(timezone(utc_offset))
    tz_name = _time.tzname[_time.daylight] if _time.daylight else _time.tzname[0]
    return now.strftime(f'%A, %B %d %Y at %I:%M %p {tz_name} (UTC%z)')


# --- Internal websites tools ---

@tool
def token_usage() -> str:
    """Show AI token usage for the current session — total input/output tokens and per-tier breakdown."""
    return format_token_usage()


@tool
def activate_skill(name: str) -> str:
    """Activate an Agent Skill by name to load its full instructions.
    Use when a task matches a skill's description from the available_skills catalog.

    Args:
        name: Skill name from the catalog
    """
    return activate_skill_fn(name, get_skills())


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
        max_tokens=600, tier="medium"
    )


@tool
def get_observer_insights() -> str:
    """Get a summary of what the observer has learned — recent observations and entity counts."""
    entries = memory._load_entries(7)
    if not entries:
        return "No memory entries yet."
    observations = [e for e in entries if e.get("type") == "observation"]
    entities = memory.known_entities()
    return (f"**{len(entries)} entries** (last 7d), {len(observations)} observations\n"
            f"**Top entities:** {', '.join(entities[:15])}\n\n"
            f"Use `recall('entity_name')` to dig into any of these.")


@tool
def recall_memory(query: str = "", limit: int = 20) -> str:
    """Recall memory by topic, person, or project. Empty query returns recent entries + summary.

    Args:
        query: Entity name, person, project, or topic to search for (empty = general recall)
        limit: Max entries to return
    """
    return memory.recall(query, limit)


# ============================================================
# Worker agent routing — supervisor delegates to specialists
# ============================================================

def _delegate(worker_name: str, request: str, _retries: int = 1) -> str:
    """Route to a worker agent with retry and graceful degradation."""
    import sys
    last_err = None
    for attempt in range(_retries + 1):
        try:
            result = get_worker(worker_name)(request)
            response = str(result.message) if hasattr(result, 'message') else str(result)
            try:
                memory.remember(f"[{worker_name}] {request[:200]} → {response[:200]}", entry_type="observation")
            except Exception:
                pass
            return response
        except Exception as e:
            last_err = e
            print(f"[{worker_name}] attempt {attempt+1} failed: {e}", file=sys.stderr)
            if attempt < _retries:
                # Clear cached worker in case it's in a bad state
                from agents.workers import _workers
                _workers.pop(worker_name, None)
    return f"⚠️ {worker_name} worker unavailable: {last_err}. Other sources may still have the information you need."


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
    """Delegate research and lookup tasks: Phonetool profiles, Kingpin goals, Wiki pages,
    Taskei tasks, Broadcast videos, tiny links, web search. Use for ANY internal lookup
    or external web search request.

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


# --- Export tools (stay on supervisor — they take content from other tools) ---

@tool
def export_word(content: str, filename: str = "") -> str:
    """Export any report or content to a Word document (.docx).

    Args:
        content: Markdown content to convert
        filename: Output filename (default: auto-generated)
    """
    return f"✅ Word document saved: {export.to_docx(content, filename)}"


@tool
def export_pptx(content: str, filename: str = "", title: str = "Envoy Report") -> str:
    """Export any report to a PowerPoint deck (.pptx). Each ## section becomes a slide.

    Args:
        content: Markdown content to convert
        filename: Output filename (default: auto-generated)
        title: Title for the cover slide
    """
    return f"✅ PowerPoint saved: {export.to_pptx(content, filename, title)}"


_ALL_TOOLS_RAW = [
    # --- Worker agent routing (5 tools → replaces ~40 direct tools) ---
    email_worker,
    comms_worker,
    calendar_worker,
    productivity_worker,
    research_worker,
    sharepoint_worker,
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
    observe_interaction,
    analyze_patterns,
    get_observer_insights,
    # --- Meta ---
    current_time,
    token_usage,
    activate_skill,
    # --- TeamSnap ---
    teamsnap_auth,
    teamsnap_schedule,
    teamsnap_roster,
    teamsnap_availability,
]

# Add supervisor tools (gather, read_email_thread, lookup_person, search_emails, show_context)
try:
    from supervisor import SUPERVISOR_TOOLS
    _ALL_TOOLS_RAW.extend(SUPERVISOR_TOOLS)
except ImportError:
    pass

ALL_TOOLS = [logged_tool(_demo_wrap(t)) for t in _ALL_TOOLS_RAW] if _DEMO_MODE else [logged_tool(t) for t in _ALL_TOOLS_RAW]
