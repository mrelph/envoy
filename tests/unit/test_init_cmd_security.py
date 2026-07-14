"""Unit tests for init_cmd.py's secrets-permissions and no-silent-wipe helpers
(PROJECT-REVIEW H3/H9): directory/file chmod, backup-before-overwrite, and
prefilling the VIP list from an existing envoy.md.
"""

import stat

import pytest

import init_cmd


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _redirect(monkeypatch, envoy_home):
    """init_cmd.py captures CONFIG_DIR/SOUL_FILE/ENVOY_FILE/PROCESS_FILE at
    import time from the real Path.home(), so tests must overwrite those
    module-level constants directly (same pattern as test_skills.py)."""
    monkeypatch.setattr(init_cmd, "CONFIG_DIR", envoy_home, raising=True)
    monkeypatch.setattr(init_cmd, "SOUL_FILE", envoy_home / "soul.md", raising=True)
    monkeypatch.setattr(init_cmd, "ENVOY_FILE", envoy_home / "envoy.md", raising=True)
    monkeypatch.setattr(init_cmd, "PROCESS_FILE", envoy_home / "process.md", raising=True)
    monkeypatch.setattr(init_cmd, "_MCP_JSON", envoy_home / "mcp.json", raising=True)


class TestSecureHelpers:
    def test_secure_dir_sets_0700(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        envoy_home.chmod(0o755)
        init_cmd._secure_dir(envoy_home)
        assert _mode(envoy_home) == 0o700

    def test_secure_file_sets_0600(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        f = envoy_home / "envoy.md"
        f.write_text("hi")
        f.chmod(0o644)
        init_cmd._secure_file(f)
        assert _mode(f) == 0o600

    def test_secure_file_missing_path_does_not_raise(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        init_cmd._secure_file(envoy_home / "does-not-exist.md")  # should not raise


class TestSaveUserMcps:
    def test_mcp_json_written_mode_0600(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        init_cmd._save_user_mcps({"Foo": {"command": "foo-server", "args": []}})
        mcp_json = envoy_home / "mcp.json"
        assert mcp_json.exists()
        assert _mode(mcp_json) == 0o600

    def test_config_dir_secured_on_save(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        envoy_home.chmod(0o755)
        init_cmd._save_user_mcps({})
        assert _mode(envoy_home) == 0o700


class TestBackupBeforeOverwrite:
    def test_no_backup_for_missing_file(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        assert init_cmd._backup_before_overwrite(envoy_home / "envoy.md") is None

    def test_no_backup_for_empty_placeholder_file(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        f = envoy_home / "envoy.md"
        f.write_text("   \n")
        assert init_cmd._backup_before_overwrite(f) is None

    def test_backs_up_existing_content_with_timestamp_suffix(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        f = envoy_home / "envoy.md"
        f.write_text("# About Me\n\n- Name: Alice\n")

        backup_path = init_cmd._backup_before_overwrite(f)

        assert backup_path is not None
        assert backup_path.parent == f.parent
        assert backup_path.name.startswith("envoy.md.bak-")
        assert backup_path.read_text() == "# About Me\n\n- Name: Alice\n"
        # Original is untouched by the backup step itself.
        assert f.read_text() == "# About Me\n\n- Name: Alice\n"
        # Backup copy is secured too — it can carry the same PII/secrets.
        assert _mode(backup_path) == 0o600


class TestRunInitRerun:
    """Re-running `envoy init` must not silently wipe config (H9): existing
    values are offered as prompt defaults and both files are backed up
    before being overwritten."""

    _OLD_ENVOY = (
        "# About Me\n\n"
        "- Name: Alice Example\n"
        "- Alias: alice\n"
        "- Role: Principal PM\n"
        "- Manager: Bob Boss\n\n"
        "# High Priority People\n\n"
        "- Bob Jones | bjones | bjones@example.com | Manager\n\n"
        "# Preferences\n\n## Email\n- Ignore: spam\n\n"
        "## SharePoint / OneDrive\n"
        "- Knowledge Folder: Documents/KB\n"
        "- Exports Folder: Documents/Out\n"
    )
    _OLD_SOUL = "# Soul\n\n# Agent Identity\n\n- Agent name: Jeeves\n"

    def _run(self, monkeypatch, envoy_home, tmp_path):
        _redirect(monkeypatch, envoy_home)
        # Empty templates dir: no template copies, no bundled-skill installs.
        empty_templates = tmp_path / "empty_templates"
        empty_templates.mkdir(exist_ok=True)
        monkeypatch.setattr(init_cmd, "TEMPLATES_DIR", empty_templates)
        # Kill all MCP/Phonetool I/O — every lookup site catches exceptions.
        monkeypatch.setattr(
            init_cmd, "run",
            lambda coro: (coro.close(), (_ for _ in ()).throw(RuntimeError("no I/O in tests")))[1],
        )

        prompts = []  # (prompt, default) pairs, in order

        def fake_ask(prompt, default=""):
            prompts.append((prompt, default))
            return default  # user hits Enter everywhere

        monkeypatch.setattr(init_cmd, "_ask", fake_ask)
        init_cmd.run_init()
        return prompts

    def test_rerun_prefills_defaults_from_existing_config(
        self, envoy_home, monkeypatch, tmp_path
    ):
        (envoy_home / "envoy.md").write_text(self._OLD_ENVOY)
        (envoy_home / "soul.md").write_text(self._OLD_SOUL)

        prompts = self._run(monkeypatch, envoy_home, tmp_path)

        defaults = {p: d for p, d in prompts}
        assert defaults["Your alias"] == "alice"
        assert defaults["Your name"] == "Alice Example"
        assert defaults["Your role/title"] == "Principal PM"
        assert defaults["Your manager"] == "Bob Boss"
        assert defaults["Name for your agent (or Enter to keep 'Envoy')"] == "Jeeves"
        assert "bjones" in defaults[
            "People whose emails should always be flagged high priority "
            "(aliases, comma-separated)"
        ]
        assert defaults[
            "Knowledge folder path (e.g., 'Documents/Knowledge' or Enter to skip)"
        ] == "Documents/KB"
        assert defaults[
            "Exports folder path (e.g., 'Documents/Envoy Exports' or Enter to skip)"
        ] == "Documents/Out"

        # Accepting the defaults round-trips the old values into the new file.
        new_envoy = (envoy_home / "envoy.md").read_text()
        assert "- Name: Alice Example" in new_envoy
        assert "- Alias: alice" in new_envoy
        assert "bjones" in new_envoy
        assert "- Knowledge Folder: Documents/KB" in new_envoy

    def test_rerun_backs_up_both_files_before_overwrite(
        self, envoy_home, monkeypatch, tmp_path
    ):
        (envoy_home / "envoy.md").write_text(self._OLD_ENVOY)
        (envoy_home / "soul.md").write_text(self._OLD_SOUL)

        self._run(monkeypatch, envoy_home, tmp_path)

        envoy_baks = list(envoy_home.glob("envoy.md.bak-*"))
        soul_baks = list(envoy_home.glob("soul.md.bak-*"))
        assert len(envoy_baks) == 1, "envoy.md was overwritten without a backup"
        assert len(soul_baks) == 1, "soul.md was overwritten without a backup"
        assert envoy_baks[0].read_text() == self._OLD_ENVOY
        assert soul_baks[0].read_text() == self._OLD_SOUL

    def test_fresh_run_has_no_stale_prefill(self, envoy_home, monkeypatch, tmp_path):
        # soul.md exists as a template placeholder; envoy.md does not exist,
        # so this is a fresh run (is_rerun is False).
        (envoy_home / "soul.md").write_text("# Soul\n\n- Agent name: Stanley\n")

        prompts = self._run(monkeypatch, envoy_home, tmp_path)

        defaults = {p: d for p, d in prompts}
        # A template's placeholder agent name must not pose as a prior choice.
        assert defaults["Name for your agent (or Enter to keep 'Envoy')"] == ""
        # Nothing to back up for a never-written envoy.md. (soul.md may still
        # be backed up — any non-empty file is, which is the safe default.)
        assert not list(envoy_home.glob("envoy.md.bak-*"))
        assert (envoy_home / "envoy.md").exists()


class TestReadVipAliases:
    def test_no_file_returns_empty(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        assert init_cmd._read_vip_aliases(envoy_home / "envoy.md") == ""

    def test_extracts_aliases_from_high_priority_section(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        f = envoy_home / "envoy.md"
        f.write_text(
            "# About Me\n\n- Name: Alice\n\n"
            "# High Priority People\n\n"
            "- Bob Jones | bjones | bjones@example.com | Manager\n"
            "- Carol Lee | clee | clee@example.com | Director\n\n"
            "# Preferences\n\n- Ignore: spam\n"
        )
        assert init_cmd._read_vip_aliases(f) == "bjones, clee"

    def test_no_vip_section_returns_empty(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        f = envoy_home / "envoy.md"
        f.write_text("# About Me\n\n- Name: Alice\n")
        assert init_cmd._read_vip_aliases(f) == ""
