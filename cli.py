#!/usr/bin/env python3

import click
import os
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box
from cot_renderer import CoTRenderer
from envoy_logger import get_logger, LogEntry

console = Console()


def _toast(lines):
    """Render a toast-style notification panel for action confirmations."""
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


VERSION = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'VERSION')).read().strip()


@click.group(invoke_without_command=True)
@click.version_option(version=VERSION)
@click.option('--verbose', '-v', is_flag=True, default=False, help='Enable chain-of-thought verbose output')
@click.pass_context
def cli(ctx, verbose):
    """Envoy — Your AI Chief of Staff.

    Run with no arguments for the interactive REPL, or use subcommands:

    \b
      envoy                    Interactive chat + slash commands
      envoy digest --days 7    Team email digest
      envoy catchup --days 5   PTO catch-up report
      envoy cleanup            Inbox cleanup scan
      envoy customers          Customer email scan
      envoy followup           Unanswered sent emails
    """
    # Determine verbose state: flag OR ENVOY_VERBOSE env var
    env_verbose = os.environ.get('ENVOY_VERBOSE', '').strip().lower() in ('1', 'true')
    is_verbose = verbose or env_verbose

    # Initialize CoT renderer and register with logger
    renderer = CoTRenderer(console=console, enabled=is_verbose)
    logger = get_logger()
    logger.on_entry(renderer.on_log_entry)

    # Store on context for subcommands if needed
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = is_verbose
    ctx.obj['renderer'] = renderer

    if ctx.invoked_subcommand is None:
        from repl import run_interactive
        run_interactive()


@cli.command()
def init():
    """Set up Envoy — build your personality, soul, and preferences."""
    from init_cmd import run_init
    run_init()


@cli.command()
def settings():
    """Edit Envoy personality and config."""
    from init_cmd import run_settings
    run_settings()


@cli.command()
@click.option("--restore", "-r", default=None, help="Restore from a named backup")
@click.option("--list", "-l", "list_", is_flag=True, help="List available backups")
def backup(restore, list_):
    """Back up or restore Envoy config, memory, and state."""
    from backup import run_backup, list_backups, restore_backup
    if list_:
        list_backups()
    elif restore:
        restore_backup(restore)
    else:
        run_backup()


@cli.command()
def menu():
    """Launch the interactive REPL."""
    from repl import run_interactive
    run_interactive()


def parse_log_file(filepath: str) -> "list[LogEntry]":
    """Read a log file and return a list of LogEntry objects, skipping malformed lines."""
    import json as _json
    entries = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(LogEntry.from_json(line))
            except (ValueError, KeyError, TypeError):
                # Skip malformed lines
                continue
    return entries


@cli.command()
@click.option('--level', default=None, help='Filter by log level (DEBUG, INFO, WARNING, ERROR)')
@click.option('--type', 'event_type', default=None, help='Filter by event type')
@click.option('--tail', '-n', default=50, help='Number of entries to show')
@click.pass_context
def logs(ctx, level, event_type, tail):
    """View recent agent logs in a formatted table."""
    from datetime import datetime as _dt

    today = _dt.now().strftime("%Y-%m-%d")
    log_dir = os.path.expanduser("~/.envoy/logs/")
    log_path = os.path.join(log_dir, f"envoy-{today}.log")

    if not os.path.isfile(log_path):
        console.print("[yellow]No logs found for today.[/yellow]")
        return

    entries = parse_log_file(log_path)
    renderer = ctx.obj.get('renderer') if ctx.obj else None
    if renderer is None:
        renderer = CoTRenderer(console=console, enabled=False)

    renderer.render_logs_table(entries, level_filter=level, type_filter=event_type, tail=tail)


def _get_latest_tag(script_dir):
    """Fetch tags and return the latest semver tag (e.g. 'v2.1.0'), or None.
    Returns (tag, fetched_ok) tuple."""
    import subprocess
    fetch_result = subprocess.run(
        ['git', '-C', script_dir, 'fetch', '--tags', '--quiet'],
        capture_output=True
    )
    fetched_ok = fetch_result.returncode == 0
    result = subprocess.run(
        ['git', '-C', script_dir, 'tag', '-l', 'v*', '--sort=-version:refname'],
        capture_output=True, text=True
    )
    tags = result.stdout.strip().splitlines()
    tag = tags[0] if tags else None
    return tag, fetched_ok


def _parse_version(tag):
    """Parse 'v1.2.3' into (1, 2, 3) tuple for comparison."""
    import re
    m = re.match(r'v?(\d+)\.(\d+)\.(\d+)', tag)
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


@cli.command()
@click.option('--force', '-f', is_flag=True, help='Force update even if already up to date')
def update(force):
    """Update to the latest published release."""
    import subprocess

    script_dir = os.path.dirname(os.path.abspath(__file__))

    if not os.path.isdir(os.path.join(script_dir, '.git')):
        console.print("[red]Error:[/red] Not a git repository. Update requires a git clone install.")
        raise click.Abort()

    console.print("[cyan]Checking for published releases...[/cyan]")
    latest_tag, fetched_ok = _get_latest_tag(script_dir)
    if not fetched_ok:
        console.print("[yellow]Warning:[/yellow] Could not reach remote. Showing cached releases only.")

    if not latest_tag:
        console.print("[yellow]No published releases found.[/yellow]")
        return

    current = _parse_version(VERSION)
    latest = _parse_version(latest_tag)

    console.print(f"  Current version: [bold]v{VERSION}[/bold]")
    console.print(f"  Latest release:  [bold]{latest_tag}[/bold]")

    if current >= latest and not force:
        console.print("\n[green]Already on the latest release.[/green]")
        return

    # Show changelog between current and latest tag
    current_tag = f'v{VERSION}'
    log = subprocess.run(
        ['git', '-C', script_dir, 'log', '--oneline', f'{current_tag}..{latest_tag}'],
        capture_output=True, text=True
    ).stdout.strip()
    if log:
        console.print(f"\n[bold]Changes in {latest_tag}:[/bold]")
        for line in log.splitlines():
            console.print(f"  [dim]•[/dim] {line}")
        console.print()

    # Check for local changes that would block checkout
    status = subprocess.run(
        ['git', '-C', script_dir, 'status', '--porcelain'],
        capture_output=True, text=True
    ).stdout.strip()
    if status:
        console.print("[red]Error:[/red] You have local changes. Stash or commit them first.")
        console.print(f"[dim]{status}[/dim]")
        raise click.Abort()

    # Checkout the release tag on a named branch to avoid detached HEAD
    console.print(f"[cyan]Updating to {latest_tag}...[/cyan]")
    result = subprocess.run(
        ['git', '-C', script_dir, 'checkout', '-B', 'release', latest_tag],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        console.print(f"[red]Error:[/red] Failed to checkout {latest_tag}:\n{result.stderr}")
        raise click.Abort()
    console.print(f"[green]✓[/green] Updated to {latest_tag}")

    # Reinstall deps if requirements.txt changed between versions
    req_changed = subprocess.run(
        ['git', '-C', script_dir, 'diff', f'{current_tag}..{latest_tag}', '--name-only', '--', 'requirements.txt'],
        capture_output=True, text=True
    ).stdout.strip()
    if req_changed or force:
        console.print("[cyan]Reinstalling dependencies...[/cyan]")
        venv_pip = os.path.join(script_dir, 'venv', 'bin', 'pip')
        req_file = os.path.join(script_dir, 'requirements.txt')
        if os.path.isfile(venv_pip):
            subprocess.run([venv_pip, 'install', '-q', '-r', req_file], check=True)
            console.print("[green]✓[/green] Dependencies updated")
        else:
            console.print("[yellow]Warning:[/yellow] venv not found. Run envoy once to set up, then retry.")

    console.print(f"\n[bold green]Updated to {latest_tag}![/bold green]")


def _main_menu():
    """Interactive REPL — delegates to agent mode for all features."""
    from repl import run_interactive
    run_interactive()


# --- Command prompt loader ---

def _load_commands() -> dict:
    """Parse commands.md into {name: template} dict."""
    import re
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'commands.md')
    user_path = os.path.expanduser('~/.envoy/commands.md')
    # User overrides take precedence
    if os.path.exists(user_path):
        path = user_path
    with open(path) as f:
        text = f.read()
    commands = {}
    for block in re.split(r'\n## ', text):
        lines = block.strip().splitlines()
        if not lines:
            continue
        name = lines[0].strip().lower()
        body = '\n'.join(lines[1:]).strip()
        if body:
            commands[name] = body
    return commands


def _build_prompt(template: str, **kwargs) -> str:
    """Build an agent prompt from a command template, expanding {if flag} conditionals."""
    import re
    # Expand {if key} ... lines: keep line only if kwarg is truthy
    def _expand_if(m):
        key = m.group(1)
        rest = m.group(2).strip()
        val = kwargs.get(key)
        if val:
            # Substitute {key} in the rest of the line
            return rest.replace(f'{{{key}}}', str(val))
        return ''
    result = re.sub(r'\{if\s+(\w+)\}\s*(.*)', _expand_if, template)
    # Substitute remaining {key} placeholders
    for k, v in kwargs.items():
        result = result.replace(f'{{{k}}}', str(v) if v else '')
    # Clean up blank lines
    result = '\n'.join(line for line in result.splitlines() if line.strip())
    return result


def _run_agent_command(prompt: str, output: str = None, no_display: bool = False):
    """Run a prompt through the Strands agent and handle output/display."""
    from agent import create_agent
    from rich.markdown import Markdown

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        progress.add_task("[cyan]Working...", total=None)
        agent = create_agent()
        result = agent(prompt)

    response = result.message if hasattr(result, 'message') else str(result)

    if output:
        with open(output, 'w') as f:
            f.write(response)
        _toast([f"✓ Written to {output}"])

    if not no_display:
        console.print(Markdown(response))


# --- CLI subcommands (thin wrappers → agent prompts) ---

_CMDS = None
def _cmds():
    global _CMDS
    if _CMDS is None:
        _CMDS = _load_commands()
    return _CMDS


@cli.command()
@click.option('--alias', '-a', default=None, help='Manager alias (defaults to $USER)')
@click.option('--days', '-d', default=14, type=int, help='Days to look back')
@click.option('--select', '-s', default=None, help='Comma-separated aliases to include')
@click.option('--vip', is_flag=True, help='Track bosses instead of directs')
@click.option('--output', '-o', default=None, help='Output file')
@click.option('--email', '-e', is_flag=True, help='Email digest to yourself')
@click.option('--slack', is_flag=True, help='Send digest as a Slack DM to yourself')
@click.option('--todo', '-t', is_flag=True, help='Add action items to To-Do')
@click.option('--no-display', is_flag=True, help='Suppress console output')
@click.option('--no-ai', is_flag=True, help='Skip AI summary')
def digest(alias, days, select, vip, output, email, slack, todo, no_display, no_ai):
    """Generate team email digest."""
    alias = alias or os.environ.get('USER', '')
    prompt = _build_prompt(_cmds()['digest'], alias=alias, days=days,
                           vip=vip, select=select, email=email, slack=slack,
                           todo=todo, no_ai=no_ai)
    _run_agent_command(prompt, output=output, no_display=no_display)


@cli.command()
@click.option('--days', '-d', default=14, help='Days to look back')
@click.option('--limit', '-l', default=100, help='Max emails to scan')
def cleanup(days, limit):
    """Scan inbox for non-critical email and facilitate deletion."""
    prompt = _build_prompt(_cmds()['cleanup'], days=days, limit=limit)
    _run_agent_command(prompt)


@cli.command()
@click.option('--alias', '-a', default=None, help='Your alias (defaults to $USER)')
@click.option('--days', '-d', default=14, help='Days to look back')
@click.option('--team', '-t', default=None, help='Comma-separated team aliases')
@click.option('--output', '-o', default=None, help='Output file')
@click.option('--email', '-e', is_flag=True, help='Email report to yourself')
@click.option('--slack', is_flag=True, help='Send report as a Slack DM to yourself')
def customers(alias, days, team, output, email, slack):
    """Scan for external customer emails with action items."""
    alias = alias or os.environ.get('USER', '')
    prompt = _build_prompt(_cmds()['customers'], alias=alias, days=days,
                           team=team, email=email, slack=slack)
    _run_agent_command(prompt, output=output)


@cli.command()
@click.argument('action', default='list', type=click.Choice(['list', 'add', 'remove', 'presets']))
@click.option('--name', '-n', default='', help='Job name')
@click.option('--schedule', '-s', default='', help='Cron expression (e.g. "0 8 * * 1-5")')
@click.option('--command', '-c', 'cmd', default='', help='Envoy command (e.g. "digest --days 7 --email")')
def cron(action, name, schedule, cmd):
    """Manage Envoy scheduled cron jobs."""
    from tools import manage_cron
    result = manage_cron(action=action, name=name, schedule=schedule, command=cmd)
    from rich.markdown import Markdown
    console.print(Markdown(result))


@cli.command()
@click.option('--days', '-d', default=5, type=int, help='Days you were out')
def catchup(days):
    """PTO catch-up — comprehensive report of what you missed."""
    _run_agent_command(_build_prompt(_cmds()['catchup'], days=days))


@cli.command()
@click.option('--days', '-d', default=3, type=int, help='Days to look back')
def slack_catchup(days):
    """Focused Slack catch-up — unread channels, @mentions, DMs."""
    _run_agent_command(_build_prompt(_cmds()['slack-catchup'], days=days))


@cli.command()
@click.option('--days', '-d', default=1, type=int, help='Days to look back')
def yesterbox(days):
    """Yesterbox — yesterday's direct messages, prioritized with action items."""
    _run_agent_command(_build_prompt(_cmds()['yesterbox'], days=days))


@cli.command()
@click.option('--days', '-d', default=5, type=int, help='Days ahead to analyze')
def cal_audit(days):
    """Audit your calendar — meeting load, focus time, optimization."""
    _run_agent_command(_build_prompt(_cmds()['cal-audit'], days=days))


@cli.command()
@click.option('--days', '-d', default=7, type=int, help='Days to analyze')
def response_times(days):
    """Analyze email response time patterns."""
    _run_agent_command(_build_prompt(_cmds()['response-times'], days=days))


@cli.command()
@click.option('--days', '-d', default=7, type=int, help='Days to look back')
def followup(days):
    """Scan sent emails for unanswered threads."""
    _run_agent_command(_build_prompt(_cmds()['followup'], days=days))


@cli.command()
@click.argument('person')
def prep_1on1(person):
    """Generate a 1:1 prep brief for a meeting with PERSON (alias)."""
    _run_agent_command(_build_prompt(_cmds()['prep-1on1'], person=person))


@cli.command()
@click.option('--days', '-d', default=7, type=int, help='Days to look back')
def commitments(days):
    """Scan sent messages for commitments and promises you made."""
    _run_agent_command(_build_prompt(_cmds()['commitments'], days=days))


@cli.command()
@click.option('--meeting', '-m', default='', help='Meeting subject to prep for (empty = next meeting)')
def prep_meeting(meeting):
    """Generate a prep brief for an upcoming meeting."""
    _run_agent_command(_build_prompt(_cmds()['prep-meeting'], meeting=meeting))


@cli.command()
@click.option('--quiet', '-q', is_flag=True, help='Suppress console output')
@click.option('--notify', '-n', default='slack', type=click.Choice(['slack', 'email', 'none']), help='Notification method')
def heartbeat(quiet, notify):
    """Autonomous heartbeat — check routines and alert on important items."""
    from agents.heartbeat import run_heartbeat
    run_heartbeat(quiet=quiet, notify=notify if notify != 'none' else None)


@cli.command()
@click.argument('action', default='list', type=click.Choice(['list', 'add', 'remove', 'suggest']))
@click.option('--order', '-o', default='', help='Routine text (for add/remove)')
def routine(action, order):
    """Manage heartbeat routines."""
    from agents.heartbeat import get_routines, add_routine, remove_routine, suggest_routines
    from rich.markdown import Markdown
    if action == 'list':
        console.print(Markdown(get_routines()))
    elif action == 'add':
        if not order:
            order = click.prompt("Routine")
        console.print(add_routine(order))
    elif action == 'remove':
        if not order:
            order = click.prompt("Text to match")
        console.print(remove_routine(order))
    elif action == 'suggest':
        console.print(Markdown(suggest_routines()))


if __name__ == '__main__':
    cli()
