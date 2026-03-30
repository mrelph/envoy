"""Envoy init — interactive setup that builds soul.md and envoy.md."""
import os
import json
import shutil
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from agents.base import invoke_ai, builder
from agents import people

CONFIG_DIR = Path.home() / ".envoy"
SOUL_FILE = CONFIG_DIR / "soul.md"
ENVOY_FILE = CONFIG_DIR / "envoy.md"
PROCESS_FILE = CONFIG_DIR / "process.md"
TEMPLATES_DIR = Path(__file__).parent / "templates"

console = Console()


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    val = input(f"  → {prompt}{suffix}: ").strip()
    return val or default


def _parse_phonetool(text: str, alias: str) -> dict:
    """Extract name, email, title from Phonetool page text."""
    info = {"alias": alias, "email": f"{alias}@amazon.com", "name": "", "title": ""}
    for line in text.split("\n"):
        line = line.strip()
        if ("Job Title:" in line or "Business Title:" in line) and not info["title"]:
            info["title"] = line.split(":", 1)[1].strip()
        elif line and not info["name"] and not line.startswith(("#", "[", "!", "|", "-", "*")):
            # First plain text line is usually the full name
            candidate = line.split("|")[0].strip()
            if candidate and len(candidate.split()) <= 5 and candidate[0].isupper():
                info["name"] = candidate
    return info


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
    if not SOUL_FILE.exists() or "<!-- " in _read_field(SOUL_FILE, "Agent name"):
        console.print("[yellow]No config found. Running full setup...[/yellow]\n")
        run_init()
        return

    console.print(Panel("⚙️  Envoy Settings", style="bold cyan"))

    fields = [
        (ENVOY_FILE,  "Name",       "Name"),
        (ENVOY_FILE,  "Role",       "Role"),
        (ENVOY_FILE,  "Manager",    "Manager"),
        (SOUL_FILE,   "Agent name", "Agent name"),
        (ENVOY_FILE,  "Signature",  "Signature"),
        (ENVOY_FILE,  "ea_alias",   "EA alias"),
        (ENVOY_FILE,  "ea_name",    "EA name"),
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
    console.print("[dim]  soul.md = agent identity  |  envoy.md = user context & prefs  |  process.md = learned patterns[/dim]\n")

    pick = _ask("Enter # to edit, 'soul' to regenerate soul.md, 'process' to view process.md, 'all' to re-run setup, or Enter to go back", "")
    if not pick:
        return
    if pick.lower() == "all":
        run_init()
        return
    if pick.lower() == "soul":
        _generate_soul_with_ai()
        return
    if pick.lower() == "process":
        if PROCESS_FILE.exists():
            console.print(Panel(PROCESS_FILE.read_text(), title="[bold]Process Memory[/bold]", border_style="dim"))
        else:
            console.print("[dim]No process memory yet. The agent will learn over time.[/dim]")
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
        soul_content = invoke_ai(prompt, max_tokens=2000, tier="medium")
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

    # Migrate old files if needed
    old_guidance = CONFIG_DIR / "guidance.md"
    if old_guidance.exists() and not SOUL_FILE.exists():
        old_guidance.rename(SOUL_FILE)
        console.print(f"[dim]Migrated guidance.md → soul.md[/dim]")

    # Copy templates as starting point for any missing files
    for filename in ("soul.md", "envoy.md", "process.md"):
        target = CONFIG_DIR / filename
        if not target.exists():
            src = TEMPLATES_DIR / filename
            if src.exists():
                shutil.copy(src, target)

    # Install bundled skills (don't overwrite user-modified ones)
    bundled_skills = TEMPLATES_DIR / "skills"
    user_skills = CONFIG_DIR / "skills"
    if bundled_skills.is_dir():
        user_skills.mkdir(exist_ok=True)
        for skill_dir in bundled_skills.iterdir():
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                target = user_skills / skill_dir.name
                if not target.exists():
                    shutil.copytree(skill_dir, target)

    console.print(Panel("🔏 Envoy Setup", style="bold cyan"))
    console.print("Let me learn about you so I can be a better assistant.\n")

    alias = _ask("Your alias", os.environ.get("USER", ""))

    # Try Phonetool lookup
    name, title, manager, directs = "", "", "", []
    try:
        console.print(f"[dim]Looking you up in Phonetool...[/dim]")
        import asyncio

        async def _lookup():
            async with builder() as session:
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
            dr = asyncio.run(people.get_direct_reports(alias))
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
    vips_raw = _ask("People whose emails should always be flagged high priority (aliases, comma-separated)", "")

    # Look up VIPs via Phonetool
    vip_entries = []
    if vips_raw:
        aliases_to_lookup = [a.strip() for a in vips_raw.split(",") if a.strip()]
        try:
            console.print(f"[dim]Looking up {len(aliases_to_lookup)} VIP(s) in Phonetool...[/dim]")
            import asyncio as _aio

            async def _lookup_vips():
                results = []
                async with builder() as session:
                    for a in aliases_to_lookup:
                        try:
                            res = await session.call_tool("ReadInternalWebsites",
                                arguments={"inputs": [f"https://phonetool.amazon.com/users/{a}"]})
                            text = str(res.content[0].text) if res.content else ""
                            results.append(_parse_phonetool(text, a))
                        except Exception:
                            results.append({"alias": a, "email": f"{a}@amazon.com", "name": "", "title": ""})
                return results

            vip_entries = _aio.run(_lookup_vips())
            for v in vip_entries:
                label = f"{v['name']} ({v['alias']})" if v["name"] else v["alias"]
                if v["title"]:
                    label += f" — {v['title']}"
                console.print(f"  ✓ {label}")
        except Exception:
            vip_entries = [{"alias": a, "email": f"{a}@amazon.com", "name": "", "title": ""}
                          for a in aliases_to_lookup]

    # --- Preferences ---
    console.print()
    console.print("[bold]Preferences[/bold]")
    ignore = _ask("Types of email to always ignore", "vendor marketing, cold outreach")
    fav_channels = _ask("Favorite Slack channels to monitor (comma-separated, or Enter to skip)", "")
    calendar_prefs = _ask("Calendar preferences (e.g., 'no meetings before 9am', 'block focus time')", "")

    console.print()
    console.print("[bold]Executive Assistant[/bold]")
    ea_alias = _ask("Your EA's login (leave blank if none)", "")
    ea_entry = None
    if ea_alias:
        try:
            console.print(f"[dim]Looking up {ea_alias} in Phonetool...[/dim]")
            import asyncio as _aio2

            async def _ea_lookup():
                async with builder() as session:
                    res = await session.call_tool("ReadInternalWebsites",
                        arguments={"inputs": [f"https://phonetool.amazon.com/users/{ea_alias}"]})
                    return str(res.content[0].text) if res.content else ""

            ea_entry = _parse_phonetool(_aio2.run(_ea_lookup()), ea_alias)
            if ea_entry["name"]:
                console.print(f"  Found: [bold]{ea_entry['name']}[/bold]")
        except Exception:
            ea_entry = {"alias": ea_alias, "email": f"{ea_alias}@amazon.com", "name": "", "title": ""}

    # --- Write envoy.md (user context + preferences) ---
    envoy = f"""# About Me

- Name: {name}
- Alias: {alias}
- Role: {title}
- Manager: {manager}
"""
    if directs:
        envoy += f"- Direct reports: {', '.join(directs)}\n"
    if priorities:
        envoy += f"\n# Priorities\n\n- {priorities.replace(', ', chr(10) + '- ')}\n"
    if vip_entries:
        envoy += "\n# High Priority People\n\n"
        for v in vip_entries:
            envoy += f"- {v['name'] or v['alias']} | {v['alias']} | {v['email']} | {v['title']}\n"
    envoy += f"\n# Preferences\n\n## Email\n- Ignore: {ignore}\n- KEEP by default — when in doubt, keep it\n"
    if vip_entries:
        envoy += f"- Always flag emails from: {', '.join(v['alias'] for v in vip_entries)}\n"
    if fav_channels:
        envoy += f"\n## Slack\n- Favorite channels: {fav_channels}\n"
    if calendar_prefs:
        envoy += f"\n## Calendar\n- {calendar_prefs}\n"
    if agent_sig:
        envoy += f"\n## Signature\n- {agent_sig}\n"
    if ea_entry:
        envoy += f"\n# Executive Assistant\n\n- {ea_entry['name'] or ea_alias} | {ea_entry['alias']} | {ea_entry['email']} | {ea_entry['title']}\n"

    ENVOY_FILE.write_text(envoy)
    console.print(f"\n[green]✓ Saved {ENVOY_FILE}[/green]")

    # --- Write soul.md (agent identity) or generate with AI ---
    console.print()
    gen_soul = _ask("Generate agent soul/personality with AI? (yes/no)", "no")
    if gen_soul.lower() in ("y", "yes"):
        _generate_soul_with_ai()
    else:
        # Update agent name in soul template
        if agent_name:
            _set_field(SOUL_FILE, "Agent name", agent_name)
        style = _ask("Summary style preference", "concise bullets, lead with action items")
        tone = _ask("Agent personality/tone", "friendly and professional")
        soul = f"""# Soul

I am your AI chief of staff — sharp, proactive, and always one step ahead.

# Personality & Tone

- {tone}

# Communication Style

- {style}

# Agent Identity

- Agent name: {agent_name or 'Envoy'}

# Behavioral Rules

- Always confirm before deleting emails or sending messages
- Be proactive with recommendations based on what I find
- When corrected, update the appropriate config file to remember
"""
        SOUL_FILE.write_text(soul)
        console.print(f"[green]✓ Saved {SOUL_FILE}[/green]")

    # Ensure process.md exists
    if not PROCESS_FILE.exists():
        src = TEMPLATES_DIR / "process.md"
        if src.exists():
            shutil.copy(src, PROCESS_FILE)
        console.print(f"[green]✓ Created {PROCESS_FILE}[/green]")

    console.print(f"\n[bold]Setup complete.[/bold] Edit files anytime, use /settings, or just tell me to adjust.\n")
