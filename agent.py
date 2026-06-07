"""Envoy — Strands-based conversational EA agent."""
import os
import json
from pathlib import Path
from envoy_logger import get_logger

CONFIG_DIR = Path.home() / ".envoy"
SOUL_FILE = CONFIG_DIR / "soul.md"
ENVOY_FILE = CONFIG_DIR / "envoy.md"
PROCESS_FILE = CONFIG_DIR / "process.md"
SESSIONS_DIR = CONFIG_DIR / "sessions"
TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_file(path: Path) -> str:
    if path.exists():
        return path.read_text().strip()
    return ""


# --- Steering docs (from Vault) ---
# Loaded contextually when Envoy is doing writing, review, or decision tasks.
# The system prompt gets a lightweight summary; full docs loaded on demand.

_STEERING_DOCS = {
    "language-standards": "Language rules — banned phrases, active voice, formatting",
    "doc-review-standards": "How Mark reviews documents — first pass, flags, what makes a great doc",
    "leadership-principles": "LPs as evaluation lenses — questions to ask of any document",
    "decision-frameworks": "Named decision frameworks — one-way doors, Tim Hortons test, signal over noise",
    "business-context": "Org scope, key metrics, strategic priorities, competitive landscape",
    "persona": "How Mark works — communication style, operating philosophy, AI parsing guidance",
    "org-entity-linking-standard": "Standard for linking org/entity references across vault agents (Chinook, Portage)",
    "people-linking-standard": "Standard for people profile linking across Scout and Portage agents",
    "About Mark": "Canonical operating manual for AI agents — preferences, patterns, communication style",
}


def _get_steering_summary() -> str:
    """Return a lightweight summary of available steering docs for the system prompt."""
    steering_path = _get_steering_path()
    if not steering_path:
        return ""

    available = []
    for name, desc in _STEERING_DOCS.items():
        if os.path.exists(os.path.join(steering_path, f"{name}.md")):
            available.append(f"  - `{name}` — {desc}")

    if not available:
        return ""

    return """## Steering Docs (Vault)
When writing emails, documents, or reviews — or when evaluating documents for the user — load the relevant steering doc for contextual guidance. Use `load_steering_doc(name)` to get the full content.

Available:
""" + "\n".join(available) + """

**Auto-load rules:**
- Writing/drafting anything → load `language-standards`
- Reviewing a document → load `doc-review-standards` + `leadership-principles`
- Making a recommendation or decision → load `decision-frameworks`
- Needing business context → load `business-context`
"""


def _get_steering_path() -> str:
    """Get steering docs path from config."""
    try:
        config_file = CONFIG_DIR / "config.json"
        if config_file.exists():
            config = json.loads(config_file.read_text())
            path = config.get("steering_docs", "")
            if path and os.path.isdir(path):
                return path
    except Exception:
        pass
    return ""


def load_steering_doc(name: str) -> str:
    """Load a specific steering doc by name. Called by tools/skills on demand."""
    steering_path = _get_steering_path()
    if not steering_path:
        return ""
    fpath = os.path.join(steering_path, f"{name}.md")
    if os.path.exists(fpath):
        try:
            return open(fpath, encoding="utf-8", errors="ignore").read()
        except Exception:
            pass
    return ""


def _ensure_config_files():
    """Bootstrap config files from templates if missing, and migrate personality.md if present."""
    CONFIG_DIR.mkdir(exist_ok=True)
    import shutil

    # Migrate personality.md → merge into soul.md + envoy.md
    personality_file = CONFIG_DIR / "personality.md"
    if personality_file.exists():
        content = personality_file.read_text()
        # Agent identity fields → soul.md
        soul_additions = []
        # User facts → envoy.md
        envoy_additions = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- Agent name:"):
                soul_additions.append(stripped)
            elif stripped.startswith("- ") and any(stripped.startswith(f"- {k}:") for k in
                    ("Name", "Alias", "Role", "Manager", "Direct reports", "Signature")):
                envoy_additions.append(stripped)
            elif stripped.startswith("- "):
                envoy_additions.append(stripped)

        if soul_additions and SOUL_FILE.exists():
            with open(SOUL_FILE, "a") as f:
                f.write("\n# Migrated from personality.md\n")
                for line in soul_additions:
                    f.write(f"{line}\n")
        if envoy_additions and ENVOY_FILE.exists():
            with open(ENVOY_FILE, "a") as f:
                f.write("\n# Migrated from personality.md\n")
                for line in envoy_additions:
                    f.write(f"{line}\n")

        personality_file.rename(CONFIG_DIR / "personality.md.bak")

    # Copy templates for any missing files
    for filename in ("soul.md", "envoy.md", "process.md"):
        target = CONFIG_DIR / filename
        if not target.exists():
            src = TEMPLATES_DIR / filename
            if src.exists():
                shutil.copy(src, target)
            else:
                target.write_text(f"# {filename.replace('.md', '').title()}\n")

    # Install bundled skills if skills dir doesn't exist yet
    bundled_skills = TEMPLATES_DIR / "skills"
    user_skills = CONFIG_DIR / "skills"
    if bundled_skills.is_dir() and not user_skills.exists():
        shutil.copytree(bundled_skills, user_skills)


def _build_system_prompt() -> str:
    _ensure_config_files()
    soul = _load_file(SOUL_FILE)
    envoy_prefs = _load_file(ENVOY_FILE)
    process = _load_file(PROCESS_FILE)

    prompt = """You are Envoy — an AI chief of staff managing email, Slack, calendar, to-dos, tickets, and EA delegation. Act like a trusted EA who knows the user's priorities, people, and preferences deeply.

## CORE BEHAVIOR
- Greetings/small talk → reply in one line, no tools. Only brief when explicitly asked.
- Prioritize ruthlessly: 🔴 Action Required → 🟡 Heads Up → 🟢 FYI. Lead with 🔴.
- Cross-reference across sources. Connect dots between email, Slack, calendar, tickets.
- Be opinionated — recommend actions, don't just present data.
- Anticipate: flag meetings without prep, approaching deadlines, cold threads.
- Be concise. Bullets > paragraphs. Action items > summaries.
- Embody the Soul personality below. If none configured, be sharp and professional.

## TOOL STRATEGY
- **gather** for 2+ sources (parallel fetch). Prefer over individual tools.
- After gather, use `drill_down` with ref IDs ([E1], [S1], [C1]) for follow-ups — don't re-fetch.
- **FAIL FAST:** If a tool returns "unavailable"/"timed out", deliver partial results immediately. Do NOT retry via alternate tools. 60% in 30s beats 100% in 5 minutes.
- Chain tools when valuable: scan → offer reply/to-do/summary actions.
- Use `coding_worker` for any dev work (code, scripts, config). It runs autonomously.
- Coding tasks: delegate to coding_worker. Do NOT attempt code changes with other tools.

## GUARDRAILS
- Confirm before: sending email/Slack, deleting, modifying soul/envoy/process files.
- NEVER guess email addresses. Get from: email headers, Phonetool lookup, or High Priority People.
- Strict timeframes: only include items within the requested window. State exact date range.
- If user has a configured Signature, append to outgoing messages.
- Never fabricate data.

## MEMORY & LEARNING
- `remember` tool: persist actions taken, user decisions, deferred items. Not routine re-fetchable data.
- Corrections auto-detected and saved to process memory ("no", "wrong", "always", "never").
- For important people: use `add_vip` to save to High Priority People.
- After scans: suggest 2-3 concrete next steps.

## SHAREPOINT
- Knowledge Folder: default read/search location for user's files.
- Exports Folder: default save location for generated docs.
"""

    if soul:
        # Cap soul at 6K chars — if longer, it's likely accumulated cruft
        soul_text = soul[:6000]
        if len(soul) > 6000:
            soul_text += "\n_(Soul truncated — edit ~/.envoy/soul.md to trim)_"
        prompt += f"\n## Soul\n{soul_text}\n"

    if envoy_prefs:
        prompt += f"\n## User Context\n{envoy_prefs}\n"

    if process:
        # Cap process memory at 4K chars — most impactful rules are at the top
        proc_text = process[:4000]
        if len(process) > 4000:
            proc_text += "\n_(Process memory truncated to most recent rules)_"
        prompt += f"\n## Process Memory\n{proc_text}\n"

    from datetime import datetime, timezone, timedelta
    import time as _time
    is_dst = _time.localtime().tm_isdst > 0
    utc_offset = timedelta(seconds=-_time.altzone if is_dst else -_time.timezone)
    tz_name = _time.tzname[1] if is_dst else _time.tzname[0]
    now = datetime.now(timezone(utc_offset)).strftime('%A, %B %d %Y %I:%M %p').replace(' 0', ' ')
    prompt += f"\n**Now:** {now} {tz_name} (use `current_time` tool for precision)\n"

    # Inject persistent memory (capped to avoid bloating system prompt)
    try:
        from agents.memory2 import recall
        mem = recall()
        if mem:
            # Cap at ~1K tokens (~4K chars) — detailed recall available via recall_memory tool
            if len(mem) > 4000:
                mem = mem[:4000] + "\n\n_(Memory truncated — use `recall_memory` tool for full details)_"
            prompt += f"\n{mem}\n"
    except Exception:
        pass

    # Inject steering doc awareness (lightweight — full docs loaded on demand)
    try:
        steering = _get_steering_summary()
        if steering:
            prompt += f"\n{steering}\n"
    except Exception:
        pass

    # Inject skill catalog (compact — one line per skill, ~50 chars each)
    try:
        from agents.skills import get_skills
        skills = get_skills()
        if skills:
            lines = [f"- **{s['name']}**: {s['description'][:80]}" for s in skills.values()]
            prompt += f"\n## Skills (call `activate_skill` by name to load full instructions)\n" + "\n".join(lines) + "\n"
    except Exception:
        pass

    return prompt


# --- Streaming + step consumer registries ---
# UI layers (TUI) can register callables to receive live progress signals.
#   set_stream_consumer(fn(chunk)) — each streaming text chunk
#   set_step_consumer(fn(label))   — each new tool selection ("📧 Email", etc.)

_stream_consumer = None
_step_consumer = None


def set_stream_consumer(fn):
    """Register a callable invoked with each streaming text chunk, or None to clear."""
    global _stream_consumer
    _stream_consumer = fn


def set_step_consumer(fn):
    """Register a callable invoked with a friendly label each time a new tool fires."""
    global _step_consumer
    _step_consumer = fn


def emit_step(label: str):
    """Emit a progress step to the TUI spinner. Safe to call from any thread."""
    if _step_consumer is not None:
        try:
            _step_consumer(label)
        except Exception:
            pass


def _create_reasoning_callback_handler():
    """Create a callback handler that shows brief status teasers and forwards streamed text.

    Strands calls this handler for every event: streaming text chunks, tool selections,
    and results. Streamed text is forwarded to the registered consumer (if any) so the
    TUI can render partial output; tool selections still emit clean log events.
    """
    state = {
        "step_number": 0,
        "started": False,
        "seen_tools": set(),
    }

    # Friendly labels for worker/tool names
    _LABELS = {
        "email_worker": "📧 Email",
        "comms_worker": "💬 Slack",
        "calendar_worker": "📅 Calendar",
        "productivity_worker": "✅ Productivity",
        "research_worker": "🔎 Research",
        "sharepoint_worker": "📁 SharePoint",
        "coding_worker": "💻 Coding",
        "gather": "📊 Gathering data",
        "observe_interaction": "👁 Observing",
        "activate_skill": "🧩 Loading skill",
    }

    def reasoning_callback_handler(**kwargs):
        try:
            logger = get_logger()

            # Forward streaming text to the registered consumer; otherwise drop it
            # so the legacy console path stays quiet.
            if "data" in kwargs:
                if _stream_consumer is not None:
                    chunk = kwargs.get("data")
                    if isinstance(chunk, str) and chunk:
                        try:
                            _stream_consumer(chunk)
                        except Exception:
                            pass
                return

            if kwargs.get("init_event_loop") and not state["started"]:
                state["started"] = True
                state["step_number"] = 0
                state["seen_tools"] = set()
                logger.new_request_id()

            if "current_tool_use" in kwargs:
                tool_info = kwargs["current_tool_use"]
                tool_name = tool_info.get("name", "") if isinstance(tool_info, dict) else ""
                if tool_name and tool_name not in state["seen_tools"]:
                    state["seen_tools"].add(tool_name)
                    state["step_number"] += 1
                    label = _LABELS.get(tool_name, tool_name)
                    logger.log(
                        "INFO",
                        "reasoning_step",
                        label,
                        step_number=state["step_number"],
                        chosen_action=tool_name,
                    )
                    if _step_consumer is not None:
                        try:
                            _step_consumer(label)
                        except Exception:
                            pass

            if kwargs.get("result") is not None and state["started"]:
                logger.log(
                    "INFO",
                    "reasoning_end",
                    "Done",
                    step_count=state["step_number"],
                )
                state["started"] = False
                state["step_number"] = 0
                state["seen_tools"] = set()

        except Exception:
            pass

    return reasoning_callback_handler


def _supports_prompt_caching(model_id: str) -> bool:
    """Bedrock prompt caching is only supported on Claude and Nova model families."""
    return "anthropic.claude" in model_id or "amazon.nova" in model_id


def _system_prompt_for_model(text: str, model_id: str):
    """Wrap the system prompt in a cachePoint block when the model supports caching.

    Returns either a plain string (no caching) or a list of SystemContentBlock items
    with a trailing cachePoint marker, which tells Bedrock to cache everything before
    it. Cached for ~5 min idle; saves the system-prompt token cost on follow-up turns.
    """
    if not _supports_prompt_caching(model_id):
        return text
    try:
        from strands.types.content import SystemContentBlock
    except ImportError:
        return text
    return [
        SystemContentBlock(text=text),
        SystemContentBlock(cachePoint={"type": "default"}),
    ]


def create_agent(session_id: str = "default"):
    """Create a Envoy Strands agent with personality, soul, and session persistence."""
    CONFIG_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)

    # Set up logger with session ID
    try:
        logger = get_logger()
        logger.set_session_id(session_id)
    except Exception:
        pass

    from agents.base import _load_models
    from strands import Agent
    from strands.models import BedrockModel
    from strands.session.file_session_manager import FileSessionManager
    from tools import ALL_TOOLS

    agent_model_id = _load_models().get("agent", "us.anthropic.claude-opus-4-7-v1")

    model = BedrockModel(
        model_id=agent_model_id,
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
    )

    session_manager = FileSessionManager(
        session_id=session_id,
        base_dir=str(SESSIONS_DIR),
    )

    callback_handler = _create_reasoning_callback_handler()

    agent = Agent(
        model=model,
        system_prompt=_system_prompt_for_model(_build_system_prompt(), agent_model_id),
        tools=ALL_TOOLS,
        session_manager=session_manager,
        callback_handler=callback_handler,
    )

    # Allow skill activation to inject tools at runtime
    from tools import set_active_agent
    set_active_agent(agent)

    return agent


# --- Singleton accessor ---
# Callers (TUI, REPL, dispatch) should fetch the agent via get_agent() rather
# than holding a long-lived reference. After reload_agent() is invoked (e.g.
# from /models when model assignments change, or from /settings after a soul
# edit), the next get_agent() rebuilds with the fresh config.

_AGENT_INSTANCE = None


def get_agent(session_id: str = "default"):
    """Return the cached agent, creating it lazily on first call."""
    global _AGENT_INSTANCE
    if _AGENT_INSTANCE is None:
        _AGENT_INSTANCE = create_agent(session_id)
    return _AGENT_INSTANCE


def reload_agent() -> None:
    """Drop the cached agent so the next get_agent() rebuilds it.

    Also invalidates the cached user alias — a settings edit may have
    changed envoy.md's "- Alias:" line.
    """
    global _AGENT_INSTANCE
    _AGENT_INSTANCE = None
    try:
        from agents.base import reload_user
        reload_user()
    except Exception:
        pass
