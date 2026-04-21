"""Envoy — Textual TUI interface."""

import os
from datetime import datetime
from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static, Input, RichLog, Label, TextArea
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
[dim]  Your AI Chief of Staff  ·  v{version}[/dim]"""

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

_FLAVOR = [
    "Brewing insights",
    "Connecting dots",
    "Reading between the lines",
    "Crunching context",
    "Herding electrons",
    "Consulting the oracle",
    "Sifting signal from noise",
    "Warming up the neurons",
    "Doing the needful",
    "Asking nicely",
    "Pulling strings",
    "Shaking the magic 8-ball",
    "Channeling your chief of staff energy",
    "Cross-referencing everything",
    "Making it look easy",
    "Thinking harder than usual",
    "Almost there, probably",
    "Summoning the cloud spirits",
]


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
    _flavor_idx: int = 0
    _timer = None

    def render(self) -> Text:
        if not self._hint:
            return Text("")
        char = BRAILLE_FRAMES[self._frame % len(BRAILLE_FRAMES)]
        flavor = _FLAVOR[self._flavor_idx % len(_FLAVOR)]
        t = Text(f"  {char} ", style="bold cyan")
        t.append(self._hint, style="dim italic")
        t.append(f"  ·  {flavor}…", style="dim")
        return t

    def start(self, hint: str) -> None:
        import random
        self._hint = hint
        self._frame = 0
        self._flavor_idx = random.randint(0, len(_FLAVOR) - 1)
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
        if self._frame % 20 == 0:  # rotate flavor every ~2s
            self._flavor_idx += 1
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
    TITLE = f"Envoy v{VERSION}"

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("f5", "refresh_mcp", "Refresh", show=False),
        Binding("escape", "focus_input", "", show=False),
    ]

    def __init__(self):
        super().__init__()
        self._agent = None
        self._pending_prompt = None  # e.g. "models" → next input is interpreted as /models <args>
        self._busy = False  # True while a command is in flight (prevents concurrent agent calls)

    def compose(self) -> ComposeResult:
        yield MCPBar(id="mcp-bar")
        yield RichLog(id="output", highlight=True, markup=True, wrap=True, max_lines=5000, auto_scroll=True)
        yield Spinner(id="spinner")
        with Horizontal(id="input-area"):
            yield Label("›", id="prompt-label")
            yield TextArea(id="input", language=None, soft_wrap=True, show_line_numbers=False)
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        out = self.query_one("#output", RichLog)
        out.write(Text.from_markup(LOGO.format(version=VERSION)))
        out.write(Text())
        self.query_one("#spinner", Spinner).display = False
        self.query_one("#input", TextArea).focus()
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

    def on_click(self) -> None:
        self.query_one("#input", TextArea).focus()

    # ── Input handling ──

    @on(TextArea.Changed, "#input")
    def _on_input_changed(self, event: TextArea.Changed) -> None:
        """Submit on Enter (newline). Shift+Enter for actual newline."""
        ta = event.text_area
        text = ta.text
        if text.endswith("\n"):
            raw = text.rstrip("\n")
            if not raw:
                ta.clear()
                return
            ta.clear()
            self._submit(raw)

    def _submit(self, raw: str) -> None:
        out = self.query_one("#output", RichLog)

        # Echo user input
        t = Text()
        t.append(f"\n › ", style="bold cyan")
        t.append(raw, style="bold")
        out.write(t)

        # Reject new input while a previous request is still running
        if self._busy:
            out.write(Text("  ⏳ Still working on your last request — wait for it to finish (or ctrl+c to quit).", style="yellow"))
            return

        # If we're awaiting a follow-up answer (e.g. after /models), rewrite the input
        if self._pending_prompt == "models":
            lower = raw.strip().lower()
            if lower in ("", "cancel", "q", "quit", "exit"):
                self._pending_prompt = None
                out.write(Text("  Cancelled.", style="dim"))
                return
            raw = f"/models {raw.strip()}"
            # Fall through to normal dispatch below; clear flag unless user stays in picker
            self._pending_prompt = None

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
        if cmd == "/mwinit":
            self._run_mwinit()
            return
        if cmd == "/settings":
            out.write(Text("  Use 'envoy settings' from CLI to edit config.", style="dim"))
            return

        # After a bare `/models`, arm follow-up so the next input is treated as args
        bare_models = (cmd == "/models" and not raw.split()[1:])

        # Start animated spinner
        hint = _get_hint(raw)
        self.query_one("#spinner", Spinner).start(hint)
        if bare_models:
            self._pending_prompt = "models"
        self._busy = True
        self._run_command(raw, hint)

    @work(thread=True, exclusive=True, group="cmd")
    def _run_command(self, raw: str, hint: str) -> None:
        worker = get_current_worker()
        if self._agent is None:
            from agent import create_agent
            self._agent = create_agent()

        error = None
        result = None
        handled = True
        try:
            result, handled = dispatch(raw, self._agent)
        except Exception as e:
            error = e
        if worker.is_cancelled:
            self._busy = False
            return

        # Log to observer learning loop
        try:
            from agents.observer import observe, maybe_analyze
            observe(raw[:300], str(result)[:300] if result else "", domain="command")
            maybe_analyze()
        except Exception:
            pass

        def _show():
            # Stop spinner
            self.query_one("#spinner", Spinner).stop()
            self._busy = False

            out = self.query_one("#output", RichLog)
            if error is not None:
                msg = str(error)
                if "Concurrent invocations" in msg or "ConcurrencyException" in type(error).__name__:
                    out.write(Text("  ⚠️  Agent was still busy. Try again in a moment.", style="yellow"))
                else:
                    out.write(Text(f"\n  ⚠️  {type(error).__name__}: {msg}\n", style="red"))
                return
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

    def _run_mwinit(self) -> None:
        import subprocess
        out = self.query_one("#output", RichLog)
        out.write(Text("  Launching mwinit — check your browser…", style="dim"))

        def _do_mwinit():
            with self.suspend():
                subprocess.run(["mwinit", "-o"])
            # Reconnect MCP sessions with fresh creds
            from agents.base import _persistent
            _persistent.clear()
            self.action_refresh_mcp()
            self.notify("✓ Midway refreshed", timeout=3)

        self.call_later(_do_mwinit)

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
        self.query_one("#input", TextArea).focus()


def run_tui():
    """Launch the Textual TUI."""
    EnvoyApp().run()
