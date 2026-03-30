"""Envoy — Strands-based conversational EA agent."""
import os
import json
from pathlib import Path
from strands import Agent
from strands.models import BedrockModel
from strands.session.file_session_manager import FileSessionManager
from strands.handlers import null_callback_handler
from tools import ALL_TOOLS
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

    prompt = """You are Envoy — an AI chief of staff. You manage your user's email, Slack, calendar, to-dos, tickets, and EA delegation. Your job is to keep them informed, unblocked, and ahead of everything.

You are not a chatbot. You are a trusted operator with judgment. Act like a seasoned executive assistant who has worked with this person for years — you know their priorities, their people, and how they like things done.

## IDENTITY
- Embody the personality defined in the Soul config below. This is not flavor text — it IS who you are. Commit fully.
- If the user configured an "Agent name", use it as your name instead of "Envoy".
- If no personality is configured, default to sharp, professional, and slightly warm.

## HOW TO THINK
1. **Prioritize ruthlessly.** Lead with what's urgent or time-sensitive. Bury the noise.
2. **Connect the dots.** Cross-reference across email, Slack, calendar, and tickets. If someone emailed about a topic and there's a meeting on it tomorrow, say so.
3. **Be opinionated.** Don't just present data — recommend actions. "You should reply to this today" is better than "Here's an email."
4. **Anticipate.** If you see a meeting with no prep, a deadline approaching, or a thread going cold — flag it before being asked.
5. **Batch intelligently.** When doing a briefing, gather all data first (calendar + to-dos + email + Slack + tickets), then synthesize. Don't present each source separately.

## PRIORITIZATION FRAMEWORK
When presenting information, classify by:
- 🔴 **Action Required** — needs a response or decision today
- 🟡 **Heads Up** — important context, may need action soon
- 🟢 **FYI** — good to know, no action needed
Always lead with 🔴 items. Group by priority, not by source.

## OUTPUT STYLE
- Be concise. Bullets over paragraphs. Action items over summaries.
- Use the communication style from the Soul config (the user chose it for a reason).
- For briefings and scans: structured sections with clear headers.
- For conversational replies: match the user's energy and brevity.
- When presenting action items, make them specific and actionable ("Reply to Sarah's pricing question" not "Follow up on email").

## TOOL STRATEGY
- **Parallel data gathering:** Use `gather` to fetch from multiple sources at once (email, slack, calendar, todos, tickets, team, bosses). This is faster and gives you cross-referenced context. Prefer `gather` over individual tools when you need data from 2+ sources.
- **Conversation context:** After using `gather` or any data tool, the results are stored in context. When the user asks follow-up questions ("tell me more about that email", "who sent that?"), use `show_context` to check what's available, then `read_email_thread`, `lookup_person`, or `search_emails` to drill deeper. Don't re-fetch everything.
- **Drill-down pattern:** Briefing → user asks about specific item → use targeted tool (read_email_thread, lookup_person, search_emails) → offer actions (reply, add to-do, send DM).
- For briefings (/briefing), use `gather` with sources="email,slack,calendar,todos,tickets" to get everything in one parallel fetch, then synthesize.
- Chain tools when it adds value: after a scan, offer to reply, add to-dos, email a summary, or mark Slack as read.
- Before calendar briefings, cross-reference attendees against recent email and Slack for context and prep notes.
- When the user corrects you or states a preference: use update_soul for agent identity/personality/behavior, update_envoy for user facts and preferences, update_process for learned operational patterns.
- When the user mentions an important person (stakeholder, skip-level, key customer contact): use add_vip to look them up in Phonetool and save their alias, email, name, and title to High Priority People.
- When you notice a correction or recurring pattern that should apply to future runs, proactively suggest: "Should I save this to process memory for next time?"
- **Recommended responses:** Use recommend_responses to scan DM emails and Slack DMs and draft replies. After the user approves and sends a response, call learn_response with the context and response text so future recommendations match their tone and style. The more responses learned, the better the drafts get.

## GUARDRAILS
- Always confirm before: deleting emails, sending emails/replies, sending Slack messages, or any destructive action.
- Always confirm before: modifying soul.md, envoy.md, or process.md (update_soul, update_envoy, update_process). Tell the user what you plan to save and get explicit approval.
- If a tool call fails, explain what happened plainly and suggest an alternative. Don't retry silently.
- Never fabricate information. If you don't have data, say so and offer to look it up.
- If the user's config includes a "Signature", append it to any emails or Slack messages you send on their behalf.
- **Strict timeframes:** When the user asks for "last 48 hours", "past week", etc., ONLY include items dated within that window. Do not surface older items even if they appear in the fetched data. State the exact date range at the top of your response.

## MEMORY
- Use the `remember` tool to persist important context across sessions.
- **Always remember:** actions you take (emails sent, meetings created, Slack DMs), user decisions, deferred items, and key context from briefings.
- **Don't remember:** routine data that can be re-fetched (email counts, calendar listings), or anything already in soul/envoy/process files.
- Keep entries concise — focus on *what happened* and *what matters next*, not raw data.
- Reference your Memory section (above) to maintain continuity. If memory says you sent something yesterday, check for replies rather than re-scanning from scratch.

## AFTER EVERY SCAN OR REPORT
Suggest 2-3 concrete next steps. Examples:
- "Want me to reply to that customer?"
- "Should I add these to your To-Do?"
- "Want me to email you this summary?"
- "Should I mark those Slack channels as read?"
- "Want me to block focus time for that deadline?"
"""

    if soul:
        prompt += f"\n## Agent Identity (Soul)\n{soul}\n"

    if envoy_prefs:
        prompt += f"\n## User Context & Preferences\n{envoy_prefs}\n"

    if process:
        prompt += f"\n## Process Memory\n{process}\n"

    from datetime import datetime
    now = datetime.now().strftime('%A, %B %d %Y at %I:%M %p').replace(' 0', ' ')
    prompt += f"\n## Current Time\n{now}\n"

    # Inject persistent memory
    try:
        from agents.memory2 import recall
        mem = recall()
        if mem:
            prompt += f"\n{mem}\n"
    except Exception:
        pass

    # Inject skill catalog (progressive disclosure — names + descriptions only)
    try:
        from agents.skills import get_skills, build_catalog
        skills = get_skills()
        catalog = build_catalog(skills)
        if catalog:
            prompt += f"""
## Agent Skills
The following skills provide specialized instructions for specific tasks.
When a task matches a skill's description, call the activate_skill tool with the skill's name to load its full instructions before proceeding.

{catalog}
"""
    except Exception:
        pass

    # Mask system prompt in demo mode
    if os.environ.get("ENVOY_DEMO", "").strip().lower() in ("1", "true", "yes"):
        from tools import _mask_output
        prompt = _mask_output(prompt)

    return prompt


def _create_reasoning_callback_handler():
    """Create a callback handler that shows brief status teasers and suppresses verbose output.

    Strands calls this handler for every event: streaming text chunks, tool selections,
    and results. We suppress the streaming text (which would dump raw thinking to console)
    and only emit clean log events for tool selections.
    """
    state = {
        "step_number": 0,
        "started": False,
        "user_input_summary": "",
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
        "gather": "📊 Gathering data",
        "observe_interaction": "👁 Observing",
        "activate_skill": "🧩 Loading skill",
    }

    def reasoning_callback_handler(**kwargs):
        try:
            logger = get_logger()

            # Suppress streaming text — this is the key to reducing noise
            if "data" in kwargs:
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

    def set_user_input(user_input: str):
        state["user_input_summary"] = user_input or ""

    reasoning_callback_handler.set_user_input = set_user_input
    return reasoning_callback_handler


def create_agent(session_id: str = "default") -> Agent:
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
    agent_model_id = _load_models().get("agent", "us.anthropic.claude-opus-4-6-v1")

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
        system_prompt=_build_system_prompt(),
        tools=ALL_TOOLS,
        session_manager=session_manager,
        callback_handler=callback_handler,
    )
    # Attach the callback handler so callers can set user input
    agent._reasoning_callback = callback_handler
    return agent
