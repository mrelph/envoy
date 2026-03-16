"""Attaché — Strands-based conversational EA agent."""
import os
import json
from pathlib import Path
from strands import Agent
from strands.models import BedrockModel
from strands.session.file_session_manager import FileSessionManager
from strands.handlers import null_callback_handler
from tools import ALL_TOOLS

CONFIG_DIR = Path.home() / ".attache"
PERSONALITY_FILE = CONFIG_DIR / "personality.md"
SOUL_FILE = CONFIG_DIR / "soul.md"
ATTACHE_FILE = CONFIG_DIR / "attache.md"
SESSIONS_DIR = CONFIG_DIR / "sessions"


def _load_file(path: Path) -> str:
    if path.exists():
        return path.read_text().strip()
    return ""


def _build_system_prompt() -> str:
    personality = _load_file(PERSONALITY_FILE)
    soul = _load_file(SOUL_FILE)
    attache_prefs = _load_file(ATTACHE_FILE)

    prompt = """You are Attaché — an AI chief of staff. You manage your user's email, Slack, calendar, to-dos, tickets, and EA delegation. Your job is to keep them informed, unblocked, and ahead of everything.

You are not a chatbot. You are a trusted operator with judgment. Act like a seasoned executive assistant who has worked with this person for years — you know their priorities, their people, and how they like things done.

## IDENTITY
- Embody the personality defined in the Soul config below. This is not flavor text — it IS who you are. Commit fully.
- If the user configured an "Agent name", use it as your name instead of "Attaché".
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
- For briefings (/briefing), call morning_briefing which orchestrates calendar + to-dos + email + Slack + tickets in one pass.
- Chain tools when it adds value: after a scan, offer to reply, add to-dos, email a summary, or mark Slack as read.
- Before calendar briefings, cross-reference attendees against recent email and Slack for context and prep notes.
- When the user corrects you or states a preference: use update_soul for personality/behavior, update_attache for preferences (channels, email rules, people, calendar), update_personality for facts about them.

## GUARDRAILS
- Always confirm before: deleting emails, sending emails/replies, sending Slack messages, or any destructive action.
- If a tool call fails, explain what happened plainly and suggest an alternative. Don't retry silently.
- Never fabricate information. If you don't have data, say so and offer to look it up.
- If the user's config includes a "Signature", append it to any emails or Slack messages you send on their behalf.
- **Strict timeframes:** When the user asks for "last 48 hours", "past week", etc., ONLY include items dated within that window. Do not surface older items even if they appear in the fetched data. State the exact date range at the top of your response.

## MEMORY
- Use the `remember` tool to persist important context across sessions.
- **Always remember:** actions you take (emails sent, meetings created, Slack DMs), user decisions, deferred items, and key context from briefings.
- **Don't remember:** routine data that can be re-fetched (email counts, calendar listings), or anything already in soul/personality/preferences files.
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

    if personality:
        prompt += f"\n## About Your User\n{personality}\n"

    if soul:
        prompt += f"\n## Your Soul (Personality & Behavior)\n{soul}\n"

    if attache_prefs:
        prompt += f"\n## User Preferences\n{attache_prefs}\n"

    from datetime import datetime
    now = datetime.now().strftime('%A, %B %d %Y at %I:%M %p').replace(' 0', ' ')
    prompt += f"\n## Current Time\n{now}\n"

    # Inject persistent memory
    try:
        from service import AttacheService
        memory = AttacheService().recall()
        if memory:
            prompt += f"\n{memory}\n"
    except Exception:
        pass

    return prompt


def create_agent(session_id: str = "default") -> Agent:
    """Create a Attaché Strands agent with personality, soul, and session persistence."""
    CONFIG_DIR.mkdir(exist_ok=True)
    SESSIONS_DIR.mkdir(exist_ok=True)

    from service import AttacheService
    agent_model_id = AttacheService._load_models().get("agent", "us.anthropic.claude-opus-4-6-v1")

    model = BedrockModel(
        model_id=agent_model_id,
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
    )

    session_manager = FileSessionManager(
        session_id=session_id,
        base_dir=str(SESSIONS_DIR),
    )

    return Agent(
        model=model,
        system_prompt=_build_system_prompt(),
        tools=ALL_TOOLS,
        session_manager=session_manager,
        callback_handler=null_callback_handler,
    )


def _check_mcp_servers():
    """Check which MCP servers are reachable."""
    import shutil
    servers = {
        "Outlook":  "aws-outlook-mcp",
        "Slack":    "ai-community-slack-mcp",
        "Phonetool": "builder-mcp",
        "Bedrock":  None,  # check via boto3
    }
    status = {}
    for name, cmd in servers.items():
        if cmd:
            status[name] = shutil.which(cmd) is not None
        else:
            try:
                import boto3
                boto3.client('bedrock-runtime', region_name='us-west-2')
                status[name] = True
            except Exception:
                status[name] = False
    return status


def _render_status_bar(console, mcp_status=None):
    """Print a status bar showing MCP server connectivity."""
    if mcp_status is None:
        mcp_status = _check_mcp_servers()
    parts = []
    for name, ok in mcp_status.items():
        icon = "[green]●[/green]" if ok else "[red]●[/red]"
        parts.append(f"{icon} {name}")
    bar = "  ".join(parts)
    from datetime import datetime
    now = datetime.now().strftime('%I:%M %p').lstrip('0')
    console.print(f"[dim]─── {bar}  │  🕐 {now} ───[/dim]")


def _show_models(console):
    """Show current model assignments and offer to edit."""
    from rich.table import Table
    from rich.prompt import Prompt
    from rich import box
    from service import AttacheService
    models = AttacheService._load_models()
    tiers = {"agent": "Conversational agent", "heavy": "Summaries, EOD, weekly review",
             "medium": "Classification, scans, briefings", "light": "Ticket scan, simple extraction"}
    table = Table(title="AI Model Assignments", show_header=True, box=box.SIMPLE)
    table.add_column("Tier", style="cyan")
    table.add_column("Model ID", style="green")
    table.add_column("Used For", style="dim")
    for tier, desc in tiers.items():
        table.add_row(tier, models.get(tier, "—"), desc)
    console.print(table)

    # Show available models
    cat = Table(title="Available Models", show_header=True, box=box.SIMPLE)
    cat.add_column("#", style="cyan", width=3)
    cat.add_column("Model ID", style="green")
    cat.add_column("Name", style="bold")
    cat.add_column("Notes", style="dim")
    for i, (mid, name, notes) in enumerate(AttacheService.MODEL_CATALOG, 1):
        cat.add_row(str(i), mid, name, notes)
    console.print(cat)
    console.print(f"[dim]  Config: {AttacheService.MODELS_FILE}[/dim]")

    edit = Prompt.ask("[yellow]Edit a tier, or 'test' to test connections? (agent/heavy/medium/light/test/no)[/yellow]", default="no")
    if edit.lower() == "test":
        _test_models(console)
        return
    if edit.lower() in tiers:
        pick = Prompt.ask(f"[yellow]Enter model # from catalog or full model ID[/yellow]", default="")
        if pick.strip():
            if pick.strip().isdigit():
                idx = int(pick.strip()) - 1
                if 0 <= idx < len(AttacheService.MODEL_CATALOG):
                    new_model = AttacheService.MODEL_CATALOG[idx][0]
                else:
                    console.print("[red]Invalid number.[/red]")
                    return
            else:
                new_model = pick.strip()
            models[edit] = new_model
            os.makedirs(os.path.dirname(AttacheService.MODELS_FILE), exist_ok=True)
            with open(AttacheService.MODELS_FILE, "w") as f:
                json.dump(models, f, indent=2)
            console.print(f"[green]✓[/green] Saved. '{edit}' → {new_model}")


def _test_models(console):
    """Test connectivity for each configured model tier."""
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from service import AttacheService
    svc = AttacheService()
    models = svc._load_models()
    tested = set()
    for tier in ("agent", "heavy", "medium", "light"):
        mid = models.get(tier, "?")
        if mid in tested:
            console.print(f"  [cyan]{tier:7s}[/cyan] {mid} — [dim]same as above[/dim]")
            continue
        tested.add(mid)
        try:
            with Progress(SpinnerColumn("dots"), TextColumn(f"[dim]Testing {tier} ({mid})…[/dim]"), console=console, transient=True) as p:
                p.add_task("", total=None)
                reply = svc._invoke_ai("Reply with exactly: OK", max_tokens=10, tier=tier)
            console.print(f"  [cyan]{tier:7s}[/cyan] {mid} — [green]✓ OK[/green] [dim]({reply.strip()[:30]})[/dim]")
        except Exception as e:
            console.print(f"  [cyan]{tier:7s}[/cyan] {mid} — [red]✗ {e}[/red]")


def run_interactive():
    """Run the interactive agent loop."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.prompt import Prompt
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import box
    console = Console()

    # Check MCP servers once at startup
    mcp_status = _check_mcp_servers()

    console.print()
    LOGO = r"""[bold cyan]
     _   _   _             _      __
    / \ | |_| |_ __ _  ___| |__  /_/
   / _ \| __| __/ _` |/ __| '_ \ ___
  / ___ \ |_| || (_| | (__| | | / _ \
 /_/   \_\__|\__\__,_|\___|_| |_\___/[/bold cyan]
[dim]  Your AI Chief of Staff[/dim]
[dim italic]  Remember to mwinit -o before use[/dim italic]"""
    console.print(Panel.fit(LOGO, border_style="cyan", padding=(0, 2)))

    if not PERSONALITY_FILE.exists():
        console.print("\n[yellow]  💡 Run [bold]attache init[/bold] to personalize me, or just start chatting.[/yellow]")

    console.print()
    agent = create_agent()

    SLASH_COMMANDS = {
        "/calendar":  ("Review today's calendar",          lambda: agent("Review my calendar for today")),
        "/week":      ("Calendar for the week ahead",      lambda: agent("Review my calendar for the week ahead")),
        "/digest":    ("Team email digest",                 lambda: agent("Generate a team digest for the last 7 days")),
        "/boss":      ("Boss tracker",                      lambda: agent("Track my management chain's recent emails")),
        "/cleanup":   ("Inbox cleanup scan",                lambda: agent("Scan my inbox for junk to clean up")),
        "/customers": ("Customer email scan",               lambda: agent("Scan for external customer emails with action items")),
        "/slack":     ("Slack scan",                        lambda: agent("Scan my Slack channels for critical info and actions")),
        "/briefing":  ("Full briefing (calendar+email+slack)", lambda: agent("Give me a full briefing — calendar, inbox, and Slack")),
        "/todo":      ("Show my action items",              lambda: agent("What action items do I have pending?")),
        "/ea":        ("Send something to your EA",         None),
        "/findtime":  ("Find available meeting times",      lambda: agent("Find me available meeting times this week")),
        "/book":      ("Book a meeting room",               None),
        "/reply":     ("Reply to an email",                 None),
        "/search":    ("Search Slack history",              None),
        "/tickets":   ("Scan open tickets",                 lambda: agent("Scan my open tickets and SIMs")),
        "/eod":       ("End-of-day summary",                lambda: agent("Generate my end-of-day summary")),
        "/weekly":    ("Weekly review",                     lambda: agent("Generate my weekly review")),
        "/cron":      ("Manage scheduled jobs",             lambda: agent("Show my cron jobs and available presets")),
        "/help":      ("Show available commands",           None),
        "/status":    ("Refresh MCP server status",         None),
        "/exit":      ("Exit Attaché",                    None),
        "/models":    ("Show/edit AI model assignments",    None),
        "/settings":  ("Edit personality and config",        None),
    }

    def _show_help():
        from rich.table import Table
        table = Table(show_header=False, box=box.SIMPLE, padding=(0, 2))
        table.add_column(style="bold green")
        table.add_column(style="dim")
        for cmd, (desc, _) in SLASH_COMMANDS.items():
            table.add_row(cmd, desc)
        console.print(Panel(table, title="[bold]Commands[/bold]", border_style="dim", padding=(1, 2)))

    console.print("[dim]  Type /help for commands, /briefing for a full scan, or just chat naturally.[/dim]")
    _render_status_bar(console, mcp_status)
    console.print()

    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import HTML
    slash_completer = WordCompleter(
        list(SLASH_COMMANDS.keys()),
        sentence=True,
    )

    while True:
        try:
            user_input = pt_prompt(HTML('<ansigreen><b>✦ </b></ansigreen>'), completer=slash_completer, complete_while_typing=True)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye! 🔏[/dim]")
            break

        stripped = user_input.strip()
        if not stripped:
            continue

        if stripped.lower() in ("quit", "exit", "q", "/exit", "/quit"):
            console.print("[dim]Goodbye! 🔏[/dim]")
            break

        if stripped.lower() == "/help":
            _show_help()
            continue

        if stripped.lower() == "/status":
            mcp_status = _check_mcp_servers()
            _render_status_bar(console, mcp_status)
            continue

        if stripped.lower() == "/models":
            _show_models(console)
            continue

        if stripped.lower() == "/settings":
            from init_cmd import run_settings
            run_settings()
            agent = create_agent()  # reload personality
            continue

        if stripped.lower() == "/ea":
            ea_msg = Prompt.ask("[bold yellow]  Message for your EA[/bold yellow]")
            if ea_msg.strip():
                stripped = f"Send this to my EA: {ea_msg}"
            else:
                continue

        if stripped.lower() == "/book":
            bldg = Prompt.ask("[bold yellow]  Building code[/bold yellow]")
            time_range = Prompt.ask("[bold yellow]  Time range (e.g., 2-3pm tomorrow)[/bold yellow]")
            if bldg.strip() and time_range.strip():
                stripped = f"Find me a room in {bldg} for {time_range}"
            else:
                continue

        if stripped.lower() == "/reply":
            context = Prompt.ask("[bold yellow]  Which email? (describe it)[/bold yellow]")
            reply_text = Prompt.ask("[bold yellow]  Your reply[/bold yellow]")
            if context.strip() and reply_text.strip():
                stripped = f"Reply to the email about {context}: {reply_text}"
            else:
                continue

        if stripped.lower() == "/search":
            query = Prompt.ask("[bold yellow]  Search Slack for[/bold yellow]")
            if query.strip():
                stripped = f"Search Slack for: {query}"
            else:
                continue

        # Check slash commands
        cmd_match = SLASH_COMMANDS.get(stripped.lower())
        if cmd_match and cmd_match[1]:
            with Progress(SpinnerColumn("dots"), TextColumn(f"[dim]{cmd_match[0]}…[/dim]"), console=console, transient=True) as progress:
                progress.add_task("", total=None)
                response = cmd_match[1]()
        else:
            with Progress(SpinnerColumn("dots"), TextColumn("[dim]Thinking…[/dim]"), console=console, transient=True) as progress:
                progress.add_task("", total=None)
                response = agent(user_input)

        console.print()
        console.print(Panel(
            Markdown(str(response)),
            title="[bold cyan]🔏 Attaché[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))
        _render_status_bar(console, mcp_status)
        console.print()
