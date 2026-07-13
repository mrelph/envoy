"""Envoy — Textual TUI interface."""

import os
import re
import threading
import time
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
from agents.paths import CONFIG_DIR, SOUL_FILE

VERSION = (Path(__file__).parent / "VERSION").read_text().strip()

def _logo():
    from tui_themes import get_theme
    t = get_theme()
    return (
        f"[bold {t['accent']}]"
        "  ╭──────────"
        "────────────"
        "────────────"
        "────╮\n"
        "  │                                      │\n"
        "  │    E N V O Y                         │\n"
        "  │                                      │\n"
        f"  │    [dim {t['text_dim']}]Your AI Chief of Staff"
        f"[/dim {t['text_dim']}]            │\n"
        f"  │    [dim {t['text_faint']}]v{VERSION}"
        f"[/dim {t['text_faint']}]                            │\n"
        "  │                                      │\n"
        "  ╰──────────"
        "────────────"
        "────────────"
        "────╯"
        f"[/bold {t['accent']}]"
    )

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


_MD_HEADING_RE = re.compile(r"(?m)^#{1,3} ")
_MD_TABLE_ROW_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")


def _looks_like_markdown(text: str) -> bool:
    """Heuristic: does `text` contain strong-enough markdown signals to be
    worth reflowing through `rich.markdown.Markdown`?

    Deliberately conservative — the previous heuristic (`"- " in text`)
    reflowed ordinary prose containing a plain hyphen ("day-to-day", "- "
    as an em-dash substitute, etc.). Require an actual heading line, a
    fenced code block, a table row, or repeated bold markers instead.
    """
    if "```" in text:
        return True
    if _MD_HEADING_RE.search(text):
        return True
    if _MD_TABLE_ROW_RE.search(text):
        return True
    if text.count("**") >= 2:
        return True
    return False


def _should_rerender_as_markdown(stream_started: bool, text: str) -> bool:
    """Decide whether `_show()` should write a formatted Markdown render of `text`.

    RichLog is append-only — it can't replace lines already written. If the
    response streamed live, the plain text already on screen IS the
    permanent record for simple responses.

    However, tables and headings are unreadable as plain streamed text, so
    for responses with those heavy-markdown signals `_show()` removes this
    turn's streamed lines (`_truncate_stream_output`) and re-renders them
    formatted — the formatting gain justifies the brief visual flash.
    """
    if not _looks_like_markdown(text):
        return False
    if not stream_started:
        return True
    # Streamed responses: re-render only for tables and headings (unreadable raw).
    # Plain bold/bullet responses are readable enough as streamed text.
    if _MD_TABLE_ROW_RE.search(text) or _MD_HEADING_RE.search(text):
        return True
    return False


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
        from tui_themes import get_theme
        th = get_theme()
        status = _check_mcp_servers()
        t = Text(" Envoy  ", style=f"bold {th['accent']}")
        t.append("│ ", style=th['border'])
        for name, ok in status.items():
            t.append("● " if ok else "○ ", style=th['success'] if ok else th['error'])
            t.append(name, style=th['text'] if ok else th['text_faint'])
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


class FeedPanel(Static):
    """Ambient activity feed — proactive insights scrolling at the top."""

    _items: list = []
    _max_visible: int = 4

    def render(self) -> Text:
        if not self._items:
            return Text("")
        from tui_themes import get_theme
        t = Text()
        for item in self._items[-self._max_visible:]:
            t.append(f"  {item.display}\n", style=get_theme()['text_dim'])
        return t

    def push(self, item) -> None:
        """Add a new feed item and refresh."""
        self._items.append(item)
        if len(self._items) > 20:
            self._items = self._items[-20:]
        self.refresh()

    def on_mount(self) -> None:
        """Start the feed poll loop."""
        self._start_feed()

    @work(thread=True)
    def _start_feed(self) -> None:
        """Register listener and start the background poll."""
        import asyncio
        from agents.feed import on_new_item, start as start_feed, _poll_once

        def _on_item(item):
            try:
                self.app.call_from_thread(self.push, item)
            except Exception:
                pass

        on_new_item(_on_item)

        # Run the poll loop on the base event loop
        try:
            from agents.base import _get_loop
            loop = _get_loop()
            asyncio.run_coroutine_threadsafe(_poll_loop_safe(), loop)
        except Exception:
            pass


async def _poll_loop_safe():
    """Safe poll loop that runs in the background event loop."""
    import asyncio
    from agents import feed
    feed._running = True
    await asyncio.sleep(15)  # initial delay
    # Gate on the live module flag (not a captured value) so feed.stop() halts us.
    while feed._running:
        try:
            await feed._poll_once()
        except Exception:
            pass
        await asyncio.sleep(feed._POLL_INTERVAL)


class Spinner(Static):
    """Animated braille spinner with elapsed time, step count, and live tool info."""

    _frame: int = 0
    _hint: str = ""
    _flavor_idx: int = 0
    _timer = None
    _start_time: float = 0
    _steps: int = 0
    _tool_history: list = []

    def render(self) -> Text:
        if not self._hint:
            return Text("")
        import time as _time
        from tui_themes import get_theme
        th = get_theme()
        char = BRAILLE_FRAMES[self._frame % len(BRAILLE_FRAMES)]
        elapsed = _time.time() - self._start_time if self._start_time else 0

        t = Text(f"  {char} ", style=f"bold {th['accent']}")
        t.append(self._hint, style=f"{th['text']} bold")

        if elapsed >= 60:
            t.append(f"  {int(elapsed)}s", style=th['warning'])
        elif elapsed >= 5:
            t.append(f"  {int(elapsed)}s", style=th['text_dim'])

        if self._steps > 0:
            t.append(f"  ·  step {self._steps}", style=th['text_faint'])
            if self._tool_history:
                trail = " → ".join(self._tool_history[-2:])
                t.append(f"  [{trail}]", style=f"{th['text_faint']} italic")
        else:
            flavor = _FLAVOR[self._flavor_idx % len(_FLAVOR)]
            t.append(f"  ·  {flavor}…", style=th['text_faint'])

        return t

    def start(self, hint: str) -> None:
        import random, time as _time
        self._hint = hint
        self._frame = 0
        self._steps = 0
        self._tool_history = []
        self._start_time = _time.time()
        self._flavor_idx = random.randint(0, len(_FLAVOR) - 1)
        self.display = True
        self.refresh()
        if self._timer is None:
            self._timer = self.set_interval(0.1, self._tick)

    def update_hint(self, hint: str) -> None:
        """Update when a new tool fires — tracks steps and tool names."""
        self._steps += 1
        # Extract short name from label (strip emoji prefix)
        short = hint.lstrip("📧💬📅✅📊🔎📁💻👁🧩📬 ")
        if short:
            self._tool_history.append(short)
        self._hint = hint
        self.refresh()

    def stop(self) -> None:
        self._hint = ""
        self.display = False
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _tick(self) -> None:
        self._frame += 1
        if self._steps == 0 and self._frame % 30 == 0:  # rotate flavor every ~3s (only before first tool)
            self._flavor_idx += 1
        self.refresh()


class StatusBar(Static):
    """Bottom bar with alias, time, model, keybindings."""

    def render(self) -> Text:
        alias = _get_alias()
        now = datetime.now().strftime("%I:%M %p").lstrip("0")

        model = ""
        try:
            # model_for() reads models.json once and keeps it in an
            # in-memory cache (agents.base._models_cache), invalidated only
            # by reload_models() — unlike _load_models(), which always hits
            # disk. Use it here so a 30s status-bar tick isn't a fresh
            # models.json read every time.
            from agents.base import model_for
            mid = model_for("agent")
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
        turn_in = 0
        turn_out = 0
        active_workers = []
        try:
            app = self.app
            ttft_ms = app._last_ttft_ms
            session_tokens = app._session_tokens
            turn_in = app._turn_input_tokens
            turn_out = app._turn_output_tokens
            active_workers = app._active_workers
        except Exception:
            pass

        from tui_themes import get_theme
        th = get_theme()
        sep = "  ·  "
        t = Text()
        t.append(f" {alias}", style=f"bold {th['accent']}")
        t.append(sep, style=th['border'])
        t.append(now, style=th['text_dim'])
        if model:
            t.append(sep, style=th['border'])
            t.append(f"⚡ {model}", style=th['model'])
        if ttft_ms is not None:
            t.append(sep, style=th['border'])
            if ttft_ms >= 1000:
                t.append(f"{ttft_ms / 1000:.1f}s", style=th['warning'])
            else:
                t.append(f"{ttft_ms}ms", style=th['success'])
        # Token counts: show turn breakdown if available, else session total
        if turn_in or turn_out:
            t.append(sep, style=th['border'])
            t.append(f"↑{self._fmt_tokens(turn_in)} ↓{self._fmt_tokens(turn_out)}", style=th['text_dim'])
        if session_tokens > 0:
            t.append(sep, style=th['border'])
            t.append(f"Σ {self._fmt_tokens(session_tokens)}", style=th['text_faint'])
        # Active workers
        if active_workers:
            t.append(sep, style=th['border'])
            t.append(" ".join(active_workers[:3]), style=th['accent_dim'])
            if len(active_workers) > 3:
                t.append(f" +{len(active_workers) - 3}", style=th['text_faint'])
        t.append(sep, style=th['border'])
        t.append("/help", style=th['success'])
        t.append("  ")
        t.append("Esc", style=f"{th['text_dim']} bold")
        t.append(" cancel", style=th['text_faint'])
        return t

    @staticmethod
    def _fmt_tokens(n: int) -> str:
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        elif n >= 1_000:
            return f"{n / 1_000:.0f}K"
        return str(n)

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
        """Populate the model list for the selected tier.

        `_fetch_model_catalog` makes synchronous boto3 network calls on a
        cache miss — calling it directly here would block the UI thread for
        as long as those calls take. `ui._read_cache()` does only a cheap
        disk read of the same 1h cache, so a warm cache renders immediately;
        a cold/expired cache falls back to a `@work(thread=True)` fetch with
        a placeholder shown in the meantime.
        """
        from ui import _read_cache

        cached = _read_cache()
        if cached is not None:
            self._render_model_list(cached)
            return

        ol = self.query_one("#picker-list", OptionList)
        ol.clear_options()
        self.query_one("#model-picker-box Static", Static).update(
            f"⚙️  Select model for [{self._selected_tier}]"
        )
        ol.add_option(Option("  ⏳ loading model catalog…", id="__loading__", disabled=True))
        self._fetch_catalog_worker()

    @work(thread=True, exclusive=True, group="model-catalog")
    def _fetch_catalog_worker(self) -> None:
        """Background thread: the actual (possibly network-hitting) catalog fetch."""
        from ui import _fetch_model_catalog
        from agents.base import MODEL_CATALOG

        try:
            live = _fetch_model_catalog(refresh=False)
        except Exception:
            live = []
        catalog = live if live else [(mid, name, desc) for mid, name, desc in MODEL_CATALOG]
        self.app.call_from_thread(self._render_model_list, catalog)

    def _render_model_list(self, catalog) -> None:
        """UI thread: paint the (already-fetched) catalog into the OptionList."""
        from agents.base import _load_models, DEFAULT_MODELS

        # The phase may have moved on (e.g. user backed out) while a
        # background fetch was in flight — don't paint a stale list over
        # whatever screen state is now current.
        if self._phase != "model":
            return

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


# ── Theme Picker Modal ──────────────────────────────────


class ThemePickerScreen(ModalScreen[str | None]):
    """Interactive theme picker with live colour previews."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    ThemePickerScreen {
        align: center middle;
    }
    #theme-picker-box {
        width: 72;
        max-height: 32;
        border: round #3a424c;
        padding: 1 2;
    }
    #theme-picker-box Static {
        width: 100%;
        content-align: center middle;
        text-style: bold;
        margin-bottom: 1;
    }
    #theme-list {
        height: auto;
        max-height: 22;
        border: solid #3a424c;
    }
    #theme-preview {
        height: 7;
        padding: 0 2;
        margin-top: 1;
        border: round #3a424c;
    }
    """

    def compose(self) -> ComposeResult:
        from tui_themes import get_theme
        th = get_theme()
        with Vertical(id="theme-picker-box"):
            yield Static("🎨  Theme Picker")
            yield OptionList(id="theme-list")
            yield Static(id="theme-preview")

    def on_mount(self) -> None:
        self._populate_list()
        # Highlight the current theme
        from tui_themes import get_theme_name, THEMES
        current = get_theme_name()
        names = list(THEMES.keys())
        if current in names:
            ol = self.query_one("#theme-list", OptionList)
            try:
                ol.highlighted = names.index(current)
            except Exception:
                pass
        self._show_preview(current)

    def _populate_list(self) -> None:
        from tui_themes import THEMES, get_theme_name
        from dispatch import _THEME_DESCRIPTIONS
        current = get_theme_name()
        ol = self.query_one("#theme-list", OptionList)
        ol.clear_options()
        for name in THEMES:
            marker = " ●" if name == current else "  "
            desc = _THEME_DESCRIPTIONS.get(name, "")
            ol.add_option(Option(f"{marker} {name:<12} {desc}", id=name))
        ol.add_option(Separator())
        ol.add_option(Option("  ↩ Cancel", id="__cancel__"))

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option.id and event.option.id != "__cancel__":
            self._show_preview(event.option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id == "__cancel__":
            self.dismiss(None)
            return
        from tui_themes import set_theme
        set_theme(event.option.id)
        self.dismiss(event.option.id)

    def _show_preview(self, name: str) -> None:
        from tui_themes import THEMES
        theme = THEMES.get(name)
        if not theme:
            return
        preview = self.query_one("#theme-preview", Static)
        t = Text()
        t.append(f"  {name}\n", style=f"bold {theme['accent']}")
        t.append(f"  ── Preview ──────────────────────────────\n", style=theme['border'])
        t.append(f"  › ", style=f"bold {theme['accent']}")
        t.append("summarise my inbox\n", style=f"{theme['text']} bold")
        t.append(f"  You have 12 unread emails. ", style=theme['text'])
        t.append("3 need replies.\n", style=theme['text'])
        t.append(f"  ↑4K ↓2K", style=theme['text_dim'])
        t.append(f"  ·  ", style=theme['border'])
        t.append(f"⚡ fable 5", style=theme['model'])
        t.append(f"  ·  ", style=theme['border'])
        t.append(f"📧 Email", style=theme['accent_dim'])
        t.append(f"  ·  ", style=theme['border'])
        t.append("✓ done", style=theme['success'])
        t.append(f"  ·  ", style=theme['border'])
        t.append("⚠ slow", style=theme['warning'])
        t.append(f"  ·  ", style=theme['border'])
        t.append("✗ error", style=theme['error'])
        preview.update(t)
        # Tint the preview background
        preview.styles.background = theme['bg']
        preview.styles.border = ("round", theme['border'])

    def action_cancel(self) -> None:
        self.dismiss(None)


# ── Chat input widget ────────────────────────────────────


class ChatInput(TextArea):
    """TextArea with paste-flag, Tab-completion for slash commands.

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

    BINDINGS = [
        Binding("tab", "complete", "Complete", show=False),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.suppress_next_submit = False
        self._complete_matches: list[str] = []
        self._complete_idx: int = 0
        self._complete_prefix: str = ""

    def action_complete(self) -> None:
        """Tab: cycle through matching slash commands."""
        text = self.text.rstrip("\n")
        if not text.startswith("/"):
            return

        # If we're already cycling and the text matches our last completion,
        # advance to the next match.
        if (self._complete_matches
                and self._complete_prefix
                and text in self._complete_matches):
            self._complete_idx = (self._complete_idx + 1) % len(self._complete_matches)
            self._set_completion(self._complete_matches[self._complete_idx])
            return

        # New prefix — find matches
        prefix = text.lower()
        self._complete_prefix = prefix
        all_cmds = sorted(COMMANDS.keys())
        matches = [c for c in all_cmds if c.startswith(prefix)]
        if not matches:
            return
        if len(matches) == 1:
            self._complete_matches = []
            self._set_completion(matches[0] + " ")
        else:
            self._complete_matches = matches
            self._complete_idx = 0
            self._set_completion(matches[0])

    def _set_completion(self, value: str) -> None:
        """Replace the current text with the completed command."""
        self.suppress_next_submit = True
        self.clear()
        self.insert(value)

    async def _on_paste(self, event: events.Paste) -> None:
        if self.read_only:
            return
        self.suppress_next_submit = True


# ── App ──────────────────────────────────────────────────


class EnvoyApp(App):
    """Envoy TUI."""

    # CSS is generated from the active theme — see tui_themes.build_css()
    from tui_themes import build_css as _build_css
    DEFAULT_CSS = _build_css()
    del _build_css

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
        self._turn_input_tokens: int = 0
        self._turn_output_tokens: int = 0
        self._last_ttft_ms: int | None = None
        self._active_workers: list[str] = []
        # Streaming state: chunks the agent emits live, written to RichLog as they arrive.
        # The final result is suppressed on render if it matches what we streamed.
        self._stream_buffer: list[str] = []
        self._stream_pending: str = ""   # text not yet flushed to UI
        self._stream_started: bool = False
        # `_stream_pending` is appended to from the worker thread (inside the
        # agent's callback handler) and drained on the UI thread (`_flush_stream`,
        # invoked via call_from_thread) — guard both sides so a chunk arriving
        # mid-drain can't be lost or duplicated.
        self._stream_lock = threading.Lock()
        self._last_text_ts: float = 0.0  # monotonic time of the last flushed text chunk
        # (len(out.lines), out._start_line) captured at the first flush of a
        # turn — lets `_show()` truncate just this turn's streamed lines.
        self._stream_anchor: tuple[int, int] = (0, 0)

    def compose(self) -> ComposeResult:
        yield MCPBar(id="mcp-bar")
        yield FeedPanel(id="feed")
        # min_width=4: RichLog's default min_width is 78, and write() renders
        # at max(content_width, min_width) — so on viewports narrower than 78
        # columns, text rendered at 78 wide overflows horizontally instead of
        # wrapping. A tiny min_width lets wrap=True fit the real widget width.
        yield RichLog(id="output", highlight=False, markup=True, wrap=True, min_width=4, max_lines=5000, auto_scroll=True)
        yield Spinner(id="spinner")
        with Horizontal(id="input-area"):
            yield Label("›", id="prompt-label")
            yield ChatInput(id="input", language=None, soft_wrap=True, show_line_numbers=False)
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        out = self.query_one("#output", RichLog)
        out.write(Text.from_markup(_logo()))
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
            from tui_themes import get_theme
            stamp = CONFIG_DIR / "update-available"
            latest = stamp.read_text().strip()
            if latest:
                ver = latest.lstrip("vV")
                out.write(Text(f"  ⬆ Envoy v{ver} available — run 'envoy update'", style=get_theme()['warning']))
        except Exception:
            pass

    @work(thread=True, exclusive=True, group="init")
    def _init_agent(self) -> None:
        from agent import get_agent
        from tui_themes import get_theme
        self._agent = get_agent()
        name = "Envoy"
        try:
            from agents.base import agent_name
            name = agent_name()
        except Exception:
            pass
        th = get_theme()
        self.app.call_from_thread(
            self.query_one("#output", RichLog).write,
            Text(f"  ✓ {name} ready\n", style=th['success']),
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
        from tui_themes import get_theme
        th = get_theme()
        t = Text()
        t.append("\n› ", style=f"bold {th['accent']}")
        t.append(raw, style=f"{th['text']} bold")
        out.write(t)

        # Reject new input while a previous request is still running
        if self._busy:
            out.write(Text("  ⏳ Still working on your last request — wait for it to finish (or Esc to cancel).", style=th['warning']))
            return

        # System commands
        cmd = raw.split()[0].lower() if raw.startswith("/") else None
        if cmd == "/help":
            show_full = "all" in raw.lower().split()[1:]
            self._show_help(full=show_full)
            return
        if cmd in ("/exit", "/quit") or raw.strip().lower() in ("quit", "exit"):
            self.exit()
            return
        if cmd == "/status":
            self.action_refresh_mcp()
            return
        if cmd == "/settings":
            self._run_settings()
            return
        if cmd == "/backup":
            self._run_backup()
            return

        # After a bare `/models`, open the interactive picker modal
        if cmd == "/models" and not raw.split()[1:]:
            self._open_model_picker()
            return

        # Bare `/theme` opens interactive picker; `/theme <name>` goes through dispatch
        if cmd == "/theme" and not raw.split()[1:]:
            self._open_theme_picker()
            return

        # Start animated spinner
        hint = _get_hint(raw)
        self.query_one("#spinner", Spinner).start(hint)
        self._busy = True
        self._run_command(raw, hint)

    def _ingest_stream_chunk(self, chunk) -> None:
        """Worker-thread callback: enqueue a chunk (or tool event) for the UI.

        Called from inside the agent's callback handler (worker thread), so
        two event shapes arrive here (see `agent.set_stream_consumer`):
        plain text chunks, and `("tool", tool_name)` events fired when a
        worker/tool starts running. Text chunks accumulate into a string
        buffer (behind `_stream_lock` — see its declaration in `__init__`)
        and schedule a flush on the UI thread; splitting flush from receive
        lets us coalesce many small chunks into a single RichLog write per
        UI tick. Tool events are dispatched straight to the UI thread so the
        spinner can restart during a silent worker delegation.
        """
        if isinstance(chunk, tuple) and len(chunk) == 2 and chunk[0] == "tool":
            self.app.call_from_thread(self._on_tool_event, chunk[1])
            return
        self._stream_buffer.append(chunk)
        with self._stream_lock:
            self._stream_pending += chunk
            pending_len = len(self._stream_pending)
        # Flush on newline boundaries to keep markdown-ish output legible
        if "\n" in chunk or pending_len > 200:
            self.app.call_from_thread(self._flush_stream)

    def _on_step(self, label: str) -> None:
        """Worker-thread callback: update the spinner hint when a new tool fires."""
        try:
            self.app.call_from_thread(
                self.query_one("#spinner", Spinner).update_hint, label
            )
        except Exception:
            pass

    def _flush_stream(self) -> None:
        """UI thread: write accumulated streamed text to the RichLog."""
        with self._stream_lock:
            pending = self._stream_pending
            self._stream_pending = ""
        if not pending:
            return
        out = self.query_one("#output", RichLog)
        # Stop the spinner unconditionally: either the very first spinner
        # (streaming IS the indicator now) or a tool-activity spinner that
        # `_on_tool_event` restarted mid-turn — text resuming means the gap
        # is over. Stop() is a no-op if it's already stopped.
        self.query_one("#spinner", Spinner).stop()
        if not self._stream_started:
            # Remember where this turn's streamed output begins so `_show()`
            # can truncate and re-render it as Markdown if warranted. Record
            # `_start_line` too: if `max_lines` trimming drops early lines
            # mid-turn, the anchor index shifts down by the trimmed count.
            self._stream_anchor = (len(out.lines), out._start_line)
            out.write(Text())
            self._stream_started = True
        from tui_themes import get_theme
        text_color = get_theme()['text']
        out.write(Text(pending, style=text_color, overflow="fold", no_wrap=False))
        self._last_text_ts = time.monotonic()

    def _truncate_stream_output(self, out: RichLog) -> bool:
        """UI thread: drop this turn's streamed lines from the RichLog.

        RichLog has no public API to remove a range of lines, so this trims
        `out.lines` back to the anchor captured at the turn's first flush
        (`_flush_stream`), leaving all earlier history intact. `_start_line`
        drift accounts for lines `max_lines` trimmed off the top since the
        anchor was taken. Returns False if the log state no longer matches
        (e.g. it was cleared mid-turn), in which case the caller should
        leave the log alone.
        """
        anchor_len, anchor_start = self._stream_anchor
        trimmed = out._start_line - anchor_start
        if trimmed < 0:
            return False
        keep = max(0, anchor_len - trimmed)
        if keep > len(out.lines):
            return False
        del out.lines[keep:]
        from textual.geometry import Size
        out.virtual_size = Size(out.virtual_size.width, len(out.lines))
        out.refresh()
        return True

    def _on_tool_event(self, tool_name: str) -> None:
        """UI thread: a worker/tool started running mid-turn.

        Restarts the spinner with a friendly label so a multi-second (to
        multi-minute) worker delegation doesn't leave a frozen screen once
        the initial streamed text has already stopped the spinner. Skipped
        if text is actively streaming right now — the stream itself is
        already a sufficient activity indicator — and it stops again the
        moment text resumes (`_flush_stream`) or the command completes
        (`_run_command`'s `_show`).
        """
        if not self._busy:
            return
        from agent import _LABELS
        label = _LABELS.get(tool_name, tool_name)
        # Track active workers for status bar display
        if label not in self._active_workers:
            self._active_workers.append(label)
            self.query_one("#status-bar", StatusBar).refresh()
        if time.monotonic() - self._last_text_ts < 1.0:
            return
        self.query_one("#spinner", Spinner).start(label)

    @work(thread=True, exclusive=True, group="cmd")
    def _run_command(self, raw: str, hint: str) -> None:
        worker = get_current_worker()
        # Always fetch via get_agent() — picks up a fresh instance after
        # reload_agent() (e.g. triggered by /models tier changes).
        from agent import get_agent, set_stream_consumer, set_step_consumer
        self._agent = get_agent()

        # Reset streaming state and register consumers for this turn.
        self._stream_buffer = []
        with self._stream_lock:
            self._stream_pending = ""
        self._stream_started = False
        self._last_text_ts = 0.0
        self._active_workers = []
        self._turn_input_tokens = 0
        self._turn_output_tokens = 0
        set_stream_consumer(self._ingest_stream_chunk)
        set_step_consumer(self._on_step)

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
            set_step_consumer(None)
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
                    usage = inv.usage
                    total = usage.get("totalTokens", 0)
                    self._session_tokens += total
                    self._turn_input_tokens = usage.get("inputTokens", 0)
                    self._turn_output_tokens = usage.get("outputTokens", 0)
                # TTFT: use first cycle duration of this invocation
                if inv and inv.cycles and m.cycle_durations:
                    n_cycles = len(inv.cycles)
                    idx = len(m.cycle_durations) - n_cycles
                    if idx >= 0:
                        self._last_ttft_ms = int(m.cycle_durations[idx] * 1000)
                elif not error:
                    self._last_ttft_ms = int((_time.time() - _t0) * 1000)
        except Exception:
            pass

        def _show():
            from tui_themes import get_theme
            th = get_theme()
            self.query_one("#spinner", Spinner).stop()
            self._busy = False
            self._active_workers = []

            out = self.query_one("#output", RichLog)
            if error is not None:
                msg = str(error)
                if "Concurrent invocations" in msg or "ConcurrencyException" in type(error).__name__:
                    out.write(Text("  ⚠️  Agent was still busy. Try again in a moment.", style=th['warning']))
                else:
                    out.write(Text(f"\n  ⚠️  {type(error).__name__}: {msg}\n", style=th['error']))
                return
            if not handled:
                cmd_name = result if isinstance(result, str) else raw.split()[0]
                out.write(Text(f"  ⚠ {cmd_name} is not available in the TUI", style=th['warning']))
                return
            if not result:
                return

            text = str(result)

            if _should_rerender_as_markdown(self._stream_started, text):
                # For streamed responses with heavy markdown (tables/headings),
                # remove just this turn's raw streamed lines (keeping prior
                # history) and re-render formatted. The brief flash is worth
                # readable tables.
                if self._stream_started:
                    self._truncate_stream_output(out)
                try:
                    out.write(Text())
                    out.write(Markdown(text))
                    out.write(Text())
                except Exception:
                    out.write(Text(f"\n{text}\n"))
            elif self._stream_started:
                # Streamed text without heavy markdown — already readable on
                # screen, just add spacing.
                out.write(Text())
                return
            else:
                out.write(Text(f"\n{text}\n"))

            # Toast notification — skip for usage errors / warnings so a
            # rejected command doesn't get a false "done" toast.
            if not text.startswith("Usage:") and not text.startswith("⚠"):
                self.notify(f"✓ {hint} done", timeout=3)

            # Turn separator — subtle line between exchanges
            out.write(Text("  " + "─" * 44, style=th['border']))
            # Refresh status bar to show updated TTFT/tokens
            self.query_one("#status-bar", StatusBar).refresh()

        self.app.call_from_thread(_show)

    def _open_model_picker(self) -> None:
        """Push the interactive model picker modal."""
        def _on_dismiss(result: str | None) -> None:
            from tui_themes import get_theme
            th = get_theme()
            out = self.query_one("#output", RichLog)
            if result:
                out.write(Text(f"  {result}", style=th['success']))
            else:
                out.write(Text("  Model picker closed.", style=th['text_dim']))
            self.query_one("#input", TextArea).focus()

        self.push_screen(ModelPickerScreen(), callback=_on_dismiss)

    def _open_theme_picker(self) -> None:
        """Push the interactive theme picker modal."""
        def _on_dismiss(result: str | None) -> None:
            from tui_themes import get_theme
            th = get_theme()
            out = self.query_one("#output", RichLog)
            if result:
                out.write(Text(f"  Theme set to {result}. Restart the TUI to apply.", style=th['success']))
                self.notify(f"Theme → {result} (restart to apply)", timeout=4)
            else:
                out.write(Text("  Theme picker closed.", style=th['text_dim']))
            self.query_one("#input", TextArea).focus()

        self.push_screen(ThemePickerScreen(), callback=_on_dismiss)

    def _run_settings(self) -> None:
        """Run the interactive CLI settings editor under `self.suspend()`.

        `init_cmd.run_settings()` is a synchronous, `input()`-driven console
        flow, so it needs the TUI's alternate screen suspended rather than a
        background worker. Settings can change soul/envoy/process files that
        feed the agent's system prompt, so reload the cached agent afterwards.
        """
        out = self.query_one("#output", RichLog)
        from tui_themes import get_theme
        out.write(Text("  Opening settings…", style=get_theme()['text_dim']))

        def _do_settings():
            import init_cmd
            with self.suspend():
                init_cmd.run_settings()
            from agent import get_agent, reload_agent
            reload_agent()
            self._agent = get_agent()
            self.notify("✓ Settings updated", timeout=3)
            self.query_one("#input", TextArea).focus()

        self.call_later(_do_settings)

    def _run_backup(self) -> None:
        out = self.query_one("#output", RichLog)
        from tui_themes import get_theme
        out.write(Text("  Backing up config, memory, and state…", style=get_theme()['text_dim']))
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
            from tui_themes import get_theme
            th = get_theme()
            out = self.query_one("#output", RichLog)
            if err:
                out.write(Text(f"  ⚠️  Backup failed: {err}", style=th['error']))
            elif path:
                out.write(Text(f"  ✓ Backup saved → {path.name}", style=th['success']))
                self.notify("✓ Backup complete", timeout=3)
            else:
                out.write(Text("  Nothing to back up — no config files found.", style=th['warning']))

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

    # Commands shown in the compact help view (most-used subset)
    _HELP_ESSENTIALS = [
        "/briefing", "/inbox", "/catchup", "/todo",
        "/reply", "/schedule", "/team-health", "/help all",
    ]

    def _show_help(self, full: bool = False) -> None:
        from tui_themes import get_theme
        th = get_theme()
        out = self.query_one("#output", RichLog)
        out.write(Text())

        if not full:
            t = Text()
            t.append("  Quick commands\n", style=f"bold {th['accent']}")
            for cmd in self._HELP_ESSENTIALS:
                entry = COMMANDS.get(cmd)
                desc = entry[0] if entry else "Show all commands"
                t.append(f"    {cmd:22s}", style=th['success'])
                t.append(f"{desc}\n", style=th['text_dim'])
            t.append(f"\n  ", style="")
            t.append("Tip: ", style=f"bold {th['text_dim']}")
            t.append("type ", style=th['text_dim'])
            t.append("/help all", style=th['success'])
            t.append(" for every command, or ", style=th['text_dim'])
            t.append("/", style=th['success'])
            t.append(" + Tab to autocomplete\n", style=th['text_dim'])
            out.write(t)
            return

        for group_name, cmds in COMMAND_GROUPS:
            t = Text()
            t.append(f"  {group_name}\n", style=f"bold {th['accent']}")
            for cmd in cmds:
                entry = COMMANDS.get(cmd)
                desc = entry[0] if entry else ""
                t.append(f"    {cmd:22s}", style=th['success'])
                t.append(f"{desc}\n", style=th['text_dim'])
            out.write(t)

    def action_refresh_mcp(self) -> None:
        self.query_one("#spinner", Spinner).start("Refreshing MCP")
        self.query_one(MCPBar).check()

    def action_focus_input(self) -> None:
        """Escape: cancel the in-flight command if one is running, else just focus input."""
        if self._busy:
            from tui_themes import get_theme
            self.workers.cancel_group(self, "cmd")
            self.query_one("#spinner", Spinner).stop()
            self._busy = False
            self.query_one("#output", RichLog).write(Text("  ✗ cancelled", style=get_theme()['error']))
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
