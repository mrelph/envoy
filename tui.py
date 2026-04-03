"""Envoy — Textual TUI interface."""

import os
from datetime import datetime
from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Input, RichLog, Label
from textual.binding import Binding
from textual.worker import get_current_worker
from textual import work, on
from rich.markdown import Markdown
from rich.text import Text

from dispatch import COMMANDS, COMMAND_GROUPS, dispatch

CONFIG_DIR = Path.home() / ".envoy"
SOUL_FILE = CONFIG_DIR / "soul.md"
VERSION = (Path(__file__).parent / "VERSION").read_text().strip()

LOGO = r"""[bold cyan]
 ███████╗███╗   ██╗██╗   ██╗ ██████╗ ██╗   ██╗
 ██╔════╝████╗  ██║██║   ██║██╔═══██╗╚██╗ ██╔╝
 █████╗  ██╔██╗ ██║██║   ██║██║   ██║ ╚████╔╝
 ██╔══╝  ██║╚██╗██║╚██╗ ██╔╝██║   ██║  ╚██╔╝
 ███████╗██║ ╚████║ ╚████╔╝ ╚██████╔╝   ██║
 ╚══════╝╚═╝  ╚═══╝  ╚═══╝   ╚═════╝    ╚═╝[/bold cyan]
[dim]  ✈  Your AI Chief of Staff  ·  v{version}[/dim]"""

SPINNER_HINTS = {
    "email": "📧 Email", "inbox": "📧 Email", "digest": "📧 Email",
    "cleanup": "📧 Email", "customer": "📧 Email",
    "slack": "💬 Slack", "channel": "💬 Slack", "catchup": "💬 Slack",
    "calendar": "📅 Calendar", "meeting": "📅 Calendar", "schedule": "📅 Calendar",
    "book": "📅 Calendar", "findtime": "📅 Calendar",
    "todo": "✅ Productivity", "ticket": "✅ Productivity",
    "briefing": "📊 Briefing", "eod": "📊 Briefing", "weekly": "📊 Briefing",
    "phonetool": "🔎 Research", "kingpin": "🔎 Research", "wiki": "🔎 Research",
    "sharepoint": "📁 SharePoint", "onedrive": "📁 SharePoint",
    "prep": "🧩 Prep", "1on1": "🧩 Prep",
    "followup": "📬 Follow-up", "commitment": "📬 Commitments",
    "response": "📬 Response times", "cal-audit": "📊 Calendar audit",
}

BRAILLE_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _get_alias():
    try:
        for line in SOUL_FILE.read_text().splitlines():
            if line.strip().startswith("- Alias:"):
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return os.environ.get("USER", "")


def _get_hint(text: str) -> str:
    lower = text.lower()
    for kw, label in SPINNER_HINTS.items():
        if kw in lower:
            return label
    return "🤔 Thinking"


# ── Widgets ──────────────────────────────────────────────


class MCPBar(Static):
    """Live MCP connection status."""

    _content: Text = Text(" ◌ connecting…", style="dim italic")

    def render(self) -> Text:
        return self._content

    def on_mount(self) -> None:
        self.check()

    @work(thread=True, exclusive=True)
    def check(self) -> None:
        from ui import _check_mcp_servers
        status = _check_mcp_servers()
        t = Text(" ")
        for name, ok in status.items():
            t.append("● " if ok else "○ ", style="green" if ok else "red")
            t.append(name, style="" if ok else "dim")
            t.append("  ")
        self._content = t
        self.app.call_from_thread(self.refresh)


class Spinner(Static):
    """Animated braille spinner with hint text. Shows during agent work."""

    _frame: int = 0
    _hint: str = ""
    _timer = None

    def render(self) -> Text:
        if not self._hint:
            return Text("")
        char = BRAILLE_FRAMES[self._frame % len(BRAILLE_FRAMES)]
        t = Text(f"  {char} ", style="bold cyan")
        t.append(self._hint, style="dim italic")
        t.append("…")
        return t

    def start(self, hint: str) -> None:
        self._hint = hint
        self._frame = 0
        self.display = True
        self.refresh()
        if self._timer is None:
            self._timer = self.set_interval(0.1, self._tick)

    def stop(self) -> None:
        self._hint = ""
        self.display = False
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._frame += 1
        self.refresh()


class StatusBar(Static):
    """Bottom bar with alias, time, model, keybindings."""

    def render(self) -> Text:
        alias = _get_alias()
        now = datetime.now().strftime("%I:%M %p").lstrip("0")

        model = ""
        try:
            from agents.base import _load_models
            import re
            mid = _load_models().get("agent", "")
            m = re.search(r'claude-(?:\d+-\d+-)?(\w+)-?(\d+)?', mid)
            if m:
                name = m.group(1)
                ver = m.group(2) or ""
                model = f"{name} {ver}" if ver and len(ver) <= 2 else name
            elif "nova" in mid:
                m2 = re.search(r'nova-(\w+)', mid)
                model = f"nova {m2.group(1)}" if m2 else "nova"
            elif mid:
                model = mid.split(".")[-1][:15]
        except Exception:
            pass

        t = Text()
        t.append(f" {alias}", style="bold cyan")
        t.append(f"  {now}", style="dim")
        if model:
            t.append("  │  ", style="dim")
            t.append(f"🧠 {model}", style="italic")
        t.append("  │  ", style="dim")
        t.append("/help", style="bold green")
        t.append(" commands  ", style="dim")
        t.append("ctrl+c", style="bold")
        t.append(" quit", style="dim")
        return t

    def on_mount(self) -> None:
        self.set_interval(30, self.refresh)


# ── App ──────────────────────────────────────────────────


class EnvoyApp(App):
    """Envoy TUI."""

    CSS_PATH = "tui.css"
    TITLE = f"✈ Envoy v{VERSION}"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("f5", "refresh_mcp", "Refresh", show=False),
        Binding("escape", "focus_input", "", show=False),
    ]

    def __init__(self):
        super().__init__()
        self._agent = None

    def compose(self) -> ComposeResult:
        yield MCPBar(id="mcp-bar")
        yield RichLog(id="output", highlight=True, markup=True, wrap=True, max_lines=5000, auto_scroll=True)
        yield Spinner(id="spinner")
        with Horizontal(id="input-area"):
            yield Label("›", id="prompt-label")
            yield Input(placeholder="Type a command or chat naturally…", id="input")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        out = self.query_one("#output", RichLog)
        out.write(Text.from_markup(LOGO.format(version=VERSION)))
        out.write(Text())
        self.query_one("#spinner", Spinner).display = False
        self.query_one("#input", Input).focus()
        self._init_agent()

    @work(thread=True, exclusive=True, group="init")
    def _init_agent(self) -> None:
        from agent import create_agent
        self._agent = create_agent()
        name = "Envoy"
        try:
            from agents.base import agent_name
            name = agent_name()
        except Exception:
            pass
        self.app.call_from_thread(
            self.query_one("#output", RichLog).write,
            Text(f"  ✓ {name} ready\n", style="green"),
        )

    # ── Input handling ──

    @on(Input.Submitted, "#input")
    def _on_submit(self, event: Input.Submitted) -> None:
        raw = event.value.strip()
        if not raw:
            return
        event.input.value = ""
        out = self.query_one("#output", RichLog)

        # Echo user input
        t = Text()
        t.append(f"\n › ", style="bold cyan")
        t.append(raw, style="bold")
        out.write(t)

        # System commands
        cmd = raw.split()[0].lower() if raw.startswith("/") else None
        if cmd == "/help":
            self._show_help()
            return
        if cmd in ("/exit", "/quit") or raw.lower() in ("quit", "exit", "q"):
            self.exit()
            return
        if cmd == "/status":
            self.action_refresh_mcp()
            return
        if cmd == "/models":
            out.write(Text("  Use 'envoy --models' from CLI to edit models.", style="dim"))
            return
        if cmd == "/settings":
            out.write(Text("  Use 'envoy settings' from CLI to edit config.", style="dim"))
            return

        # Start animated spinner
        hint = _get_hint(raw)
        self.query_one("#spinner", Spinner).start(hint)
        self._run_command(raw, hint)

    @work(thread=True, exclusive=True, group="cmd")
    def _run_command(self, raw: str, hint: str) -> None:
        worker = get_current_worker()
        if self._agent is None:
            from agent import create_agent
            self._agent = create_agent()

        result, handled = dispatch(raw, self._agent)
        if worker.is_cancelled:
            return

        def _show():
            # Stop spinner
            self.query_one("#spinner", Spinner).stop()

            out = self.query_one("#output", RichLog)
            if not result:
                return
            text = str(result)
            if any(c in text for c in ("#", "**", "- ", "| ", "```")):
                try:
                    out.write(Text())
                    out.write(Markdown(text))
                    out.write(Text())
                except Exception:
                    out.write(Text(f"\n{text}\n"))
            else:
                out.write(Text(f"\n{text}\n"))

            # Toast notification
            self.notify(f"✓ {hint} done", timeout=3)

        self.app.call_from_thread(_show)

    # ── Helpers ──

    def _show_help(self) -> None:
        out = self.query_one("#output", RichLog)
        out.write(Text())
        for group_name, cmds in COMMAND_GROUPS:
            t = Text()
            t.append(f"  {group_name}\n", style="bold cyan")
            for cmd in cmds:
                entry = COMMANDS.get(cmd)
                desc = entry[0] if entry else ""
                t.append(f"    {cmd:22s}", style="green")
                t.append(f"{desc}\n", style="dim")
            out.write(t)

    def action_refresh_mcp(self) -> None:
        self.query_one("#spinner", Spinner).start("Refreshing MCP")
        self.query_one(MCPBar).check()

    def action_focus_input(self) -> None:
        self.query_one("#input", Input).focus()


def run_tui():
    """Launch the Textual TUI."""
    EnvoyApp().run()
