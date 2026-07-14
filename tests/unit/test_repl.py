"""Unit tests for repl.py's interactive loop (PROJECT-REVIEW H10):
a dispatch() exception (Bedrock throttle, expired creds, …) must print a
graceful warning and keep the loop alive — never a raw traceback — while
EOF/Ctrl-C at the prompt still exit cleanly.
"""

import builtins

import pytest

import repl
import ui


class _ScriptedInput:
    """Feed a fixed sequence of lines to input(); raise EOFError when done."""

    def __init__(self, lines):
        self._lines = iter(lines)

    def __call__(self, prompt=""):
        try:
            return next(self._lines)
        except StopIteration:
            raise EOFError


@pytest.fixture
def quiet_repl(monkeypatch):
    """Stub out the agent + MCP status check so run_interactive is pure I/O."""
    monkeypatch.setattr(ui, "_check_mcp_servers", lambda: {})
    monkeypatch.setattr(repl, "get_agent", lambda: object())
    monkeypatch.setattr(repl, "reload_agent", lambda: None)


class TestDispatchErrorHandling:
    def test_dispatch_exception_prints_warning_and_loop_continues(
        self, quiet_repl, monkeypatch, capsys
    ):
        calls = []

        def flaky_dispatch(text, agent):
            calls.append(text)
            if len(calls) == 1:
                raise RuntimeError("ThrottlingException: too many requests")
            return ("all good", True)

        monkeypatch.setattr(repl, "dispatch", flaky_dispatch)
        monkeypatch.setattr(builtins, "input", _ScriptedInput(["first", "second"]))

        repl.run_interactive()  # must not raise

        out = capsys.readouterr().out
        assert "⚠ RuntimeError: ThrottlingException: too many requests" in out
        # The loop survived the exception and processed the next line.
        assert calls == ["first", "second"]
        assert "all good" in out

    def test_expired_credentials_style_error_does_not_crash(
        self, quiet_repl, monkeypatch, capsys
    ):
        class ExpiredTokenException(Exception):
            pass

        def dead_dispatch(text, agent):
            raise ExpiredTokenException("The security token included in the request is expired")

        monkeypatch.setattr(repl, "dispatch", dead_dispatch)
        monkeypatch.setattr(builtins, "input", _ScriptedInput(["do something"]))

        repl.run_interactive()  # must not raise

        out = capsys.readouterr().out
        assert "⚠ ExpiredTokenException" in out

    def test_unhandled_command_prints_not_available(self, quiet_repl, monkeypatch, capsys):
        monkeypatch.setattr(repl, "dispatch", lambda text, agent: (None, False))
        monkeypatch.setattr(builtins, "input", _ScriptedInput(["/bogus arg"]))

        repl.run_interactive()

        assert "/bogus is not available in this interface" in capsys.readouterr().out


class TestCleanExit:
    def test_eof_at_prompt_exits_cleanly(self, quiet_repl, monkeypatch, capsys):
        monkeypatch.setattr(builtins, "input", _ScriptedInput([]))  # immediate EOF
        repl.run_interactive()
        assert "Goodbye!" in capsys.readouterr().out

    def test_keyboard_interrupt_at_prompt_exits_cleanly(self, quiet_repl, monkeypatch, capsys):
        def ctrl_c(prompt=""):
            raise KeyboardInterrupt

        monkeypatch.setattr(builtins, "input", ctrl_c)
        repl.run_interactive()
        assert "Goodbye!" in capsys.readouterr().out

    def test_quit_command_exits(self, quiet_repl, monkeypatch, capsys):
        monkeypatch.setattr(
            repl, "dispatch",
            lambda text, agent: (_ for _ in ()).throw(AssertionError("dispatch must not run")),
        )
        monkeypatch.setattr(builtins, "input", _ScriptedInput(["/quit"]))
        repl.run_interactive()
        assert "Goodbye!" in capsys.readouterr().out
