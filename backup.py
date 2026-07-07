"""Envoy backup — snapshot user config, memory, and state to a timestamped archive."""
import os
import tarfile
from datetime import datetime
from pathlib import Path

CONFIG_DIR = Path.home() / ".envoy"
BACKUP_DIR = CONFIG_DIR / "backups"

# Files and dirs to back up (relative to ~/.envoy)
# NOTE: ".env" is intentionally excluded — it holds AWS/API credentials and
# should never be duplicated into a backup archive (PROJECT-REVIEW H3).
TARGETS = [
    "soul.md",
    "envoy.md",
    "process.md",
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

    try:
        os.chmod(archive_path, 0o600)
    except OSError:
        pass

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


def _safe_members(tar, base):
    """Return archive members that resolve inside `base`, skipping (and
    warning about) any whose path would escape it (traversal, absolute
    paths, symlink shenanigans, etc.)."""
    from rich.console import Console
    console = Console()

    safe = []
    for member in tar.getmembers():
        resolved = (base / member.name).resolve()
        try:
            resolved.relative_to(base)
        except ValueError:
            console.print(f"[yellow]⚠ Skipping unsafe archive member: {member.name}[/yellow]")
            continue
        safe.append(member)
    return safe


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

    base = CONFIG_DIR.resolve()
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=CONFIG_DIR, filter="data")
    except TypeError:
        # Python < 3.12 (pre-PEP 706 backport): no `filter` kwarg — reopen
        # fresh (streaming tars can't be re-extracted mid-stream) and reject
        # any member whose resolved path escapes CONFIG_DIR by hand.
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=CONFIG_DIR, members=_safe_members(tar, base))
    except tarfile.FilterError as e:
        # `filter="data"` itself rejected an unsafe member (path traversal,
        # absolute path, symlink escape, etc.) — reopen fresh and salvage the
        # safe members instead of aborting the whole restore.
        console.print(f"[yellow]⚠ Archive contained an unsafe member ({e}); extracting only safe members.[/yellow]")
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(path=CONFIG_DIR, members=_safe_members(tar, base))

    console.print(f"[green]✓[/green] Restored from [bold]{archive.name}[/bold]")
