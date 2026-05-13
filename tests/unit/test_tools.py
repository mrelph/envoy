"""Unit tests for tools.py — _load_config, _allowed_dirs, _config_has_similar,
update_soul / update_envoy / update_process, and the security-critical
manage_cron command/schedule validator.

Most of tools.py is @tool-decorated MCP routers and isn't unit-testable; this
file covers the pure helpers and the cron validator.
"""

import json
import os

import pytest

import tools


# ---------------------------------------------------------------------------
# _load_config / _allowed_dirs
# ---------------------------------------------------------------------------

def _patch_config_file(monkeypatch, envoy_home):
    """Redirect tools._CONFIG_FILE to live under the per-test envoy_home."""
    fake_path = str(envoy_home / "config.json")
    monkeypatch.setattr(tools, "_CONFIG_FILE", fake_path)
    return fake_path


class TestLoadConfig:
    def test_no_config_file_returns_empty_dict(self, envoy_home, monkeypatch):
        _patch_config_file(monkeypatch, envoy_home)
        assert tools._load_config() == {}

    def test_parses_valid_config(self, envoy_home, monkeypatch):
        path = _patch_config_file(monkeypatch, envoy_home)
        with open(path, "w") as f:
            json.dump({"allowed_dirs": ["~/foo", "~/bar"], "other": 1}, f)
        cfg = tools._load_config()
        assert cfg["allowed_dirs"] == ["~/foo", "~/bar"]
        assert cfg["other"] == 1

    def test_malformed_json_returns_empty_dict(self, envoy_home, monkeypatch):
        path = _patch_config_file(monkeypatch, envoy_home)
        with open(path, "w") as f:
            f.write("{not: valid json,,,")
        # Should swallow the JSON error and return {}
        assert tools._load_config() == {}

    def test_empty_file_returns_empty_dict(self, envoy_home, monkeypatch):
        path = _patch_config_file(monkeypatch, envoy_home)
        open(path, "w").close()
        assert tools._load_config() == {}


class TestAllowedDirs:
    def test_no_config_returns_empty_list(self, envoy_home, monkeypatch):
        _patch_config_file(monkeypatch, envoy_home)
        assert tools._allowed_dirs() == []

    def test_returns_configured_dirs(self, envoy_home, monkeypatch):
        path = _patch_config_file(monkeypatch, envoy_home)
        with open(path, "w") as f:
            json.dump({"allowed_dirs": ["/tmp/a", "/tmp/b"]}, f)
        assert tools._allowed_dirs() == ["/tmp/a", "/tmp/b"]

    def test_config_without_allowed_dirs_key(self, envoy_home, monkeypatch):
        path = _patch_config_file(monkeypatch, envoy_home)
        with open(path, "w") as f:
            json.dump({"some_other_key": 42}, f)
        assert tools._allowed_dirs() == []

    def test_malformed_config_returns_empty_list(self, envoy_home, monkeypatch):
        path = _patch_config_file(monkeypatch, envoy_home)
        with open(path, "w") as f:
            f.write("garbage")
        assert tools._allowed_dirs() == []


# ---------------------------------------------------------------------------
# _config_has_similar
# ---------------------------------------------------------------------------

class TestConfigHasSimilar:
    def test_missing_file_returns_empty(self, envoy_home):
        path = str(envoy_home / "no_such_file.md")
        assert tools._config_has_similar(path, "be polite to customers") == ""

    def test_identical_rule_returns_match(self, envoy_home):
        path = str(envoy_home / "soul.md")
        with open(path, "w") as f:
            f.write("# soul\n- be polite to customers always\n")
        result = tools._config_has_similar(path, "be polite to customers always")
        assert result == "be polite to customers always"

    def test_dissimilar_rule_returns_empty(self, envoy_home):
        path = str(envoy_home / "soul.md")
        with open(path, "w") as f:
            f.write("- always reply within 24 hours\n")
        # Totally different topic and words => no overlap above 0.6
        assert tools._config_has_similar(path, "use British spelling in emails") == ""

    def test_short_new_rule_returns_empty(self, envoy_home):
        # Function bails out when new_rule has fewer than 2 words
        path = str(envoy_home / "soul.md")
        with open(path, "w") as f:
            f.write("- something\n")
        assert tools._config_has_similar(path, "hi") == ""

    def test_ignores_lines_not_starting_with_dash(self, envoy_home):
        path = str(envoy_home / "soul.md")
        with open(path, "w") as f:
            f.write("# header\nsome free text rule about customers\n")
        # Even though words overlap, the line doesn't start with "- " so it's skipped
        assert tools._config_has_similar(path, "free text rule about customers") == ""

    def test_partial_overlap_above_threshold(self, envoy_home):
        path = str(envoy_home / "soul.md")
        with open(path, "w") as f:
            f.write("- always reply quickly to vips\n")
        # 5 words new, 5 words existing, 4 shared => 4/6 = 0.66 >= 0.6
        result = tools._config_has_similar(path, "always reply quickly to customers")
        assert result == "always reply quickly to vips"


# ---------------------------------------------------------------------------
# update_soul / update_envoy / update_process
# ---------------------------------------------------------------------------

class TestUpdateSoul:
    def test_appends_rule_to_soul_md(self, envoy_home):
        result = tools.update_soul("speak in plain English")
        soul = (envoy_home / "soul.md").read_text()
        assert "- speak in plain English" in soul
        assert "Updated soul" in result

    def test_dedupes_similar_rule(self, envoy_home):
        tools.update_soul("speak in plain English always")
        result = tools.update_soul("speak in plain English always")
        assert "Similar rule already exists" in result


class TestUpdateEnvoy:
    def test_appends_preference_to_envoy_md(self, envoy_home):
        result = tools.update_envoy("favorite Slack channel is #team-foo")
        envoy = (envoy_home / "envoy.md").read_text()
        assert "- favorite Slack channel is #team-foo" in envoy
        assert "Updated preferences" in result


class TestUpdateProcess:
    def test_creates_process_md_when_missing(self, envoy_home, monkeypatch):
        # Make sure the templates dir lookup doesn't shortcut us into copying a real
        # template — point the templates dir at a nonexistent location.
        monkeypatch.setattr(
            tools.os.path, "dirname",
            lambda p: str(envoy_home / "no_templates_here"),
        )
        result = tools.update_process("archive newsletters older than 30 days", section="Email")
        process = (envoy_home / "process.md").read_text()
        assert "## Email" in process
        assert "- archive newsletters older than 30 days" in process
        assert "Created process memory" in result or "Updated process memory" in result

    def test_appends_under_existing_section(self, envoy_home):
        path = envoy_home / "process.md"
        path.write_text("# Process Memory\n\n## Email\n- existing rule about something\n")
        result = tools.update_process("flag VIP mail with red label", section="Email")
        text = path.read_text()
        assert "flag VIP mail with red label" in text
        assert "existing rule about something" in text
        assert "Updated process memory" in result


# ---------------------------------------------------------------------------
# manage_cron
# ---------------------------------------------------------------------------

class _FakeProc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def cron_recorder(monkeypatch):
    """Replace subprocess.run inside tools.manage_cron with a recorder.

    Records every call. By default returns an empty crontab on `crontab -l`
    and success on `crontab -`.
    """
    class _Recorder(list):
        pass

    state = {"crontab": ""}
    calls = _Recorder()

    def fake_run(cmd, *args, **kwargs):
        calls.append({"cmd": list(cmd), "input": kwargs.get("input")})
        if cmd[:2] == ["crontab", "-l"]:
            return _FakeProc(stdout=state["crontab"])
        if cmd[:2] == ["crontab", "-"]:
            state["crontab"] = kwargs.get("input", "") or ""
            return _FakeProc(returncode=0)
        return _FakeProc()

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    calls.state = state
    return calls


class TestManageCronListAndPresets:
    def test_presets_action_lists_templates(self, cron_recorder):
        out = tools.manage_cron(action="presets")
        assert "morning-briefing" in out
        assert "weekly-digest" in out

    def test_list_with_no_jobs(self, cron_recorder):
        out = tools.manage_cron(action="list")
        assert "No Envoy cron jobs" in out

    def test_list_returns_existing_jobs(self, cron_recorder):
        cron_recorder.state["crontab"] = (
            "0 8 * * *  /usr/bin/envoy digest --days 7  # envoy: morning-brief\n"
            "* * * * *  /something/else  # not us\n"
        )
        out = tools.manage_cron(action="list")
        assert "morning-brief" in out
        assert "0 8 * * *" in out
        # Does not include the non-envoy line
        assert "something/else" not in out


class TestManageCronAddValid:
    def test_valid_add_writes_crontab(self, cron_recorder):
        out = tools.manage_cron(
            action="add", name="test", schedule="0 8 * * *", command="digest --days 7"
        )
        assert "Added cron job 'test'" in out
        # The fake recorder captured a `crontab -` write
        writes = [c for c in cron_recorder if c["cmd"][:2] == ["crontab", "-"]]
        assert writes, "Expected a write to crontab"
        written = writes[-1]["input"]
        assert "# envoy: test" in written
        assert "digest --days 7" in written
        assert "0 8 * * *" in written

    def test_strips_optional_leading_envoy_word(self, cron_recorder):
        out = tools.manage_cron(
            action="add", name="cleanup", schedule="0 16 * * 5",
            command="envoy cleanup --days 7",
        )
        assert "Added cron job 'cleanup'" in out

    def test_replaces_existing_job_with_same_name(self, cron_recorder):
        cron_recorder.state["crontab"] = (
            "0 7 * * *  /usr/bin/envoy digest --days 1  # envoy: morning\n"
        )
        out = tools.manage_cron(
            action="add", name="morning", schedule="0 9 * * *", command="digest --days 2"
        )
        assert "Added cron job 'morning'" in out
        written = [c for c in cron_recorder if c["cmd"][:2] == ["crontab", "-"]][-1]["input"]
        # Old line is gone, new one is present
        assert "0 7 * * *" not in written
        assert "0 9 * * *" in written
        # Only one job named 'morning' in the result
        assert written.count("# envoy: morning") == 1


class TestManageCronAddRejection:
    """Security: shell metacharacter and whitelist enforcement."""

    @pytest.mark.parametrize("bad_cmd", [
        "digest; rm -rf /",
        "digest | cat /etc/passwd",
        "digest && rm -rf /",
        "digest $(whoami)",
        "digest `whoami`",
        "digest > /tmp/out",
        "digest < /etc/passwd",
        "digest --days 7\nrm -rf /",
        "digest {a,b}",
        "digest !bang",
    ])
    def test_rejects_shell_metacharacters_in_command(self, cron_recorder, bad_cmd):
        out = tools.manage_cron(
            action="add", name="x", schedule="0 8 * * *", command=bad_cmd
        )
        assert out.startswith("Rejected"), f"Expected rejection for {bad_cmd!r}, got: {out}"
        # And no crontab write happened
        writes = [c for c in cron_recorder if c["cmd"][:2] == ["crontab", "-"]]
        assert not writes, f"Should not write crontab for unsafe command: {bad_cmd!r}"

    @pytest.mark.parametrize("bad_first", [
        "bash -c something",
        "rm -rf /",
        "ls /etc",
        "python -c 'evil'",
        "envoyz digest",  # close-but-not-allowed subcommand
    ])
    def test_rejects_non_whitelisted_first_word(self, cron_recorder, bad_first):
        out = tools.manage_cron(
            action="add", name="x", schedule="0 8 * * *", command=bad_first
        )
        assert out.startswith("Rejected"), f"Expected rejection for {bad_first!r}"
        writes = [c for c in cron_recorder if c["cmd"][:2] == ["crontab", "-"]]
        assert not writes

    @pytest.mark.parametrize("bad_sched", [
        "invalid",
        "0 8",                   # only 2 fields
        "0 8 * * 1-5 extra",     # 6 fields
        "0 8 * *",               # 4 fields
        "@daily",                # @-shortcuts not allowed
        "",                      # empty schedule
    ])
    def test_rejects_malformed_schedule(self, cron_recorder, bad_sched):
        out = tools.manage_cron(
            action="add", name="x", schedule=bad_sched, command="digest --days 1"
        )
        # Empty schedule short-circuits earlier with the "Need name, schedule, command" error
        assert out.startswith("Rejected") or "Need name" in out, (
            f"Expected rejection for schedule {bad_sched!r}, got: {out}"
        )
        writes = [c for c in cron_recorder if c["cmd"][:2] == ["crontab", "-"]]
        assert not writes

    @pytest.mark.parametrize("bad_sched", [
        "0 8 * * 1;5",
        "0 8 * * `whoami`",
        "0 8 * * $(id)",
    ])
    def test_rejects_metacharacters_in_schedule(self, cron_recorder, bad_sched):
        out = tools.manage_cron(
            action="add", name="x", schedule=bad_sched, command="digest --days 1"
        )
        assert out.startswith("Rejected")

    @pytest.mark.parametrize("bad_name", [
        "name with space",
        "evil;name",
        "name$",
        "name/slash",
        "name.dot",
    ])
    def test_rejects_unsafe_name(self, cron_recorder, bad_name):
        out = tools.manage_cron(
            action="add", name=bad_name, schedule="0 8 * * *", command="digest --days 1"
        )
        assert out.startswith("Rejected")

    def test_missing_args_returns_helpful_error(self, cron_recorder):
        out = tools.manage_cron(action="add", name="", schedule="", command="")
        assert "Need name, schedule, and command" in out


class TestManageCronRemove:
    def test_remove_nonexistent_returns_friendly_error(self, cron_recorder):
        out = tools.manage_cron(action="remove", name="nope")
        assert "No job named 'nope'" in out

    def test_remove_without_name(self, cron_recorder):
        out = tools.manage_cron(action="remove", name="")
        assert "Need name" in out

    def test_remove_existing_job(self, cron_recorder):
        cron_recorder.state["crontab"] = (
            "0 8 * * *  /usr/bin/envoy digest --days 7  # envoy: morning\n"
            "0 9 * * *  /usr/bin/envoy cleanup  # envoy: tidy\n"
        )
        out = tools.manage_cron(action="remove", name="morning")
        assert "Removed cron job 'morning'" in out
        written = [c for c in cron_recorder if c["cmd"][:2] == ["crontab", "-"]][-1]["input"]
        assert "# envoy: morning" not in written
        assert "# envoy: tidy" in written

    def test_remove_with_unsafe_name(self, cron_recorder):
        out = tools.manage_cron(action="remove", name="bad name; rm -rf /")
        assert out.startswith("Rejected")


class TestManageCronUnknown:
    def test_unknown_action(self, cron_recorder):
        out = tools.manage_cron(action="explode")
        assert "Unknown action" in out
