"""Envoy backup — snapshot user config, memory, and state to a timestamped archive."""
import os
import tarfile
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".envoy"
BACKUP_DIR = CONFIG_DIR / "backups"

# Files and dirs to back up (relative to ~/.envoy)
TARGETS = [
    "soul.md",
    "envoy.md",
    "process.md",
    ".env",
    "models.json",
    "sent.json",
    "memory",
    "skills",
]


def run_backup():
    """Create a .tar.gz snapshot of envoy user state."""
    from rich.console import Console
    console = Console()

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = BACKUP_DIR / f"envoy-backup-{ts}.tar.gz"

    count = 0
    with tarfile.open(archive_path, "w:gz") as tar:
        for target in TARGETS:
            full = CONFIG_DIR / target
            if full.exists():
                tar.add(full, arcname=target)
                count += 1

    if count == 0:
        console.print("[yellow]Nothing to back up — no config files found.[/yellow]")
        return None

    size_kb = archive_path.stat().st_size / 1024
    console.print(f"[green]✓[/green] Backed up {count} items → [bold]{archive_path.name}[/bold] ({size_kb:.0f} KB)")
    _prune_old_backups()
    return archive_path


def _prune_old_backups(keep=10):
    """Keep only the most recent N backups."""
    backups = sorted(BACKUP_DIR.glob("envoy-backup-*.tar.gz"), reverse=True)
    for old in backups[keep:]:
        old.unlink()


def list_backups():
    """List available backups."""
    from rich.console import Console
    console = Console()

    if not BACKUP_DIR.exists():
        console.print("[dim]No backups yet. Run [bold]/backup[/bold] to create one.[/dim]")
        return

    backups = sorted(BACKUP_DIR.glob("envoy-backup-*.tar.gz"), reverse=True)
    if not backups:
        console.print("[dim]No backups yet.[/dim]")
        return

    console.print(f"[bold]Backups[/bold] ({len(backups)}):")
    for b in backups:
        size_kb = b.stat().st_size / 1024
        console.print(f"  {b.name}  [dim]({size_kb:.0f} KB)[/dim]")


def restore_backup(name=None):
    """Restore from a backup archive."""
    from rich.console import Console
    console = Console()

    if not BACKUP_DIR.exists():
        console.print("[red]No backups found.[/red]")
        return

    if name:
        archive = BACKUP_DIR / name
    else:
        backups = sorted(BACKUP_DIR.glob("envoy-backup-*.tar.gz"), reverse=True)
        if not backups:
            console.print("[red]No backups found.[/red]")
            return
        archive = backups[0]

    if not archive.exists():
        console.print(f"[red]Backup not found: {archive.name}[/red]")
        return

    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(path=CONFIG_DIR)

    console.print(f"[green]✓[/green] Restored from [bold]{archive.name}[/bold]")
