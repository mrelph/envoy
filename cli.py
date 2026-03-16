#!/usr/bin/env python3

import click
import os
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich import box
from service import AttacheService

console = Console()


@click.group(invoke_without_command=True)
@click.version_option(version='2.0.0')
@click.pass_context
def cli(ctx):
    """Attaché — AI-Powered Email Management"""
    if ctx.invoked_subcommand is None:
        from agent import run_interactive
        run_interactive()


@cli.command()
def init():
    """Set up Attaché — build your personality, soul, and preferences."""
    from init_cmd import run_init
    run_init()


@cli.command()
def settings():
    """Edit Attaché personality and config."""
    from init_cmd import run_settings
    run_settings()


@cli.command()
def menu():
    """Launch the classic menu-driven TUI."""
    _main_menu()


def _main_menu():
    """Interactive menu — delegates to agent mode for all features."""
    from agent import run_interactive
    run_interactive()


# --- CLI subcommands for automation/scripting ---

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
    if not alias:
        alias = os.environ.get('USER', '')

    selected_aliases = [s.strip() for s in select.split(',') if s.strip()] if select else None
    mode = "VIP management chain" if vip else "direct reports"
    console.print(f"[cyan]Generating {mode} digest for {alias} (last {days} days)...[/cyan]\n")

    try:
        service = AttacheService()

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
            task = progress.add_task("[cyan]Fetching emails...", total=None)
            raw = service.generate_digest(alias, days, selected_aliases, vip)
            if not no_ai:
                progress.update(task, description="[cyan]Generating AI summary...")
                final_output = service.generate_ai_summary(raw, alias, days)
            else:
                final_output = raw

        if output:
            with open(output, 'w') as f:
                f.write(final_output)
            console.print(f"[green]✓[/green] Written to {output}")

        if email:
            success = service.email_digest(final_output, alias, days, include_summary=not no_ai)
            console.print(f"[green]✓[/green] Emailed to {alias}@amazon.com" if success else "[red]✗[/red] Failed to email")

        if slack:
            result = service.send_slack_dm(alias, final_output)
            console.print(f"[green]✓[/green] Sent digest via Slack DM" if "✅" in result else f"[red]✗[/red] {result}")

        if todo and not no_ai:
            actions = service.extract_action_items(final_output)
            if actions:
                selected = _preview_and_select_actions(actions)
                if selected:
                    service.add_to_todo(selected)
                    console.print(f"[green]✓[/green] Added {len(selected)} items to To-Do")

        if not no_display:
            console.print('\n' + final_output)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        import traceback
        traceback.print_exc()
        raise click.Abort()


@cli.command()
@click.option('--days', '-d', default=14, help='Days to look back')
@click.option('--limit', '-l', default=100, help='Max emails to scan')
def cleanup(days, limit):
    """Scan inbox for non-critical email and facilitate deletion."""
    alias = os.environ.get('USER', '')
    service = AttacheService()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("[cyan]Scanning inbox...", total=None)
        emails = service.fetch_inbox_emails(days, limit)
        if not emails:
            console.print("[yellow]No emails found.[/yellow]")
            return
        progress.update(task, description=f"[cyan]Classifying {len(emails)} emails with AI...")
        emails = service.classify_emails(emails, alias)

    deletable = [e for e in emails if e['classification'] == 'DELETE']
    reviewable = [e for e in emails if e['classification'] == 'REVIEW']
    keepable = [e for e in emails if e['classification'] == 'KEEP']

    console.print(f"\n[bold]Scan Results:[/bold] {len(deletable)} DELETE · {len(reviewable)} REVIEW · {len(keepable)} KEEP\n")

    if deletable:
        console.print("[bold red]── Recommended for Deletion ──[/bold red]")
        _show_email_table(deletable, "red")
    if reviewable:
        console.print("\n[bold yellow]── Review Before Deleting ──[/bold yellow]")
        _show_email_table(reviewable, "yellow")

    if not deletable and not reviewable:
        console.print("[green]Your inbox looks clean![/green]")
        return

    candidates = deletable + reviewable
    selection = Prompt.ask(
        "\n[yellow]Enter numbers, 'delete' for all DELETE, 'all' for DELETE+REVIEW, or 'none'[/yellow]",
        default="delete"
    )

    if selection.lower() == 'none':
        return
    elif selection.lower() == 'all':
        to_delete = candidates
    elif selection.lower() == 'delete':
        to_delete = deletable
    else:
        indices = [int(x.strip()) - 1 for x in selection.split(',')]
        to_delete = [candidates[i] for i in indices if 0 <= i < len(candidates)]

    if not to_delete:
        return

    console.print(f"\n[bold]About to move {len(to_delete)} emails to Deleted Items:[/bold]")
    for e in to_delete:
        console.print(f"  [dim]•[/dim] {e['subject'][:80]} [dim]({e['from']})[/dim]")

    if not Confirm.ask(f"\n[red]Proceed?[/red]", default=False):
        return

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("[cyan]Deleting...", total=None)
        cids = [e['conversationId'] for e in to_delete if e.get('conversationId')]
        results = service.delete_emails(cids)

    console.print(f"[green]✓[/green] Deleted {results['deleted']} emails", end="")
    if results['failed']:
        console.print(f" [red]({results['failed']} failed)[/red]")
    else:
        console.print()


@cli.command()
@click.option('--alias', '-a', default=None, help='Your alias (defaults to $USER)')
@click.option('--days', '-d', default=14, help='Days to look back')
@click.option('--team', '-t', default=None, help='Comma-separated team aliases (or auto-fetches directs)')
@click.option('--output', '-o', default=None, help='Output file')
@click.option('--email', '-e', is_flag=True, help='Email report to yourself')
@click.option('--slack', is_flag=True, help='Send report as a Slack DM to yourself')
def customers(alias, days, team, output, email, slack):
    """Scan for external customer emails with action items."""
    if not alias:
        alias = os.environ.get('USER', '')

    service = AttacheService()
    team_aliases = [t.strip() for t in team.split(',') if t.strip()] if team else None

    # Auto-fetch directs if no team specified
    if team_aliases is None:
        import asyncio
        console.print(f"[cyan]Fetching direct reports for {alias}...[/cyan]")
        directs = asyncio.run(service.get_direct_reports(alias))
        team_aliases = [d['alias'] for d in directs]

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("[cyan]Scanning external customer emails...", total=None)
        report = service.scan_customer_emails(alias, days, team_aliases)

    if output:
        with open(output, 'w') as f:
            f.write(report)
        console.print(f"[green]✓[/green] Written to {output}")

    if email:
        success = service.email_digest(report, alias, days, include_summary=True)
        console.print(f"[green]✓[/green] Emailed" if success else "[red]✗[/red] Failed")

    if slack:
        result = service.send_slack_dm(alias, report)
        console.print(f"[green]✓[/green] Sent report via Slack DM" if "✅" in result else f"[red]✗[/red] {result}")

    console.print('\n' + report)


@cli.command()
@click.argument('action', default='list', type=click.Choice(['list', 'add', 'remove', 'presets']))
@click.option('--name', '-n', default='', help='Job name')
@click.option('--schedule', '-s', default='', help='Cron expression (e.g. "0 8 * * 1-5")')
@click.option('--command', '-c', 'cmd', default='', help='Attaché command (e.g. "digest --days 7 --email")')
def cron(action, name, schedule, cmd):
    """Manage Attaché scheduled cron jobs."""
    from tools import manage_cron
    result = manage_cron(action=action, name=name, schedule=schedule, command=cmd)
    from rich.markdown import Markdown
    console.print(Markdown(result))


@cli.command()
@click.option('--days', '-d', default=7, type=int, help='Days to look back')
@click.option('--channels', '-c', default=None, help='Comma-separated channel IDs')
@click.option('--output', '-o', default=None, help='Output file')
def slack(days, channels, output):
    """Scan Slack channels for critical info and action items."""
    service = AttacheService()
    ch_list = [c.strip() for c in channels.split(',') if c.strip()] if channels else None

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("[cyan]Scanning Slack channels...", total=None)
        report = service.scan_slack(ch_list, days)

    if output:
        with open(output, 'w') as f:
            f.write(report)
        console.print(f"[green]✓[/green] Written to {output}")

    console.print('\n' + report)


@cli.command()
@click.option('--view', '-v', default='day', type=click.Choice(['day', 'week']), help='day or week view')
@click.option('--days', '-d', default=5, type=int, help='Days ahead (for week view)')
@click.option('--output', '-o', default=None, help='Output file')
def calendar(view, days, output):
    """Review your calendar with AI briefing and email cross-references."""
    service = AttacheService()

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("[cyan]Reviewing calendar...", total=None)
        report = service.review_calendar(view, days_ahead=days)

    if output:
        with open(output, 'w') as f:
            f.write(report)
        console.print(f"[green]✓[/green] Written to {output}")

    console.print('\n' + report)


if __name__ == '__main__':
    cli()
