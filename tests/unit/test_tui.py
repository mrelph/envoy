"""Unit tests for tui.py input handling and command dispatch glue.

Covers the H4 (paste/Enter submit heuristic), H5 (escape-to-cancel), and
Medium UI/UX fixes from PROJECT-REVIEW-2026-07-06.md. AI calls and MCP I/O
are never exercised here — `_init_agent` is stubbed at the class level before
mount, and `_submit`/`dispatch` are monkeypatched where the real pipeline
would otherwise run.
"""

import asyncio
import threading

import pytest
from textual import events

import tui
from tui import ChatInput, EnvoyApp, _looks_like_markdown, _should_rerender_as_markdown


def _make_app(monkeypatch):
    """An EnvoyApp with agent init stubbed out so mount never touches MCP/Bedrock."""
    monkeypatch.setattr(EnvoyApp, "_init_agent", lambda self: None)
    return EnvoyApp()


def test_paste_inserts_verbatim_without_double_insert_or_submit(monkeypatch):
    app = _make_app(monkeypatch)
    submitted = []
    app._submit = submitted.append

    async def scenario():
        async with app.run_test() as pilot:
            ta = app.query_one("#input", ChatInput)
            ta.focus()
            app.post_message(events.Paste("line one\nline two\n"))
            await pilot.pause()
            assert ta.text == "line one\nline two\n"  # not duplicated
            assert submitted == []  # trailing \n from paste must not auto-submit
            assert ta.suppress_next_submit is False  # flag consumed exactly once

    asyncio.run(scenario())


def test_alt_enter_inserts_newline_without_submitting(monkeypatch):
    app = _make_app(monkeypatch)
    submitted = []
    app._submit = submitted.append

    async def scenario():
        async with app.run_test() as pilot:
            ta = app.query_one("#input", ChatInput)
            ta.focus()
            ta.insert("hello")
            await pilot.press("alt+enter")
            await pilot.pause()
            assert ta.text == "hello\n"
            assert submitted == []

    asyncio.run(scenario())


def test_enter_submits_alt_enter_composed_multiline_text(monkeypatch):
    app = _make_app(monkeypatch)
    submitted = []
    app._submit = submitted.append

    async def scenario():
        async with app.run_test() as pilot:
            ta = app.query_one("#input", ChatInput)
            ta.focus()
            ta.insert("hello")
            await pilot.press("alt+enter")
            ta.insert("world")
            await pilot.press("enter")
            await pilot.pause()
            assert ta.text == ""  # cleared on submit
            assert submitted == ["hello\nworld"]

    asyncio.run(scenario())


def test_quit_guard_drops_bare_q(monkeypatch):
    app = _make_app(monkeypatch)
    # "q" isn't a recognized quit word, so it falls through to a normal
    # (stubbed) command dispatch rather than quitting.
    monkeypatch.setattr(tui, "dispatch", lambda raw, agent: ("ok", True))
    exits = []
    app.exit = lambda *a, **k: exits.append(True)

    async def scenario():
        async with app.run_test():
            app._submit("q")
            await app.workers.wait_for_complete()
            assert exits == []
            app._submit("quit")
            assert exits == [True]

    asyncio.run(scenario())


def test_quit_guard_exact_match_exit(monkeypatch):
    app = _make_app(monkeypatch)
    exits = []
    app.exit = lambda *a, **k: exits.append(True)

    async def scenario():
        async with app.run_test():
            app._submit("exit")
            assert exits == [True]

    asyncio.run(scenario())


def test_unhandled_system_command_shows_not_available(monkeypatch):
    app = _make_app(monkeypatch)
    monkeypatch.setattr(tui, "dispatch", lambda raw, agent: ("/nope", False))
    notified = []
    app.notify = lambda *a, **k: notified.append(a)

    async def scenario():
        async with app.run_test():
            app._submit("/nope")
            await app.workers.wait_for_complete()
            out_text = app.query_one("#output").lines
            joined = "\n".join(str(line) for line in out_text)
            assert "/nope is not available in the TUI" in joined
            assert notified == []  # no false "done" toast
            assert app._busy is False

    asyncio.run(scenario())


@pytest.mark.parametrize("bad_result", ["Usage: /reply <arg>", "⚠ something went wrong"])
def test_toast_suppressed_for_usage_and_warning_results(monkeypatch, bad_result):
    app = _make_app(monkeypatch)
    monkeypatch.setattr(tui, "dispatch", lambda raw, agent: (bad_result, True))
    notified = []
    app.notify = lambda *a, **k: notified.append(a)

    async def scenario():
        async with app.run_test():
            app._submit("/reply")
            await app.workers.wait_for_complete()
            assert notified == []
            assert app._busy is False

    asyncio.run(scenario())


def test_toast_fires_for_normal_results(monkeypatch):
    app = _make_app(monkeypatch)
    monkeypatch.setattr(tui, "dispatch", lambda raw, agent: ("all good", True))
    notified = []
    app.notify = lambda *a, **k: notified.append(a)

    async def scenario():
        async with app.run_test():
            app._submit("/todo")
            await app.workers.wait_for_complete()
            assert len(notified) == 1
            assert app._busy is False

    asyncio.run(scenario())


def test_backup_command_intercepted_in_tui(monkeypatch, tmp_path):
    app = _make_app(monkeypatch)
    fake_archive = tmp_path / "envoy-backup-20260707.tar.gz"
    fake_archive.write_text("fake")

    import backup
    monkeypatch.setattr(backup, "run_backup", lambda: fake_archive)
    notified = []
    app.notify = lambda *a, **k: notified.append(a)

    async def scenario():
        async with app.run_test():
            app._submit("/backup")
            await app.workers.wait_for_complete()
            out_lines = "\n".join(str(l) for l in app.query_one("#output").lines)
            assert fake_archive.name in out_lines
            assert len(notified) == 1

    asyncio.run(scenario())


def test_backup_no_op_result_does_not_claim_success(monkeypatch):
    app = _make_app(monkeypatch)
    import backup
    monkeypatch.setattr(backup, "run_backup", lambda: None)
    notified = []
    app.notify = lambda *a, **k: notified.append(a)

    async def scenario():
        async with app.run_test():
            app._submit("/backup")
            await app.workers.wait_for_complete()
            out_lines = "\n".join(str(l) for l in app.query_one("#output").lines)
            assert "Nothing to back up" in out_lines
            assert notified == []

    asyncio.run(scenario())


def test_update_notice_shown_when_stamp_present(monkeypatch, envoy_home):
    (envoy_home / "update-available").write_text("v3.3.0\n")
    monkeypatch.setattr(tui, "CONFIG_DIR", envoy_home)
    app = _make_app(monkeypatch)

    async def scenario():
        async with app.run_test():
            out_lines = "\n".join(str(l) for l in app.query_one("#output").lines)
            assert "Envoy v3.3.0 available" in out_lines
            assert "run 'envoy update'" in out_lines

    asyncio.run(scenario())


def test_update_notice_absent_when_no_stamp(monkeypatch, envoy_home):
    monkeypatch.setattr(tui, "CONFIG_DIR", envoy_home)
    app = _make_app(monkeypatch)

    async def scenario():
        async with app.run_test():
            out_lines = "\n".join(str(l) for l in app.query_one("#output").lines)
            assert "available" not in out_lines

    asyncio.run(scenario())


class TestMarkdownDetectionHeuristic:
    """PROJECT-REVIEW item: `- ` alone used to false-positive on plain prose."""

    @pytest.mark.parametrize("text", [
        "just a plain sentence with no markdown at all",
        "day-to-day operations - that's the plan",
        "- a single leading dash, still not enough signal",
        "a pipe | in the middle of a sentence, not a table",
    ])
    def test_plain_prose_is_not_markdown(self, text):
        assert _looks_like_markdown(text) is False

    @pytest.mark.parametrize("text", [
        "# Heading\nsome body text",
        "## Sub heading\nbody",
        "### Third level\nbody",
        "wrapped\n```python\ncode()\n```\nmore",
        "| col1 | col2 |\n| --- | --- |\n| a | b |",
        "one bold word: **hello** stands out",
        "**bold one** and **bold two** in the same reply",
    ])
    def test_strong_signals_are_markdown(self, text):
        assert _looks_like_markdown(text) is True


class TestShouldRerenderAsMarkdown:
    """Factored decision from `_show()` — no duplicate rendering once streamed."""

    def test_never_rerenders_once_anything_streamed(self):
        # Even text with strong markdown signals is skipped once streaming
        # already put the plain-text record on screen.
        assert _should_rerender_as_markdown(True, "# Heading\nbody") is False

    def test_rerenders_non_streamed_markdown_text(self):
        assert _should_rerender_as_markdown(False, "# Heading\nbody") is True

    def test_does_not_rerender_non_streamed_plain_text(self):
        assert _should_rerender_as_markdown(False, "just plain prose - nothing fancy") is False


class TestStreamPendingLockDrain:
    """H/Low item: `_stream_pending` append (worker thread) vs. drain (UI
    thread) must not race — `_flush_stream` should observe every appended
    chunk exactly once even under concurrent appends."""

    def test_concurrent_appends_are_not_lost_or_duplicated(self, monkeypatch):
        app = _make_app(monkeypatch)
        chunks = [f"chunk{i} " for i in range(200)]
        drained = []

        def fake_call_from_thread(fn, *a, **k):
            # In the real app this hops to the UI thread; here we just run
            # it inline so the test can drive `_flush_stream` deterministically.
            return fn(*a, **k)

        app.app.call_from_thread = fake_call_from_thread

        def real_flush():
            with app._stream_lock:
                pending = app._stream_pending
                app._stream_pending = ""
            if pending:
                drained.append(pending)

        monkeypatch.setattr(app, "_flush_stream", real_flush)

        threads = [
            threading.Thread(target=app._ingest_stream_chunk, args=(c,))
            for c in chunks
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Drain whatever's left after all threads finished appending.
        real_flush()

        total = "".join(drained)
        # Every chunk landed exactly once — no chunk lost or duplicated by a
        # torn read/write of `_stream_pending`.
        for c in chunks:
            assert total.count(c) == 1


def test_tool_event_restarts_spinner_during_silent_gap(monkeypatch):
    """Medium item: a tool-use event mid-turn should restart the spinner
    with a friendly label once the initial stream has gone quiet."""
    app = _make_app(monkeypatch)

    async def scenario():
        async with app.run_test():
            app._busy = True
            app._last_text_ts = 0.0  # "long ago" — no recent text
            app._on_tool_event("email_worker")
            spinner = app.query_one("#spinner", tui.Spinner)
            assert spinner._hint  # spinner is showing something
            assert "Email" in spinner._hint or "📧" in spinner._hint

    asyncio.run(scenario())


def test_tool_event_skipped_while_text_actively_streaming(monkeypatch):
    app = _make_app(monkeypatch)

    async def scenario():
        async with app.run_test():
            import time
            app._busy = True
            app._last_text_ts = time.monotonic()  # text just streamed
            app._on_tool_event("email_worker")
            spinner = app.query_one("#spinner", tui.Spinner)
            assert not spinner._hint  # left alone — stream is the indicator

    asyncio.run(scenario())


def test_settings_command_intercepted_in_tui(monkeypatch):
    """Medium item: `/settings` should run the CLI settings flow under
    `self.suspend()`, not punt with a static 'use the CLI' message."""
    app = _make_app(monkeypatch)

    import init_cmd
    calls = []
    monkeypatch.setattr(init_cmd, "run_settings", lambda: calls.append(True))

    class _FakeSuspend:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(app, "suspend", lambda: _FakeSuspend())

    import agent as agent_module
    reload_calls = []
    monkeypatch.setattr(agent_module, "reload_agent", lambda: reload_calls.append(True))
    monkeypatch.setattr(agent_module, "get_agent", lambda: "fake-agent")

    async def scenario():
        async with app.run_test() as pilot:
            app._submit("/settings")
            await pilot.pause()
            assert calls == [True]
            assert reload_calls == [True]
            assert app._agent == "fake-agent"
            out_lines = "\n".join(str(l) for l in app.query_one("#output").lines)
            assert "Use 'envoy settings' from CLI" not in out_lines

    asyncio.run(scenario())


def test_escape_cancels_busy_command(monkeypatch):
    app = _make_app(monkeypatch)
    gate = __import__("threading").Event()

    def slow_dispatch(raw, agent):
        gate.wait(timeout=5)
        return ("late result", True)

    monkeypatch.setattr(tui, "dispatch", slow_dispatch)

    async def scenario():
        async with app.run_test() as pilot:
            app._submit("/todo")
            await pilot.pause()
            assert app._busy is True
            app.action_focus_input()  # Escape binding target
            assert app._busy is False
            out_lines = "\n".join(str(l) for l in app.query_one("#output").lines)
            assert "cancelled" in out_lines
            gate.set()  # let the background thread finish so it doesn't linger
            try:
                await app.workers.wait_for_complete()
            except Exception:
                pass  # the worker was cancelled — that's the point of this test

    asyncio.run(scenario())
