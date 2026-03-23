"""Envoy init — interactive setup that builds personality.md, soul.md, and envoy.md."""
import os
import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from service import EnvoyService

CONFIG_DIR = Path.home() / ".envoy"
PERSONALITY_FILE = CONFIG_DIR / "personality.md"
SOUL_FILE = CONFIG_DIR / "soul.md"
ENVOY_FILE = CONFIG_DIR / "envoy.md"

console = Console()


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  → {prompt}{suffix}: ").strip()
    return val or default


def _read_field(filepath: Path, key: str) -> str:
    if not filepath.exists():
        return ""
    for line in filepath.read_text().splitlines():
        if line.strip().startswith(f"- {key}:"):
            return line.split(":", 1)[1].strip()
    return ""


def _set_field(filepath: Path, key: str, value: str):
    if not filepath.exists():
        filepath.write_text(f"- {key}: {value}\n")
        return
    lines = filepath.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"- {key}:"):
            lines[i] = f"- {key}: {value}"
            filepath.write_text("\n".join(lines) + "\n")
            return
    # Not found — append under a sensible header
    lines.append(f"- {key}: {value}")
    filepath.write_text("\n".join(lines) + "\n")


def run_settings():
    """Edit config interactively."""
    if not PERSONALITY_FILE.exists():
        console.print("[yellow]No config found. Running full setup...[/yellow]\n")
        run_init()
        return

    console.print(Panel("⚙️  Envoy Settings", style="bold cyan"))

    fields = [
        (PERSONALITY_FILE, "Name",       "Name"),
        (PERSONALITY_FILE, "Role",       "Role"),
        (PERSONALITY_FILE, "Manager",    "Manager"),
        (PERSONALITY_FILE, "Agent name", "Agent name"),
        (PERSONALITY_FILE, "Signature",  "Signature"),
        (ENVOY_FILE,     "ea_alias",   "EA alias"),
        (ENVOY_FILE,     "ea_name",    "EA name"),
    ]

    from rich.table import Table
    from rich import box
    table = Table(show_header=True, box=box.SIMPLE)
    table.add_column("#", style="cyan", width=3)
    table.add_column("Setting", style="bold")
    table.add_column("Current Value", style="green")
    table.add_column("File", style="dim")
    editable = []
    for fpath, key, label in fields:
        val = _read_field(fpath, key) or "[dim]not set[/dim]"
        editable.append((fpath, key, label))
        table.add_row(str(len(editable)), label, val, fpath.name)
    console.print(table)

    console.print(f"\n[dim]  Config dir: {CONFIG_DIR}[/dim]")
    console.print("[dim]  personality.md = about you  |  soul.md = agent personality  |  envoy.md = preferences[/dim]\n")

    pick = _ask("Enter # to edit, 'soul' to regenerate soul.md, 'all' to re-run setup, or Enter to go back", "")
    if not pick:
        return
    if pick.lower() == "all":
        run_init()
        return
    if pick.lower() == "soul":
        _generate_soul_with_ai()
        return
    if pick.isdigit() and 1 <= int(pick) <= len(editable):
        fpath, key, label = editable[int(pick) - 1]
        current = _read_field(fpath, key)
        new_val = _ask(f"{label}", current)
        if new_val != current:
            _set_field(fpath, key, new_val)
            console.print(f"[green]✓[/green] Updated {key} → {new_val}")
    else:
        console.print("[red]Invalid selection.[/red]")


def _generate_soul_with_ai():
    """Use AI to generate soul.md from user inputs."""
    console.print(Panel("🧠 Generate Agent Soul with AI", style="bold magenta"))
    console.print("Answer a few questions and I'll craft a soul.md for your agent.\n")

    tone = _ask("Desired personality (e.g., 'witty British butler', 'sarcastic but helpful', 'chill surfer')", "friendly and professional")
    style = _ask("Communication style (e.g., 'concise bullets', 'narrative', 'emoji-heavy')", "concise bullets, lead with action items")
    quirks = _ask("Any quirks or catchphrases? (or Enter for none)", "")
    boundaries = _ask("Things the agent should NEVER do?", "never delete without asking, never send emails without confirmation")
    extras = _ask("Anything else about how the agent should behave?", "")

    prompt = f"""Generate a soul.md file for an AI executive assistant agent. This defines the agent's entire personality, tone, communication style, and behavioral rules.

User inputs:
- Personality/tone: {tone}
- Communication style: {style}
- Quirks/catchphrases: {quirks or 'none'}
- Boundaries: {boundaries}
- Additional notes: {extras or 'none'}

Write it in markdown with these sections:
# Soul
A brief 1-2 sentence identity statement.

# Personality & Tone
How the agent speaks and carries itself. Be specific and vivid.

# Communication Style
Formatting preferences, how to structure responses.

# Behavioral Rules
Hard rules the agent must always follow.

Make it feel like a real character description, not a boring config file. Be creative but faithful to the user's inputs. Output ONLY the markdown content, no preamble."""

    console.print("[dim]Generating with AI...[/dim]")
    try:
        svc = EnvoyService()
        soul_content = svc._invoke_ai(prompt, max_tokens=2000, tier="medium")
        console.print()
        console.print(Panel(soul_content, title="[bold magenta]Generated Soul[/bold magenta]", border_style="magenta"))
        console.print()
        choice = _ask("Save this? (yes/edit/no)", "yes")
        if choice.lower() in ("y", "yes"):
            SOUL_FILE.write_text(soul_content.strip() + "\n")
            console.print(f"[green]✓ Saved {SOUL_FILE}[/green]")
        elif choice.lower() in ("e", "edit"):
            SOUL_FILE.write_text(soul_content.strip() + "\n")
            console.print(f"[green]✓ Saved {SOUL_FILE}[/green] — edit it at {SOUL_FILE}")
        else:
            console.print("[dim]Discarded.[/dim]")
    except Exception as e:
        console.print(f"[red]AI generation failed: {e}[/red]")
        console.print("[dim]You can write soul.md manually instead.[/dim]")


def run_init():
    CONFIG_DIR.mkdir(exist_ok=True)

    # Migrate guidance.md → soul.md if needed
    old_guidance = CONFIG_DIR / "guidance.md"
    if old_guidance.exists() and not SOUL_FILE.exists():
        old_guidance.rename(SOUL_FILE)
        console.print(f"[dim]Migrated guidance.md → soul.md[/dim]")

    console.print(Panel("🔏 Envoy Setup", style="bold cyan"))
    console.print("Let me learn about you so I can be a better assistant.\n")

    alias = _ask("Your alias", os.environ.get("USER", ""))

    # Try Phonetool lookup
    name, title, manager, directs = "", "", "", []
    try:
        console.print(f"[dim]Looking you up in Phonetool...[/dim]")
        svc = EnvoyService()
        import asyncio
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        async def _lookup():
            async with stdio_client(svc.builder_mcp_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "ReadInternalWebsites",
                        arguments={"inputs": [f"https://phonetool.amazon.com/users/{alias}"]}
                    )
                    return str(result.content[0].text) if result.content else ""

        pt_text = asyncio.run(_lookup())
        for line in pt_text.split("\n"):
            if "Job Title:" in line or "Business Title:" in line:
                title = line.split(":", 1)[1].strip()
            elif "Manager:" in line:
                manager = line.split(":", 1)[1].strip()

        if title:
            console.print(f"  Found: [bold]{title}[/bold]")
        if manager:
            console.print(f"  Manager: {manager}")

        try:
            dr = asyncio.run(svc.get_direct_reports(alias))
            directs = [d.get("alias", d.get("name", "")) for d in dr]
            if directs:
                console.print(f"  Direct reports: {', '.join(directs)}")
        except Exception:
            pass

    except Exception as e:
        console.print(f"[dim]Phonetool lookup skipped: {e}[/dim]")

    console.print()
    name = _ask("Your name", name or alias)
    title = _ask("Your role/title", title)
    manager = _ask("Your manager", manager)
    agent_name = _ask("Name for your agent (or Enter to keep 'Envoy')", "")
    agent_sig = _ask("Signature for agent-sent emails/Slack (or Enter for none)", "")
    priorities = _ask("Top 3 priorities right now (comma-separated)", "")
    vips = _ask("People whose emails should always be flagged high priority", "")

    # --- Preferences (envoy.md) ---
    console.print()
    console.print("[bold]Preferences[/bold]")
    ignore = _ask("Types of email to always ignore", "vendor marketing, cold outreach")
    fav_channels = _ask("Favorite Slack channels to monitor (comma-separated, or Enter to skip)", "")
    calendar_prefs = _ask("Calendar preferences (e.g., 'no meetings before 9am', 'block focus time')", "")

    console.print()
    console.print("[bold]Executive Assistant[/bold]")
    ea_alias = _ask("Your EA's login (leave blank if none)", "")
    ea_name = ""
    if ea_alias:
        try:
            console.print(f"[dim]Looking up {ea_alias} in Phonetool...[/dim]")
            import asyncio as _aio
            from mcp import ClientSession as _CS
            from mcp.client.stdio import stdio_client as _sc

            async def _ea_lookup():
                async with _sc(svc.builder_mcp_params) as (r, w):
                    async with _CS(r, w) as s:
                        await s.initialize()
                        res = await s.call_tool("ReadInternalWebsites",
                            arguments={"inputs": [f"https://phonetool.amazon.com/users/{ea_alias}"]})
                        return str(res.content[0].text) if res.content else ""

            ea_text = _aio.run(_ea_lookup())
            for line in ea_text.split("\n"):
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("[") and not line.startswith("!"):
                    candidate = line.split("|")[0].strip().strip("*").strip()
                    if candidate and len(candidate.split()) <= 4 and candidate[0].isupper():
                        ea_name = candidate.split()[0]
                        console.print(f"  Found: [bold]{candidate}[/bold]")
                        break
        except Exception:
            pass
        ea_name = _ask(f"Your EA's first name", ea_name or ea_alias.capitalize())

    # --- Write personality.md ---
    personality = f"""# About Me
- Name: {name}
- Alias: {alias}
- Role: {title}
- Manager: {manager}
"""
    if agent_name:
        personality += f"\n# Agent Identity\n- Agent name: {agent_name}\n"
    if agent_sig:
        personality += f"- Signature: {agent_sig}\n"
    if directs:
        personality += f"- Direct reports: {', '.join(directs)}\n"
    if priorities:
        personality += f"\n# My Priorities\n- {priorities.replace(', ', chr(10) + '- ')}\n"
    if vips:
        personality += f"\n# High Priority People\n- {vips.replace(', ', chr(10) + '- ')}\n"

    PERSONALITY_FILE.write_text(personality)
    console.print(f"\n[green]✓ Saved {PERSONALITY_FILE}[/green]")

    # --- Write envoy.md ---
    prefs = "# Preferences\n"
    prefs += f"\n## Email\n- Ignore: {ignore}\n- KEEP by default — when in doubt, keep it\n"
    if vips:
        prefs += f"- Always flag emails from: {vips}\n"
    if fav_channels:
        prefs += f"\n## Slack\n- Favorite channels: {fav_channels}\n"
    if calendar_prefs:
        prefs += f"\n## Calendar\n- {calendar_prefs}\n"
    if ea_alias:
        prefs += f"\n## Executive Assistant\n- ea_alias: {ea_alias}\n- ea_name: {ea_name}\n"

    ENVOY_FILE.write_text(prefs)
    console.print(f"[green]✓ Saved {ENVOY_FILE}[/green]")

    # --- Soul: generate with AI or write defaults ---
    console.print()
    gen_soul = _ask("Generate agent soul/personality with AI? (yes/no)", "no")
    if gen_soul.lower() in ("y", "yes"):
        _generate_soul_with_ai()
    elif not SOUL_FILE.exists():
        style = _ask("Summary style preference", "concise bullets, lead with action items")
        tone = _ask("Agent personality/tone", "friendly and professional")
        soul = f"""# Soul
I am your AI chief of staff — sharp, proactive, and always one step ahead.

# Personality & Tone
- {tone}

# Communication Style
- {style}

# Behavioral Rules
- Always confirm before deleting emails or sending messages
- Be proactive with recommendations based on what you find
- When corrected, update soul.md or envoy.md to remember
"""
        SOUL_FILE.write_text(soul)
        console.print(f"[green]✓ Saved {SOUL_FILE}[/green]")
    else:
        console.print(f"[dim]Keeping existing {SOUL_FILE}[/dim]")

    console.print(f"\n[bold]Setup complete.[/bold] Edit files anytime, use /settings, or just tell me to adjust.\n")
