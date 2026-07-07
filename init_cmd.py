"""Envoy init — interactive setup that builds soul.md and envoy.md."""
import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from agents.base import invoke_ai, builder, run
from agents import people

CONFIG_DIR = Path.home() / ".envoy"
SOUL_FILE = CONFIG_DIR / "soul.md"
ENVOY_FILE = CONFIG_DIR / "envoy.md"
PROCESS_FILE = CONFIG_DIR / "process.md"
TEMPLATES_DIR = Path(__file__).parent / "templates"

console = Console()


def _secure_dir(path: Path):
    """Best-effort lock down a config directory to owner-only (0700)."""
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def _secure_file(path: Path):
    """Best-effort lock down a config file that may hold secrets/PII to 0600."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _backup_before_overwrite(path: Path) -> Optional[Path]:
    """If `path` already has real (non-template-placeholder) content, copy it
    to a timestamped sibling before it gets overwritten. Returns the backup
    path, or None if there was nothing worth backing up."""
    if not path.exists():
        return None
    try:
        if not path.read_text().strip():
            return None
    except OSError:
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{ts}")
    try:
        shutil.copy(path, backup_path)
    except OSError:
        return None
    _secure_file(backup_path)
    return backup_path


def _read_vip_aliases(filepath: Path) -> str:
    """Pull the comma-separated alias list back out of the '# High Priority
    People' section of an existing envoy.md, so re-running init can prefill it."""
    if not filepath.exists():
        return ""
    try:
        text = filepath.read_text()
    except OSError:
        return ""
    in_section = False
    aliases = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            in_section = stripped == "# High Priority People"
            continue
        if in_section and stripped.startswith("-"):
            parts = [p.strip() for p in stripped.lstrip("- ").split("|")]
            if len(parts) >= 2 and parts[1]:
                aliases.append(parts[1])
    return ", ".join(aliases)


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
        _secure_file(filepath)
        return
    lines = filepath.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith(f"- {key}:"):
            lines[i] = f"- {key}: {value}"
            filepath.write_text("\n".join(lines) + "\n")
            _secure_file(filepath)
            return
    # Not found — append under a sensible header
    lines.append(f"- {key}: {value}")
    filepath.write_text("\n".join(lines) + "\n")
    _secure_file(filepath)


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
        (ENVOY_FILE,  "ea_alias",          "EA alias"),
        (ENVOY_FILE,  "ea_name",            "EA name"),
        (ENVOY_FILE,  "Knowledge Folder",   "Knowledge Folder"),
        (ENVOY_FILE,  "Exports Folder",     "Exports Folder"),
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
            backup_path = _backup_before_overwrite(SOUL_FILE)
            SOUL_FILE.write_text(soul_content.strip() + "\n")
            _secure_file(SOUL_FILE)
            console.print(f"[green]✓ Saved {SOUL_FILE}[/green]")
            if backup_path:
                console.print(f"[dim]  Previous soul.md backed up to {backup_path}[/dim]")
        elif choice.lower() in ("e", "edit"):
            backup_path = _backup_before_overwrite(SOUL_FILE)
            SOUL_FILE.write_text(soul_content.strip() + "\n")
            _secure_file(SOUL_FILE)
            console.print(f"[green]✓ Saved {SOUL_FILE}[/green] — edit it at {SOUL_FILE}")
            if backup_path:
                console.print(f"[dim]  Previous soul.md backed up to {backup_path}[/dim]")
        else:
            console.print("[dim]Discarded.[/dim]")
    except Exception as e:
        console.print(f"[red]AI generation failed: {e}[/red]")
        console.print("[dim]You can write soul.md manually instead.[/dim]")


def run_init():
    CONFIG_DIR.mkdir(mode=0o700, exist_ok=True)
    _secure_dir(CONFIG_DIR)  # belt-and-suspenders: mkdir's mode is subject to umask

    # Detect a genuine re-run (existing, non-empty config) before we touch anything,
    # so we know whether to prefill prompts / mention the auto-backup.
    is_rerun = ENVOY_FILE.exists() and bool(ENVOY_FILE.read_text().strip())

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
                _secure_file(target)

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
    if is_rerun:
        console.print(
            "[dim]Existing config found — name, alias, and VIP list are prefilled below; "
            "your previous envoy.md/soul.md will be backed up automatically before they're "
            "overwritten. Other fields are not prefilled — re-enter them or edit the files "
            "directly afterwards.[/dim]\n"
        )

    alias = _ask("Your alias", _read_field(ENVOY_FILE, "Alias") or os.environ.get("USER", ""))

    # Try Phonetool lookup (prefill from existing config as a fallback default)
    name = _read_field(ENVOY_FILE, "Name")
    title = _read_field(ENVOY_FILE, "Role")
    manager = _read_field(ENVOY_FILE, "Manager")
    directs = []
    try:
        console.print(f"[dim]Looking you up in Phonetool...[/dim]")

        async def _lookup():
            async with builder() as session:
                result = await session.call_tool(
                    "ReadInternalWebsites",
                    arguments={"inputs": [f"https://phonetool.amazon.com/users/{alias}"]}
                )
                return str(result.content[0].text) if result.content else ""

        pt_text = run(_lookup())
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
            dr = run(people.get_direct_reports(alias))
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
    vips_raw = _ask("People whose emails should always be flagged high priority (aliases, comma-separated)",
                     _read_vip_aliases(ENVOY_FILE))

    # Look up VIPs via Phonetool
    vip_entries = []
    if vips_raw:
        aliases_to_lookup = [a.strip() for a in vips_raw.split(",") if a.strip()]
        try:
            console.print(f"[dim]Looking up {len(aliases_to_lookup)} VIP(s) in Phonetool...[/dim]")

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

            vip_entries = run(_lookup_vips())
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
    console.print("[bold]SharePoint / OneDrive[/bold]")
    console.print("[dim]  Envoy can read from a knowledge folder and save exports to a folder on your OneDrive.[/dim]")
    knowledge_folder = _ask("Knowledge folder path (e.g., 'Documents/Knowledge' or Enter to skip)", "")
    exports_folder = _ask("Exports folder path (e.g., 'Documents/Envoy Exports' or Enter to skip)", "")

    console.print()
    console.print("[bold]Executive Assistant[/bold]")
    ea_alias = _ask("Your EA's login (leave blank if none)", "")
    ea_entry = None
    if ea_alias:
        try:
            console.print(f"[dim]Looking up {ea_alias} in Phonetool...[/dim]")

            async def _ea_lookup():
                async with builder() as session:
                    res = await session.call_tool("ReadInternalWebsites",
                        arguments={"inputs": [f"https://phonetool.amazon.com/users/{ea_alias}"]})
                    return str(res.content[0].text) if res.content else ""

            ea_entry = _parse_phonetool(run(_ea_lookup()), ea_alias)
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
    if knowledge_folder or exports_folder:
        envoy += "\n## SharePoint / OneDrive\n"
        if knowledge_folder:
            envoy += f"- Knowledge Folder: {knowledge_folder}\n"
        if exports_folder:
            envoy += f"- Exports Folder: {exports_folder}\n"
    if ea_entry:
        envoy += f"\n# Executive Assistant\n\n- {ea_entry['name'] or ea_alias} | {ea_entry['alias']} | {ea_entry['email']} | {ea_entry['title']}\n"

    envoy_backup = _backup_before_overwrite(ENVOY_FILE)
    ENVOY_FILE.write_text(envoy)
    _secure_file(ENVOY_FILE)
    console.print(f"\n[green]✓ Saved {ENVOY_FILE}[/green]")
    if envoy_backup:
        console.print(f"[dim]  Previous config backed up to {envoy_backup}[/dim]")

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
        soul_backup = _backup_before_overwrite(SOUL_FILE)
        SOUL_FILE.write_text(soul)
        _secure_file(SOUL_FILE)
        console.print(f"[green]✓ Saved {SOUL_FILE}[/green]")
        if soul_backup:
            console.print(f"[dim]  Previous config backed up to {soul_backup}[/dim]")

    # Ensure process.md exists
    if not PROCESS_FILE.exists():
        src = TEMPLATES_DIR / "process.md"
        if src.exists():
            shutil.copy(src, PROCESS_FILE)
            _secure_file(PROCESS_FILE)
        console.print(f"[green]✓ Created {PROCESS_FILE}[/green]")

    console.print(f"\n[bold]Setup complete.[/bold] Edit files anytime, use /settings, or just tell me to adjust.\n")


# --- MCP server management ---

_MCP_JSON = CONFIG_DIR / "mcp.json"


def _load_user_mcps() -> dict:
    if _MCP_JSON.exists():
        return json.loads(_MCP_JSON.read_text())
    return {}


def _save_user_mcps(data: dict):
    CONFIG_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    _secure_dir(CONFIG_DIR)
    _MCP_JSON.write_text(json.dumps(data, indent=2) + "\n")
    _secure_file(_MCP_JSON)


def run_mcp(arg: str) -> str:
    """Manage MCP servers: add, remove, list."""
    parts = arg.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub == "add":
        return _mcp_add(rest)
    elif sub == "remove":
        return _mcp_remove(rest)
    elif sub == "list" or not sub:
        return _mcp_list()
    else:
        return "Usage: /mcp [list | add <name> <command> [args...] | remove <name>]"


def _mcp_list() -> str:
    from agents.base import _MCP_PARAM_DEFS
    lines = ["**MCP Servers**\n"]
    user_mcps = _load_user_mcps()
    for name, defn in sorted(_MCP_PARAM_DEFS.items()):
        src = "user" if name in user_mcps else "built-in"
        cmd = defn["command"]
        args = " ".join(defn.get("args", []))
        lines.append(f"- **{name}** ({src}): `{cmd} {args}`".rstrip())
    lines.append(f"\nConfig: `{_MCP_JSON}`")
    return "\n".join(lines)


def _mcp_add(rest: str) -> str:
    if not rest:
        return "Usage: /mcp add <name> <command> [args...]\nExample: /mcp add MyServer my-mcp-server --port 3000"
    tokens = rest.split()
    name = tokens[0]
    if len(tokens) < 2:
        return "Need at least a name and command. Example: /mcp add MyServer my-mcp-server"
    command = tokens[1]
    args = tokens[2:]
    user_mcps = _load_user_mcps()
    user_mcps[name] = {"command": command, "args": args}
    _save_user_mcps(user_mcps)
    # Hot-reload into running config
    from agents.base import _MCP_PARAM_DEFS, _mcp_params_cache
    _MCP_PARAM_DEFS[name] = {"command": command, "args": args}
    _mcp_params_cache.pop(name, None)
    return f"✅ Added MCP server **{name}**: `{command} {' '.join(args)}`\nSaved to `{_MCP_JSON}`. Active on next connection."


def _mcp_remove(name: str) -> str:
    if not name:
        return "Usage: /mcp remove <name>"
    user_mcps = _load_user_mcps()
    if name not in user_mcps:
        return f"⚠️ **{name}** is not in your user config (`{_MCP_JSON}`). Only user-added servers can be removed."
    del user_mcps[name]
    _save_user_mcps(user_mcps)
    from agents.base import _MCP_PARAM_DEFS, _mcp_params_cache
    _MCP_PARAM_DEFS.pop(name, None)
    _mcp_params_cache.pop(name, None)
    return f"✅ Removed MCP server **{name}** from `{_MCP_JSON}`."
