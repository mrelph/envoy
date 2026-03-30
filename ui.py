"""Envoy — Rich console rendering helpers."""
import os
import json


def _check_mcp_servers():
    """Check which MCP servers are actually reachable (live connection test)."""
    from agents.base import check_mcp_connections
    try:
        return check_mcp_connections()
    except Exception:
        return {}


def _check_mcp_servers_animated(console):
    """Animated startup: show each MCP server connecting in real-time with Live display."""
    import asyncio
    from rich.live import Live
    from rich.text import Text
    from agents.base import MCP_SERVERS, check_mcp_connections

    servers = dict(MCP_SERVERS)
    # Status tracking: None=pending, True=connected, False=failed
    status = {name: None for name in servers}
    status["Bedrock"] = None

    def _render():
        lines = Text()
        for name, st in status.items():
            if st is None:
                lines.append("  ◌ ", style="yellow")
                lines.append(name, style="dim")
                lines.append("  connecting…\n", style="dim italic")
            elif st is True:
                lines.append("  ● ", style="green")
                lines.append(name, style="green")
                lines.append("  connected\n", style="dim")
            else:
                lines.append("  ● ", style="red")
                lines.append(name, style="red")
                lines.append("  unavailable\n", style="dim")
        return lines

    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async def _test_one(name, params):
        try:
            async with stdio_client(params, errlog=open(os.devnull, "w")) as (r, w):
                async with ClientSession(r, w) as s:
                    await asyncio.wait_for(s.initialize(), timeout=10)
                    return name, True
        except Exception:
            return name, False

    async def _test_bedrock():
        try:
            import boto3
            client = boto3.client('bedrock-runtime', region_name='us-west-2')
            client.meta.endpoint_url
            return "Bedrock", True
        except Exception:
            return "Bedrock", False

    async def _run_all(live):
        tasks_list = []
        for n, p in servers.items():
            tasks_list.append(_test_one(n, p))
        tasks_list.append(_test_bedrock())

        for coro in asyncio.as_completed(tasks_list):
            name, ok = await coro
            status[name] = ok
            live.update(_render())

    with Live(_render(), console=console, refresh_per_second=8, transient=True) as live:
        asyncio.run(_run_all(live))
        live.update(_render())

    # Print final state after Live clears
    console.print(_render())

    return {name: (st is True) for name, st in status.items()}


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
    from agents.base import _load_models, MODEL_CATALOG, MODELS_FILE, invoke_ai
    models = _load_models()
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
    for i, (mid, name, notes) in enumerate(MODEL_CATALOG, 1):
        cat.add_row(str(i), mid, name, notes)
    console.print(cat)
    console.print(f"[dim]  Config: {MODELS_FILE}[/dim]")

    edit = Prompt.ask("[yellow]Edit a tier, or 'test' to test connections? (agent/heavy/medium/light/test/no)[/yellow]", default="no")
    if edit.lower() == "test":
        _test_models(console)
        return
    if edit.lower() in tiers:
        pick = Prompt.ask(f"[yellow]Enter model # from catalog or full model ID[/yellow]", default="")
        if pick.strip():
            if pick.strip().isdigit():
                idx = int(pick.strip()) - 1
                if 0 <= idx < len(MODEL_CATALOG):
                    new_model = MODEL_CATALOG[idx][0]
                else:
                    console.print("[red]Invalid number.[/red]")
                    return
            else:
                new_model = pick.strip()
            models[edit] = new_model
            os.makedirs(os.path.dirname(MODELS_FILE), exist_ok=True)
            with open(MODELS_FILE, "w") as f:
                json.dump(models, f, indent=2)
            console.print(f"[green]✓[/green] Saved. '{edit}' → {new_model}")


def _test_models(console):
    """Test connectivity for each configured model tier."""
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from agents.base import _load_models, invoke_ai
    models = _load_models()
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
                reply = invoke_ai("Reply with exactly: OK", max_tokens=10, tier=tier)
            console.print(f"  [cyan]{tier:7s}[/cyan] {mid} — [green]✓ OK[/green] [dim]({reply.strip()[:30]})[/dim]")
        except Exception as e:
            console.print(f"  [cyan]{tier:7s}[/cyan] {mid} — [red]✗ {e}[/red]")


def _toast(console, lines):
    """Render a toast-style notification panel for action confirmations."""
    from rich.panel import Panel
    from rich.text import Text
    content = Text()
    for i, line in enumerate(lines):
        content.append(line)
        if i < len(lines) - 1:
            content.append("\n")
    console.print(Panel.fit(
        content,
        border_style="green",
        padding=(0, 2),
    ))


def _render_response(console, response_text):
    """Render agent response with color-coded priority sections."""
    import re
    from rich.panel import Panel
    from rich.markdown import Markdown
    from agents.base import agent_name as _agent_name

    name = _agent_name()

    # Check if response contains priority markers
    priority_pattern = re.compile(r'^(.*?)(🔴|🟡|🟢)\s*', re.MULTILINE)
    has_priorities = bool(priority_pattern.search(response_text))

    if not has_priorities:
        console.print(Panel(
            Markdown(response_text),
            title=f"[bold cyan]🔏 {name}[/bold cyan]",
            border_style="cyan",
            padding=(1, 2),
        ))
        return

    # Split into sections by priority emoji at the start of lines
    section_pattern = re.compile(r'(?=^[#\s]*(?:🔴|🟡|🟢))', re.MULTILINE)
    parts = section_pattern.split(response_text)

    color_map = {"🔴": "red", "🟡": "yellow", "🟢": "green"}

    first = True
    for part in parts:
        part = part.strip()
        if not part:
            continue

        border = "cyan"
        label = f"🔏 {name}" if first else ""
        for emoji, color in color_map.items():
            if emoji in part[:80]:
                border = color
                break

        console.print(Panel(
            Markdown(part),
            title=f"[bold {border}]{label}[/bold {border}]" if label else "",
            border_style=border,
            padding=(1, 2),
        ))
        first = False
