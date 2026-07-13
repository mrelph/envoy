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
