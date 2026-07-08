"""Tests for cli.py — the --verbose flag.

The flag used to be parsed into ctx.obj['verbose'] and never read. It should
now flip envoy_logger's file level to DEBUG (also via ENVOY_VERBOSE=1) and
print a one-line notice. We drive it through a lightweight subcommand
(`logs`) rather than the default no-args path, since the default path
launches the TUI/REPL.
"""

from click.testing import CliRunner

import cli as cli_module
from cli import cli


class _FakeLogger:
    """Records set_level() calls without touching real logging state."""

    def __init__(self):
        self.levels = []

    def set_level(self, level):
        self.levels.append(level)


class TestVerboseFlag:
    def test_verbose_flag_sets_debug_level_and_prints_notice(self, monkeypatch, envoy_home):
        fake_logger = _FakeLogger()
        monkeypatch.setattr(cli_module, "get_logger", lambda: fake_logger)
        runner = CliRunner()
        result = runner.invoke(cli, ["--verbose", "logs"])
        assert result.exit_code == 0
        assert fake_logger.levels == ["DEBUG"]
        assert "verbose logging enabled" in result.output
        assert "~/.envoy/logs/" in result.output

    def test_short_flag_alias_works(self, monkeypatch, envoy_home):
        fake_logger = _FakeLogger()
        monkeypatch.setattr(cli_module, "get_logger", lambda: fake_logger)
        runner = CliRunner()
        result = runner.invoke(cli, ["-v", "logs"])
        assert result.exit_code == 0
        assert fake_logger.levels == ["DEBUG"]

    def test_env_var_enables_verbose_without_flag(self, monkeypatch, envoy_home):
        fake_logger = _FakeLogger()
        monkeypatch.setattr(cli_module, "get_logger", lambda: fake_logger)
        monkeypatch.setenv("ENVOY_VERBOSE", "1")
        runner = CliRunner()
        result = runner.invoke(cli, ["logs"])
        assert result.exit_code == 0
        assert fake_logger.levels == ["DEBUG"]

    def test_no_verbose_by_default(self, monkeypatch, envoy_home):
        fake_logger = _FakeLogger()
        monkeypatch.setattr(cli_module, "get_logger", lambda: fake_logger)
        monkeypatch.delenv("ENVOY_VERBOSE", raising=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["logs"])
        assert result.exit_code == 0
        assert fake_logger.levels == []
        assert "verbose logging enabled" not in result.output

    def test_help_text_describes_debug_logging_not_chain_of_thought(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "chain-of-thought" not in result.output
        assert "DEBUG" in result.output
