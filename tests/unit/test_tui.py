"""Unit tests for tui.py input handling and command dispatch glue.

Covers the H4 (paste/Enter submit heuristic), H5 (escape-to-cancel), and
Medium UI/UX fixes from PROJECT-REVIEW-2026-07-06.md. AI calls and MCP I/O
are never exercised here — `_init_agent` is stubbed at the class level before
mount, and `_submit`/`dispatch` are monkeypatched where the real pipeline
would otherwise run.
"""

import asyncio

import pytest
from textual import events

import tui
from tui import ChatInput, EnvoyApp


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
