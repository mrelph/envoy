"""Unit tests for backup.py — archive contents, permissions, and safe restore."""

import stat
import tarfile

import pytest

import backup as backup_mod


# --- Helpers ---------------------------------------------------------------

def _redirect(monkeypatch, envoy_home):
    """Point backup.py at the per-test envoy_home dir.

    `backup.py` captures CONFIG_DIR/BACKUP_DIR at import time using the real
    `Path.home()`, so monkeypatching $HOME after import does nothing — the
    module-level constants have to be overwritten directly.
    """
    backup_dir = envoy_home / "backups"
    monkeypatch.setattr(backup_mod, "CONFIG_DIR", envoy_home, raising=True)
    monkeypatch.setattr(backup_mod, "BACKUP_DIR", backup_dir, raising=True)
    return backup_dir


def _mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


# --- run_backup --------------------------------------------------------

class TestRunBackup:
    def test_excludes_dot_env(self, envoy_home, monkeypatch):
        backup_dir = _redirect(monkeypatch, envoy_home)

        (envoy_home / ".env").write_text("AWS_SECRET_ACCESS_KEY=super-secret\n")
        (envoy_home / "soul.md").write_text("# Soul\n")

        archive_path = backup_mod.run_backup()

        assert archive_path is not None
        with tarfile.open(archive_path, "r:gz") as tar:
            names = tar.getnames()
        assert ".env" not in names
        assert "soul.md" in names

    def test_archive_created_mode_0600(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        (envoy_home / "soul.md").write_text("# Soul\n")

        archive_path = backup_mod.run_backup()

        assert archive_path is not None
        assert _mode(archive_path) == 0o600

    def test_nothing_to_back_up_returns_none(self, envoy_home, monkeypatch):
        _redirect(monkeypatch, envoy_home)
        assert backup_mod.run_backup() is None


# --- restore_backup ------------------------------------------------------

class TestRestoreBackupSafety:
    def _make_malicious_archive(self, backup_dir, member_name, content=b"pwned"):
        """Build a .tar.gz whose single member tries to escape CONFIG_DIR."""
        backup_dir.mkdir(parents=True, exist_ok=True)
        archive_path = backup_dir / "envoy-backup-malicious.tar.gz"
        import io
        with tarfile.open(archive_path, "w:gz") as tar:
            info = tarfile.TarInfo(name=member_name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        return archive_path

    def test_rejects_path_traversal_member(self, envoy_home, monkeypatch, capsys):
        backup_dir = _redirect(monkeypatch, envoy_home)
        self._make_malicious_archive(backup_dir, "../../evil.txt")

        backup_mod.restore_backup(name="envoy-backup-malicious.tar.gz")

        # The traversal target must not land anywhere outside envoy_home.
        escaped = envoy_home.parent.parent / "evil.txt"
        assert not escaped.exists()
        assert not (envoy_home.parent / "evil.txt").exists()

    def test_rejects_absolute_path_member(self, envoy_home, monkeypatch, tmp_path):
        backup_dir = _redirect(monkeypatch, envoy_home)
        outside_target = tmp_path / "outside-evil.txt"
        self._make_malicious_archive(backup_dir, str(outside_target))

        backup_mod.restore_backup(name="envoy-backup-malicious.tar.gz")

        assert not outside_target.exists()

    def test_restores_safe_members_normally(self, envoy_home, monkeypatch):
        backup_dir = _redirect(monkeypatch, envoy_home)
        (envoy_home / "soul.md").write_text("# Soul\n")
        archive_path = backup_mod.run_backup()
        (envoy_home / "soul.md").write_text("# Overwritten\n")

        backup_mod.restore_backup(name=archive_path.name)

        assert (envoy_home / "soul.md").read_text() == "# Soul\n"
