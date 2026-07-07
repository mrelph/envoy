"""Envoy — Textual TUI interface."""

import os
from datetime import datetime
from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, Input, RichLog, Label, TextArea, OptionList
from textual.widgets.option_list import Option, Separator
from textual.binding import Binding
from textual.worker import get_current_worker
from textual import events, work, on
from rich.markdown import Markdown
from rich.text import Text

from dispatch import COMMANDS, COMMAND_GROUPS, dispatch_with_learning as dispatch

CONFIG_DIR = Path.home() / ".envoy"
SOUL_FILE = CONFIG_DIR / "soul.md"
VERSION = (Path(__file__).parent / "VERSION").read_text().strip()

LOGO = r"""[bold #58a6ff]
  ╭──────────────────────────────────────╮
  │                                      │
  │    E N V O Y                         │
  │                                      │
  │    [dim #8b949e]Your AI Chief of Staff[/dim #8b949e]            │
  │    [dim #484f58]v{version}[/dim #484f58]                            │
  │                                      │
  ╰──────────────────────────────────────╯[/bold #58a6ff]"""

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
        t = Text(" Envoy  ", style="bold #58a6ff")
        t.append("│ ", style="#30363d")
        for name, ok in status.items():
            t.append("● " if ok else "○ ", style="#3fb950" if ok else "#f85149")
            t.append(name, style="#e6edf3" if ok else "#484f58")
            t.append("  ")
        self._content = t

        def _done() -> None:
            self.refresh()
            # Stop the global spinner /status and F5 (action_refresh_mcp) start —
            # otherwise it spins forever once the check completes.
            try:
                self.app.query_one("#spinner", Spinner).stop()
            except Exception:
                pass

        self.app.call_from_thread(_done)


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
        t = Text(f"  {char} ", style="bold #58a6ff")
        t.append(self._hint, style="#8b949e italic")
        t.append(f"  ·  {flavor}…", style="#484f58")
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

        # Get session stats from app
        ttft_ms = None
        session_tokens = 0
        try:
            app = self.app
            ttft_ms = app._last_ttft_ms
            session_tokens = app._session_tokens
        except Exception:
            pass

        sep = "  ·  "
        t = Text()
        t.append(f" {alias}", style="bold #58a6ff")
        t.append(sep, style="#30363d")
        t.append(now, style="#8b949e")
        if model:
            t.append(sep, style="#30363d")
            t.append(f"⚡ {model}", style="#d2a8ff")
        if ttft_ms is not None:
            t.append(sep, style="#30363d")
            if ttft_ms >= 1000:
                t.append(f"{ttft_ms / 1000:.1f}s", style="#d29922")
            else:
                t.append(f"{ttft_ms}ms", style="#3fb950")
        if session_tokens > 0:
            t.append(sep, style="#30363d")
            if session_tokens >= 1_000_000:
                t.append(f"{session_tokens / 1_000_000:.1f}M tok", style="#484f58")
            elif session_tokens >= 1_000:
                t.append(f"{session_tokens / 1_000:.0f}K tok", style="#484f58")
            else:
                t.append(f"{session_tokens} tok", style="#484f58")
        t.append(sep, style="#30363d")
        t.append("/help", style="#3fb950")
        t.append("  ")
        t.append("^C", style="#8b949e bold")
        t.append(" quit", style="#484f58")
        return t

    def on_mount(self) -> None:
        self.set_interval(30, self.refresh)


# ── Model Picker Modal ───────────────────────────────────


class ModelPickerScreen(ModalScreen[str | None]):
    """Interactive model picker — select tier then model."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ModelPickerScreen {
        align: center middle;
    }
    #model-picker-box {
        width: 72;
        max-height: 28;
        background: #161b22;
        border: round #30363d;
        padding: 1 2;
    }
    #model-picker-box Static {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        color: #58a6ff;
        margin-bottom: 1;
    }
    #model-picker-box OptionList {
        height: auto;
        max-height: 20;
        background: #0d1117;
        border: solid #21262d;
    }
    """

    def __init__(self):
        super().__init__()
        self._phase = "tier"  # "tier" or "model"
        self._selected_tier: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="model-picker-box"):
            yield Static("⚙️  Model Picker — Select a tier to change")
            yield OptionList(id="picker-list")

    def on_mount(self) -> None:
        self._show_tier_list()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self._phase == "tier":
            if event.option.id == "__cancel__":
                self.dismiss(None)
                return
            self._selected_tier = event.option.id
            self._phase = "model"
            self._show_model_list()
        else:
            if event.option.id == "__cancel__":
                # Go back to tier selection
                self._phase = "tier"
                self._show_tier_list()
                return
            # Apply the selection
            tier = self._selected_tier
            model_id = event.option.id
            self._apply(tier, model_id)

    def _show_model_list(self) -> None:
        from ui import _fetch_model_catalog
        from agents.base import MODEL_CATALOG, _load_models, DEFAULT_MODELS

        live = _fetch_model_catalog(refresh=False)
        catalog = live if live else [(mid, name, desc) for mid, name, desc in MODEL_CATALOG]

        current_mid = _load_models().get(self._selected_tier, DEFAULT_MODELS.get(self._selected_tier, ""))

        ol = self.query_one("#picker-list", OptionList)
        ol.clear_options()
        self.query_one("#model-picker-box Static", Static).update(
            f"⚙️  Select model for [{self._selected_tier}]"
        )
        for mid, name, desc in catalog:
            marker = " ●" if mid == current_mid else "  "
            short_desc = (desc or "")[:40]
            label = f"{marker} {name:<22} {short_desc}"
            ol.add_option(Option(label, id=mid))
        ol.add_option(Separator())
        ol.add_option(Option("  ← Back", id="__cancel__"))

    def _show_tier_list(self) -> None:
        from agents.base import _load_models, DEFAULT_MODELS, MODEL_CATALOG
        models = _load_models()

        ol = self.query_one("#picker-list", OptionList)
        ol.clear_options()
        self.query_one("#model-picker-box Static", Static).update(
            "⚙️  Model Picker — Select a tier to change"
        )
        for tier in DEFAULT_MODELS:
            mid = models.get(tier, DEFAULT_MODELS[tier])
            name = next((c[1] for c in MODEL_CATALOG if c[0] == mid), mid.split(".")[-1])
            ol.add_option(Option(f"  {tier:<8} → {name}", id=tier))
        ol.add_option(Separator())
        ol.add_option(Option("  ↩ Cancel", id="__cancel__"))

    def _apply(self, tier: str, model_id: str) -> None:
        import json
        from agents.base import MODELS_FILE, reload_models, MODEL_CATALOG

        current = {}
        try:
            with open(MODELS_FILE) as f:
                current = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        current[tier] = model_id
        os.makedirs(os.path.dirname(MODELS_FILE), exist_ok=True)
        with open(MODELS_FILE, "w") as f:
            json.dump(current, f, indent=2)
        reload_models()
        from agent import reload_agent
        reload_agent()

        name = next((c[1] for c in MODEL_CATALOG if c[0] == model_id), model_id.split(".")[-1])
        self.dismiss(f"✓ {tier} → {name}")

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── Chat input widget ────────────────────────────────────


class ChatInput(TextArea):
    """TextArea that flags paste-inserted text so Enter-submit logic can skip it.

    Textual dispatches privately-named `_on_xxx` handlers by walking the MRO:
    overriding `_on_paste` does NOT replace TextArea's own `_on_paste` — both
    get invoked independently for every `Paste` event (this subclass's
    version runs first, since subclasses precede base classes in the MRO
    walk). So this method only sets the flag; TextArea's own handler (run
    right after, by the framework) performs the actual verbatim insert.
    Calling `super()._on_paste()` here would insert the pasted text twice.
    The App's `_on_input_changed` handler consumes (and clears) the flag
    once, so a pasted block — even one ending in a newline — lands intact
    instead of auto-submitting.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.suppress_next_submit = False

    async def _on_paste(self, event: events.Paste) -> None:
        if self.read_only:
            return
        self.suppress_next_submit = True


# ── App ──────────────────────────────────────────────────


class EnvoyApp(App):
    """Envoy TUI."""

    CSS_PATH = "tui.css"
    TITLE = "Envoy"
    ALLOW_SELECT = True

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("ctrl+y", "copy_output", "Copy selection", show=False),
        Binding("f5", "refresh_mcp", "Refresh", show=False),
        Binding("escape", "focus_input", "", show=False),
        Binding("alt+enter", "insert_newline", "Newline", show=False),
        Binding("ctrl+up", "history_prev", "Previous command", show=False),
        Binding("ctrl+down", "history_next", "Next command", show=False),
    ]

    HISTORY_FILE = CONFIG_DIR / "history"
    HISTORY_MAX = 500

    def __init__(self):
        super().__init__()
        self._agent = None
        self._busy = False  # True while a command is in flight (prevents concurrent agent calls)
        self._history: list[str] = []
        self._history_pos: int | None = None  # None = not browsing; else index into _history
        self._history_draft: str = ""          # current typed text, restored when user walks past end
        # Session stats for status bar
        self._session_tokens: int = 0
        self._last_ttft_ms: int | None = None
        # Streaming state: chunks the agent emits live, written to RichLog as they arrive.
        # The final result is suppressed on render if it matches what we streamed.
        self._stream_buffer: list[str] = []
        self._stream_pending: str = ""   # bytes not yet flushed to UI
        self._stream_started: bool = False

    def compose(self) -> ComposeResult:
        yield MCPBar(id="mcp-bar")
        yield RichLog(id="output", highlight=True, markup=True, wrap=True, max_lines=5000, auto_scroll=True)
        yield Spinner(id="spinner")
        with Horizontal(id="input-area"):
            yield Label("›", id="prompt-label")
            yield ChatInput(id="input", language=None, soft_wrap=True, show_line_numbers=False)
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        out = self.query_one("#output", RichLog)
        out.write(Text.from_markup(LOGO.format(version=VERSION)))
        self._show_update_notice(out)
        out.write(Text())
        self.query_one("#spinner", Spinner).display = False
        self.query_one("#input", TextArea).focus()
        self._load_history()
        self._init_agent()

    def _show_update_notice(self, out: RichLog) -> None:
        """Surface the `envoy` wrapper's update stamp file, if present.

        The wrapper writes ~/.envoy/update-available with the newer version
        string when it detects a newer git tag (absence/empty = up to date).
        Read defensively — this must never block or crash startup.
        """
        try:
            stamp = CONFIG_DIR / "update-available"
            latest = stamp.read_text().strip()
            if latest:
                ver = latest.lstrip("vV")
                out.write(Text(f"  ⬆ Envoy v{ver} available — run 'envoy update'", style="#d29922"))
        except Exception:
            pass

    @work(thread=True, exclusive=True, group="init")
    def _init_agent(self) -> None:
        from agent import get_agent
        self._agent = get_agent()
        name = "Envoy"
        try:
            from agents.base import agent_name
            name = agent_name()
        except Exception:
            pass
        self.app.call_from_thread(
            self.query_one("#output", RichLog).write,
            Text(f"  ✓ {name} ready\n", style="#3fb950"),
        )

    def on_click(self, event) -> None:
        # Don't steal focus from output — let users select/copy text
        if self.query_one("#output", RichLog).is_mouse_over:
            return
        self.query_one("#input", TextArea).focus()

    # ── Input handling ──

    @on(TextArea.Changed, "#input")
    def _on_input_changed(self, event: TextArea.Changed) -> None:
        """Submit on Enter; Alt+Enter and paste insert a literal newline instead.

        Textual's TextArea always inserts a literal "\\n" when Enter is
        pressed and posts this Changed event — that's the actual submit
        signal, detected here as "text ends with a newline". Multi-line
        pastes (even ones ending in a newline) and Alt+Enter-inserted
        newlines (see `action_insert_newline`) are flagged via
        `suppress_next_submit` (set by `ChatInput._on_paste` or
        `action_insert_newline`) so this handler skips the submit check for
        that one Changed event and lets the text land intact.
        """
        ta = event.text_area
        if getattr(ta, "suppress_next_submit", False):
            ta.suppress_next_submit = False
            return
        text = ta.text
        if text.endswith("\n"):
            raw = text.rstrip("\n")
            if not raw:
                ta.clear()
                return
            ta.clear()
            self._push_history(raw)
            self._history_pos = None
            self._history_draft = ""
            self._submit(raw)

    def _submit(self, raw: str) -> None:
        out = self.query_one("#output", RichLog)

        # Echo user input
        t = Text()
        t.append(f"\n › ", style="bold #58a6ff")
        t.append(raw, style="#e6edf3 bold")
        out.write(t)

        # Reject new input while a previous request is still running
        if self._busy:
            out.write(Text("  ⏳ Still working on your last request — wait for it to finish (or ctrl+c to quit).", style="#d29922"))
            return

        # System commands
        cmd = raw.split()[0].lower() if raw.startswith("/") else None
        if cmd == "/help":
            self._show_help()
            return
        if cmd in ("/exit", "/quit") or raw.strip().lower() in ("quit", "exit"):
            self.exit()
            return
        if cmd == "/status":
            self.action_refresh_mcp()
            return
        if cmd == "/mwinit":
            self._run_mwinit()
            return
        if cmd == "/settings":
            out.write(Text("  Use 'envoy settings' from CLI to edit config.", style="#8b949e"))
            return
        if cmd == "/backup":
            self._run_backup()
            return

        # After a bare `/models`, open the interactive picker modal
        if cmd == "/models" and not raw.split()[1:]:
            self._open_model_picker()
            return

        # Start animated spinner
        hint = _get_hint(raw)
        self.query_one("#spinner", Spinner).start(hint)
        self._busy = True
        self._run_command(raw, hint)

    def _ingest_stream_chunk(self, chunk: str) -> None:
        """Worker-thread callback: enqueue a chunk for the UI to flush.

        Called from inside the agent's callback handler (worker thread). We
        accumulate into a string buffer and schedule a flush on the UI thread.
        Splitting flush from receive lets us coalesce many small chunks into
        a single RichLog write per UI tick.
        """
        self._stream_buffer.append(chunk)
        self._stream_pending += chunk
        # Flush on newline boundaries to keep markdown-ish output legible
        if "\n" in chunk or len(self._stream_pending) > 200:
            self.app.call_from_thread(self._flush_stream)

    def _flush_stream(self) -> None:
        """UI thread: write accumulated streamed text to the RichLog."""
        if not self._stream_pending:
            return
        out = self.query_one("#output", RichLog)
        if not self._stream_started:
            # Stop the spinner the moment real text arrives — streaming IS the indicator now
            self.query_one("#spinner", Spinner).stop()
            out.write(Text())
            self._stream_started = True
        out.write(Text(self._stream_pending, style="#e6edf3"))
        self._stream_pending = ""

    @work(thread=True, exclusive=True, group="cmd")
    def _run_command(self, raw: str, hint: str) -> None:
        worker = get_current_worker()
        # Always fetch via get_agent() — picks up a fresh instance after
        # reload_agent() (e.g. triggered by /models tier changes).
        from agent import get_agent, set_stream_consumer
        self._agent = get_agent()

        # Reset streaming state and register consumer for this turn.
        self._stream_buffer = []
        self._stream_pending = ""
        self._stream_started = False
        set_stream_consumer(self._ingest_stream_chunk)

        error = None
        result = None
        handled = True
        import time as _time
        _t0 = _time.time()
        try:
            result, handled = dispatch(raw, self._agent)
        except Exception as e:
            error = e
        finally:
            set_stream_consumer(None)
        if worker.is_cancelled:
            self._busy = False
            return

        # Extract metrics from AgentResult
        try:
            from strands.agent.agent_result import AgentResult
            if isinstance(result, AgentResult) and result.metrics:
                m = result.metrics
                inv = m.latest_agent_invocation
                if inv:
                    self._session_tokens += inv.usage.get("totalTokens", 0)
                # TTFT: use first cycle duration of this invocation
                if inv and inv.cycles and m.cycle_durations:
                    n_cycles = len(inv.cycles)
                    idx = len(m.cycle_durations) - n_cycles
                    if idx >= 0:
                        self._last_ttft_ms = int(m.cycle_durations[idx] * 1000)
                elif not error:
                    # Fallback: wall-clock time for the whole call
                    self._last_ttft_ms = int((_time.time() - _t0) * 1000)
        except Exception:
            pass

        def _show():
            # Drain any trailing streamed text first
            self._flush_stream()

            # Stop spinner (no-op if streaming already stopped it)
            self.query_one("#spinner", Spinner).stop()
            self._busy = False

            out = self.query_one("#output", RichLog)
            if error is not None:
                msg = str(error)
                if "Concurrent invocations" in msg or "ConcurrencyException" in type(error).__name__:
                    out.write(Text("  ⚠️  Agent was still busy. Try again in a moment.", style="#d29922"))
                else:
                    out.write(Text(f"\n  ⚠️  {type(error).__name__}: {msg}\n", style="#f85149"))
                return
            if not handled:
                # dispatch() punted a system command back to us that this TUI
                # doesn't (yet) implement — don't echo the raw command string
                # as if it were a real response.
                cmd_name = result if isinstance(result, str) else raw.split()[0]
                out.write(Text(f"  ⚠ {cmd_name} is not available in the TUI", style="#d29922"))
                return
            if not result:
                return

            text = str(result)
            streamed = "".join(self._stream_buffer)

            # If streaming covered the full response, re-render once as Markdown
            # so headings/bullets land formatted (the live stream is plain text).
            # Skip if the result is a plain status message (slash commands handled internally).
            if self._stream_started and streamed and streamed.strip() == text.strip():
                # Replace the plain stream with a formatted render
                if any(c in text for c in ("#", "**", "- ", "| ", "```")):
                    try:
                        out.write(Text())
                        out.write(Markdown(text))
                        out.write(Text())
                    except Exception:
                        pass  # plain stream already on screen — no-op
                else:
                    out.write(Text())  # just spacing
                return

            if any(c in text for c in ("#", "**", "- ", "| ", "```")):
                try:
                    out.write(Text())
                    out.write(Markdown(text))
                    out.write(Text())
                except Exception:
                    out.write(Text(f"\n{text}\n"))
            else:
                out.write(Text(f"\n{text}\n"))

            # Toast notification — skip for usage errors / warnings so a
            # rejected command doesn't get a false "done" toast.
            if not text.startswith("Usage:") and not text.startswith("⚠"):
                self.notify(f"✓ {hint} done", timeout=3)
            # Refresh status bar to show updated TTFT/tokens
            self.query_one("#status-bar", StatusBar).refresh()

        self.app.call_from_thread(_show)

    def _open_model_picker(self) -> None:
        """Push the interactive model picker modal."""
        def _on_dismiss(result: str | None) -> None:
            out = self.query_one("#output", RichLog)
            if result:
                out.write(Text(f"  {result}", style="#3fb950"))
            else:
                out.write(Text("  Model picker closed.", style="#8b949e"))
            self.query_one("#input", TextArea).focus()

        self.push_screen(ModelPickerScreen(), callback=_on_dismiss)

    def _run_mwinit(self) -> None:
        import subprocess
        out = self.query_one("#output", RichLog)
        out.write(Text("  Launching mwinit — check your browser…", style="#8b949e"))

        def _do_mwinit():
            with self.suspend():
                subprocess.run(["mwinit", "-o"])
            # Close (not just forget) persistent MCP sessions so their
            # subprocesses don't leak, then reconnect with fresh creds.
            from agents.base import _cleanup_persistent
            _cleanup_persistent()
            self.action_refresh_mcp()
            self.notify("✓ Midway refreshed", timeout=3)

        self.call_later(_do_mwinit)

    def _run_backup(self) -> None:
        out = self.query_one("#output", RichLog)
        out.write(Text("  Backing up config, memory, and state…", style="#8b949e"))
        self._do_backup()

    @work(thread=True, exclusive=True, group="backup")
    def _do_backup(self) -> None:
        import contextlib
        import io

        from backup import run_backup

        path = None
        err = None
        try:
            # run_backup() prints progress via a rich Console tied to
            # sys.stdout; redirect so it can't scribble on the TUI's
            # alternate screen buffer.
            with contextlib.redirect_stdout(io.StringIO()):
                path = run_backup()
        except Exception as e:
            err = f"{type(e).__name__}: {e}"

        def _report():
            out = self.query_one("#output", RichLog)
            if err:
                out.write(Text(f"  ⚠️  Backup failed: {err}", style="#f85149"))
            elif path:
                out.write(Text(f"  ✓ Backup saved → {path.name}", style="#3fb950"))
                self.notify("✓ Backup complete", timeout=3)
            else:
                out.write(Text("  Nothing to back up — no config files found.", style="#d29922"))

        self.app.call_from_thread(_report)

    # ── Helpers ──

    def _load_history(self) -> None:
        try:
            if self.HISTORY_FILE.exists():
                lines = self.HISTORY_FILE.read_text().splitlines()
                self._history = [l for l in lines if l.strip()][-self.HISTORY_MAX:]
        except Exception:
            self._history = []

    def _push_history(self, entry: str) -> None:
        if not entry.strip():
            return
        # Dedupe consecutive entries
        if self._history and self._history[-1] == entry:
            return
        self._history.append(entry)
        self._history = self._history[-self.HISTORY_MAX:]
        try:
            self.HISTORY_FILE.parent.mkdir(exist_ok=True)
            self.HISTORY_FILE.write_text("\n".join(self._history) + "\n")
        except Exception:
            pass

    def _set_input_text(self, text: str) -> None:
        ta = self.query_one("#input", TextArea)
        ta.text = text
        # Move cursor to end
        try:
            ta.move_cursor(ta.document.end)
        except Exception:
            pass

    def action_history_prev(self) -> None:
        """Ctrl+Up — older entry."""
        if not self._history:
            return
        ta = self.query_one("#input", TextArea)
        if self._history_pos is None:
            self._history_draft = ta.text.rstrip("\n")
            self._history_pos = len(self._history)
        if self._history_pos > 0:
            self._history_pos -= 1
            self._set_input_text(self._history[self._history_pos])

    def action_history_next(self) -> None:
        """Ctrl+Down — newer entry; past the end restores the user's draft."""
        if self._history_pos is None:
            return
        self._history_pos += 1
        if self._history_pos >= len(self._history):
            self._history_pos = None
            self._set_input_text(self._history_draft)
            self._history_draft = ""
        else:
            self._set_input_text(self._history[self._history_pos])

    def _show_help(self) -> None:
        out = self.query_one("#output", RichLog)
        out.write(Text())
        for group_name, cmds in COMMAND_GROUPS:
            t = Text()
            t.append(f"  {group_name}\n", style="bold #58a6ff")
            for cmd in cmds:
                entry = COMMANDS.get(cmd)
                desc = entry[0] if entry else ""
                t.append(f"    {cmd:22s}", style="#3fb950")
                t.append(f"{desc}\n", style="#8b949e")
            out.write(t)

    def action_refresh_mcp(self) -> None:
        self.query_one("#spinner", Spinner).start("Refreshing MCP")
        self.query_one(MCPBar).check()

    def action_focus_input(self) -> None:
        """Escape: cancel the in-flight command if one is running, else just focus input."""
        if self._busy:
            self.workers.cancel_group(self, "cmd")
            self.query_one("#spinner", Spinner).stop()
            self._busy = False
            self.query_one("#output", RichLog).write(Text("  ✗ cancelled", style="#f85149"))
        self.query_one("#input", TextArea).focus()

    def action_insert_newline(self) -> None:
        """Alt+Enter: insert a literal newline into the input without submitting."""
        ta = self.query_one("#input", TextArea)
        ta.suppress_next_submit = True
        ta.insert("\n")

    def action_copy_output(self) -> None:
        """Copy selected text (or last output) to clipboard."""
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            self.notify("Copied to clipboard", timeout=2)
        else:
            self.notify("Select text first (click + drag in output), then Ctrl+Y", timeout=3)


def run_tui():
    """Launch the Textual TUI."""
    EnvoyApp().run()
