"""Chain-of-thought CLI renderer for the Envoy agent framework."""

from rich.console import Console
from rich.table import Table
from rich import box

from envoy_logger import LogEntry, _LEVEL_ORDER

# Reasoning event types that the renderer cares about
_REASONING_EVENTS = {"reasoning_start", "reasoning_step", "reasoning_end"}


class CoTRenderer:
    """Renders chain-of-thought reasoning steps to the Rich console.

    Register via ``EnvoyLogger.on_entry()`` to receive log entries in real time.
    Only reasoning events are rendered, and only when verbose mode is enabled.
    """

    def __init__(self, console: Console, enabled: bool = False):
        self.console = console
        self.enabled = enabled  # verbose mode — kept for logs table
        self.show_teasers = True  # always show brief worker teasers
        self._step_counter = 0

    def on_log_entry(self, entry: LogEntry):
        """Callback registered with EnvoyLogger.on_entry().

        Always shows brief teasers for reasoning steps.
        Full verbose output only when enabled.
        """
        if entry.event_type not in _REASONING_EVENTS:
            return
        if entry.event_type == "reasoning_step" and self.show_teasers:
            self.render_step(entry)
        elif self.enabled:
            self.render_step(entry)

    def render_step(self, entry: LogEntry):
        """Display a single reasoning step as a brief teaser."""
        if entry.event_type == "reasoning_start":
            self._step_counter = 0
        elif entry.event_type == "reasoning_step":
            self._step_counter += 1
            self.console.print(f"  [dim]  → {entry.message}[/dim]")
        elif entry.event_type == "reasoning_end":
            pass  # spinner handles the "done" state

    def render_logs_table(
        self,
        entries: "list[LogEntry]",
        level_filter: str = None,
        type_filter: str = None,
        tail: int = None,
    ):
        """Render log entries as a color-coded Rich table for ``envoy logs``."""
        # Level filter: keep entries at or above the specified level
        if level_filter is not None:
            min_severity = _LEVEL_ORDER.get(level_filter.upper(), 0)
            entries = [
                e for e in entries
                if _LEVEL_ORDER.get(e.level.upper(), 0) >= min_severity
            ]

        # Event type filter: exact match
        if type_filter is not None:
            entries = [e for e in entries if e.event_type == type_filter]

        # Tail filter: last N entries
        if tail is not None and tail >= 0:
            entries = entries[-tail:] if tail > 0 else []

        _LEVEL_STYLES = {
            "ERROR": "red",
            "WARNING": "yellow",
            "INFO": "green",
            "DEBUG": "dim",
        }

        table = Table(box=box.SIMPLE)
        table.add_column("Timestamp")
        table.add_column("Level")
        table.add_column("Event Type")
        table.add_column("Message")

        for entry in entries:
            style = _LEVEL_STYLES.get(entry.level.upper(), "")
            table.add_row(
                entry.timestamp,
                entry.level,
                entry.event_type,
                entry.message,
                style=style,
            )

        self.console.print(table)
