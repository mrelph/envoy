"""Envoy — Interactive REPL loop."""
import os
from agent import create_agent, _load_file, SOUL_FILE, CONFIG_DIR
from ui import (
    _check_mcp_servers,
    _check_mcp_servers_animated,
    _render_status_bar,
    _render_response,
    _show_models,
    _toast,
)


def run_interactive():
    """Run the interactive agent loop."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich import box
    console = Console()

    LOGO = r"""[bold cyan]
 ███████╗███╗   ██╗██╗   ██╗ ██████╗ ██╗   ██╗
 ██╔════╝████╗  ██║██║   ██║██╔═══██╗╚██╗ ██╔╝
 █████╗  ██╔██╗ ██║██║   ██║██║   ██║ ╚████╔╝
 ██╔══╝  ██║╚██╗██║╚██╗ ██╔╝██║   ██║  ╚██╔╝
 ███████╗██║ ╚████║ ╚████╔╝ ╚██████╔╝   ██║
 ╚══════╝╚═╝  ╚═══╝  ╚═══╝   ╚═════╝    ╚═╝[/bold cyan]
[dim]  ✈  Your AI Chief of Staff[/dim]"""
    console.print(Panel.fit(LOGO, border_style="cyan", padding=(0, 2)))

    # Animated MCP connection test
    console.print()
    mcp_status = _check_mcp_servers_animated(console)

    if os.environ.get("ENVOY_DEMO", "").strip().lower() in ("1", "true", "yes"):
        console.print("\n[bold yellow on red]  🎭 DEMO MODE — all names, emails, and IDs are masked  [/bold yellow on red]")

    if not SOUL_FILE.exists() or "<!-- " in _load_file(SOUL_FILE):
        console.print("\n[yellow]  💡 Run [bold]envoy init[/bold] to personalize me, or just start chatting.[/yellow]")

    console.print()
    agent = create_agent()

    SLASH_COMMANDS = {
        # --- Briefings ---
        "/briefing":  ("Full briefing (calendar+email+slack)", lambda: agent("Give me a full briefing — calendar, inbox, and Slack")),
        "/calendar":  ("Review today's calendar",              lambda: agent("Review my calendar for today")),
        "/week":      ("Calendar for the week ahead",          lambda: agent("Review my calendar for the week ahead")),
        "/todo":      ("Show my action items",                 lambda: agent("What action items do I have pending?")),
        # --- Scans & Digests ---
        "/digest":    ("Team email digest",                    None),  # parameterized
        "/boss":      ("Boss tracker",                         lambda: agent("Track my management chain's recent emails")),
        "/customers": ("Customer email scan",                  None),  # parameterized
        "/cleanup":   ("Inbox cleanup scan",                   None),  # parameterized (confirm)
        "/slack":     ("Slack scan",                           lambda: agent("Scan my Slack channels for critical info and actions")),
        "/tickets":   ("Scan open tickets",                    lambda: agent("Scan my open tickets and SIMs")),
        # --- Catch-up ---
        "/catchup":   ("PTO catch-up report",                  None),  # parameterized
        "/slack-catchup": ("Focused Slack catch-up",           None),  # parameterized
        "/yesterbox":     ("Yesterbox — yesterday's DMs",       lambda: agent("Run yesterbox for yesterday's messages")),
        # --- Analysis ---
        "/cal-audit":      ("Calendar audit",                  None),  # parameterized
        "/response-times": ("Email response time analysis",    None),  # parameterized
        "/followup":       ("Unanswered sent emails",          None),  # parameterized
        "/commitments":    ("Promises & commitments tracker",  None),  # parameterized
        # --- Prep ---
        "/prep-1on1":    ("1:1 prep brief",                    None),  # needs alias
        "/prep-meeting": ("Meeting prep brief",                None),  # needs subject
        # --- Actions ---
        "/reply":     ("Reply to an email",                    None),  # interactive
        "/ea":        ("Send something to your EA",            None),  # interactive
        "/findtime":  ("Find available meeting times",         lambda: agent("Find me available meeting times this week")),
        "/book":      ("Book a meeting room",                  None),  # interactive
        "/search":    ("Search Slack history",                 None),  # interactive
        "/sharepoint": ("Search or browse SharePoint/OneDrive", None),  # interactive
        # --- Reviews ---
        "/eod":       ("End-of-day summary",                   lambda: agent("Generate my end-of-day summary")),
        "/weekly":    ("Weekly review",                        lambda: agent("Generate my weekly review")),
        "/cron":      ("Manage scheduled jobs",                lambda: agent("Show my cron jobs and available presets")),
        # --- System ---
        "/help":      ("Show available commands",              None),
        "/status":    ("Refresh MCP server status",            None),
        "/models":    ("Show/edit AI model assignments",       None),
        "/settings":  ("Edit personality and config",          None),
        "/exit":      ("Exit Envoy",                           None),
    }

    def _show_help():
        from rich.table import Table
        from rich.columns import Columns

        groups = [
            ("Briefings", ["/briefing", "/calendar", "/week", "/todo"]),
            ("Digests & Scans", ["/digest", "/boss", "/customers", "/cleanup", "/slack", "/tickets"]),
            ("Catch-up", ["/catchup", "/slack-catchup", "/yesterbox"]),
            ("Analysis", ["/cal-audit", "/response-times", "/followup", "/commitments"]),
            ("Prep", ["/prep-1on1", "/prep-meeting"]),
            ("Actions", ["/reply", "/ea", "/book", "/findtime", "/search", "/sharepoint"]),
            ("Reviews", ["/eod", "/weekly", "/cron"]),
            ("System", ["/status", "/models", "/settings", "/help", "/exit"]),
        ]

        tables = []
        for group_name, cmds in groups:
            t = Table(show_header=True, box=box.SIMPLE, padding=(0, 1), title_style="bold cyan")
            t.add_column(f"[bold]{group_name}[/bold]", style="bold green", no_wrap=True)
            t.add_column("", style="dim")
            for cmd in cmds:
                entry = SLASH_COMMANDS.get(cmd)
                if entry:
                    t.add_row(cmd, entry[0])
            tables.append(t)

        console.print(Panel(
            Columns(tables, equal=True, expand=True),
            title="[bold]Commands[/bold]",
            subtitle="[dim]or just chat naturally · most commands accept a number of days, e.g. /digest 7[/dim]",
            border_style="dim",
            padding=(1, 2),
        ))

    console.print("[dim]  Type /help for commands, or just chat naturally.[/dim]")
    console.print()

    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import HTML
    slash_completer = WordCompleter(
        list(SLASH_COMMANDS.keys()),
        sentence=True,
    )

    # Load user alias for the prompt
    def _get_user_alias():
        try:
            for line in PERSONALITY_FILE.read_text().splitlines():
                if line.strip().startswith("- Alias:"):
                    return line.split(":", 1)[1].strip()
        except Exception:
            pass
        return os.environ.get("USER", "")

    user_alias = _get_user_alias()

    def _build_prompt_html():
        from datetime import datetime
        now = datetime.now()
        day = now.strftime('%a')
        time_str = now.strftime('%I:%M%p').lstrip('0').lower()
        parts = []
        if user_alias:
            parts.append(f'<style fg="ansibrightcyan">{user_alias}</style>')
        parts.append(f'<style fg="ansigray">{day} {time_str}</style>')
        context = ' <style fg="ansigray">·</style> '.join(parts)
        return HTML(f' {context} <ansigreen><b>› </b></ansigreen>')

    while True:
        try:
            user_input = pt_prompt(_build_prompt_html(), completer=slash_completer, complete_while_typing=True)
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

        # --- Parse slash command + optional args (e.g. "/digest 7") ---
        _parts = stripped.split(None, 1)
        _cmd = _parts[0].lower()
        _arg = _parts[1].strip() if len(_parts) > 1 else ""

        def _days_arg(default=7):
            return int(_arg) if _arg.isdigit() else default

        # --- Interactive slash commands ---
        if _cmd == "/ea":
            ea_msg = Prompt.ask("[bold yellow]  Message for your EA[/bold yellow]")
            stripped = f"Send this to my EA: {ea_msg}" if ea_msg.strip() else ""
        elif _cmd == "/book":
            bldg = Prompt.ask("[bold yellow]  Building code[/bold yellow]")
            time_range = Prompt.ask("[bold yellow]  Time range (e.g., 2-3pm tomorrow)[/bold yellow]")
            stripped = f"Find me a room in {bldg} for {time_range}" if bldg.strip() and time_range.strip() else ""
        elif _cmd == "/reply":
            ctx = Prompt.ask("[bold yellow]  Which email? (describe it)[/bold yellow]")
            reply_text = Prompt.ask("[bold yellow]  Your reply[/bold yellow]")
            stripped = f"Reply to the email about {ctx}: {reply_text}" if ctx.strip() and reply_text.strip() else ""
        elif _cmd == "/search":
            q = _arg or Prompt.ask("[bold yellow]  Search Slack for[/bold yellow]")
            stripped = f"Search Slack for: {q}" if q.strip() else ""
        elif _cmd == "/sharepoint":
            q = _arg or Prompt.ask("[bold yellow]  Search or describe what you need[/bold yellow]")
            stripped = f"On SharePoint/OneDrive: {q}" if q.strip() else ""
        # --- Parameterized slash commands ---
        elif _cmd == "/digest":
            stripped = f"Generate a team digest for the last {_days_arg(7)} days"
        elif _cmd == "/customers":
            stripped = f"Scan for external customer emails with action items from the last {_days_arg(14)} days"
        elif _cmd == "/cleanup":
            d = _days_arg(14)
            if not Confirm.ask(f"[yellow]  Scan inbox ({d} days) and suggest deletions?[/yellow]", default=True):
                continue
            stripped = f"Scan my inbox for junk to clean up, last {d} days"
        elif _cmd == "/catchup":
            stripped = f"I was out of office for {_days_arg(5)} days, give me a full catch-up"
        elif _cmd == "/slack-catchup":
            stripped = f"Give me a focused Slack catch-up for the last {_days_arg(3)} days — unread channels, mentions, and DMs"
        elif _cmd == "/cal-audit":
            stripped = f"Audit my calendar for the next {_days_arg(5)} days — meeting load, focus time, and what to decline"
        elif _cmd == "/response-times":
            stripped = f"Analyze my email response time patterns for the last {_days_arg(7)} days"
        elif _cmd == "/followup":
            stripped = f"Scan my sent emails for unanswered threads from the last {_days_arg(7)} days"
        elif _cmd == "/commitments":
            stripped = f"Scan my sent messages for commitments and promises from the last {_days_arg(7)} days"
        elif _cmd == "/prep-1on1":
            person = _arg or Prompt.ask("[bold yellow]  Person's alias[/bold yellow]")
            stripped = f"Generate a 1:1 prep brief for my meeting with {person.strip()}" if person.strip() else ""
        elif _cmd == "/prep-meeting":
            meeting = _arg or Prompt.ask("[bold yellow]  Meeting subject (empty = next meeting)[/bold yellow]", default="")
            stripped = f"Generate a prep brief for my meeting: {meeting}" if meeting.strip() else "Generate a prep brief for my next meeting"

        if not stripped:
            continue

        # --- Execute ---
        cmd_match = SLASH_COMMANDS.get(_cmd)
        if cmd_match and cmd_match[1]:
            try:
                if hasattr(agent, '_reasoning_callback'):
                    agent._reasoning_callback.set_user_input(stripped[:200])
            except Exception:
                pass
            with Progress(SpinnerColumn("dots"), TextColumn(f"[dim]{cmd_match[0]}…[/dim]"), console=console, transient=True) as progress:
                progress.add_task("", total=None)
                response = cmd_match[1]()
        else:
            try:
                if hasattr(agent, '_reasoning_callback'):
                    agent._reasoning_callback.set_user_input(stripped[:200])
            except Exception:
                pass
            _spinner_hints = {
                "email": "📧 Email", "inbox": "📧 Email", "digest": "📧 Email", "cleanup": "📧 Email",
                "slack": "💬 Slack", "channel": "💬 Slack",
                "calendar": "📅 Calendar", "meeting": "📅 Calendar", "schedule": "📅 Calendar",
                "todo": "✅ Productivity", "ticket": "✅ Productivity", "briefing": "✅ Productivity",
                "phonetool": "🔎 Research", "kingpin": "🔎 Research", "wiki": "🔎 Research",
                "sharepoint": "📁 SharePoint", "onedrive": "📁 SharePoint",
                "catch-up": "📊 Catch-up", "catchup": "📊 Catch-up",
            }
            _hint = "Thinking"
            for kw, label in _spinner_hints.items():
                if kw in stripped.lower():
                    _hint = label
                    break
            with Progress(SpinnerColumn("dots"), TextColumn(f"[dim]{_hint}…[/dim]"), console=console, transient=True) as progress:
                progress.add_task("", total=None)
                response = agent(stripped)

        console.print()
        _render_response(console, str(response))
        console.print()
