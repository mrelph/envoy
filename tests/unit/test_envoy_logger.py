"""Tests for envoy_logger.py — secret redaction and log file/dir permissions.

Covers:
  1. _redact_value — recursive redaction of sensitive dict keys
  2. _sanitize_args — the tool-arg logging path (nested dicts + repr fallback)
  3. _redact_repr — regex redaction for non-JSON-serializable repr() output
  4. Log directory/file permissions (0700 / 0600) on create + rotation
  5. set_level — runtime level bump (wired up by cli.py's --verbose)
"""

import logging
import os
import stat

import pytest

from envoy_logger import (
    EnvoyLogger,
    _redact_repr,
    _redact_value,
    _sanitize_args,
)


# =========================================================================
# 1. _redact_value — recursive dict/list redaction
# =========================================================================

class TestRedactValue:
    def test_redacts_top_level_sensitive_key(self):
        assert _redact_value({"password": "hunter2"}) == {"password": "***REDACTED***"}

    def test_redacts_nested_dict(self):
        data = {"user": "bob", "auth": {"api_key": "abc123", "note": "keep"}}
        redacted = _redact_value(data)
        assert redacted["auth"]["api_key"] == "***REDACTED***"
        assert redacted["auth"]["note"] == "keep"
        assert redacted["user"] == "bob"

    def test_redacts_within_list_of_dicts(self):
        data = {"items": [{"token": "t1"}, {"safe": "ok"}]}
        redacted = _redact_value(data)
        assert redacted["items"][0]["token"] == "***REDACTED***"
        assert redacted["items"][1]["safe"] == "ok"

    def test_redacts_deeply_nested_structure(self):
        data = {"a": {"b": {"c": [{"secret": "shh"}, {"password": "p1"}]}}}
        redacted = _redact_value(data)
        inner = redacted["a"]["b"]["c"]
        assert inner[0]["secret"] == "***REDACTED***"
        assert inner[1]["password"] == "***REDACTED***"

    def test_case_insensitive_and_key_variants(self):
        data = {
            "Authorization": "Bearer xyz",
            "client_secret": "s3cr3t",
            "API-KEY": "k1",
            "credentials": "c1",
        }
        redacted = _redact_value(data)
        assert all(v == "***REDACTED***" for v in redacted.values())

    def test_leaves_non_sensitive_values_untouched(self):
        data = {"name": "Alice", "count": 3}
        assert _redact_value(data) == data

    def test_non_dict_non_list_values_pass_through(self):
        assert _redact_value("plain string") == "plain string"
        assert _redact_value(42) == 42


# =========================================================================
# 2. _sanitize_args — the tool-call logging path
# =========================================================================

class TestSanitizeArgs:
    def test_sanitize_args_redacts_nested_secret(self):
        args = {"config": {"password": "hunter2", "host": "example.com"}}
        sanitized = _sanitize_args(args)
        assert sanitized["config"]["password"] == "***REDACTED***"
        assert sanitized["config"]["host"] == "example.com"

    def test_sanitize_args_redacts_top_level_secret(self):
        args = {"api_key": "sk-live-12345", "region": "us-west-2"}
        sanitized = _sanitize_args(args)
        assert sanitized["api_key"] == "***REDACTED***"
        assert sanitized["region"] == "us-west-2"

    def test_sanitize_args_keeps_normal_values(self):
        args = {"days": 7, "name": "digest"}
        assert _sanitize_args(args) == args

    def test_sanitize_args_repr_fallback_redacts_kv_pairs(self):
        class Weird:
            def __repr__(self):
                return "Weird(token='abc123', name='bob')"

        sanitized = _sanitize_args({"thing": Weird()})
        assert "abc123" not in sanitized["thing"]
        assert "***REDACTED***" in sanitized["thing"]
        assert "bob" in sanitized["thing"]

    def test_sanitize_args_repr_fallback_still_used_for_unserializable(self):
        class Blob:
            def __repr__(self):
                return "Blob(id=42)"

        sanitized = _sanitize_args({"thing": Blob()})
        assert sanitized["thing"] == "Blob(id=42)"


# =========================================================================
# 3. _redact_repr — regex redaction for repr() fallback strings
# =========================================================================

class TestRedactRepr:
    def test_redacts_single_quoted_kv(self):
        text = "Config(token='abc123', name='bob')"
        result = _redact_repr(text)
        assert "abc123" not in result
        assert "bob" in result
        assert "***REDACTED***" in result

    def test_redacts_json_style_kv(self):
        text = '{"password": "hunter2", "user": "alice"}'
        result = _redact_repr(text)
        assert "hunter2" not in result
        assert "alice" in result

    def test_redacts_unquoted_kv(self):
        text = "api_key=sk-12345 region=us-west-2"
        result = _redact_repr(text)
        assert "sk-12345" not in result
        assert "us-west-2" in result

    def test_leaves_non_sensitive_text_untouched(self):
        text = "Response(status=200, body='hello world')"
        assert _redact_repr(text) == text

    def test_never_raises_on_odd_input(self):
        # Best-effort — must not blow up logging even on garbage (non-str) input.
        assert _redact_repr(12345) == 12345


# =========================================================================
# 4. Log directory / file permissions
# =========================================================================

class TestLogPermissions:
    def test_log_dir_created_with_0700(self, tmp_path):
        log_dir = tmp_path / "logs"
        EnvoyLogger(log_dir=str(log_dir))
        mode = stat.S_IMODE(os.stat(log_dir).st_mode)
        assert mode == 0o700

    def test_log_file_created_with_0600(self, tmp_path):
        log_dir = tmp_path / "logs"
        logger = EnvoyLogger(log_dir=str(log_dir))
        log_file = logger._file_handler.baseFilename
        mode = stat.S_IMODE(os.stat(log_file).st_mode)
        assert mode == 0o600

    def test_permissions_survive_pre_existing_world_readable_dir(self, tmp_path):
        """Even if the dir already existed with looser perms (e.g. pre-upgrade
        installs), init should tighten it to 0700."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(mode=0o777)
        os.chmod(log_dir, 0o777)
        EnvoyLogger(log_dir=str(log_dir))
        mode = stat.S_IMODE(os.stat(log_dir).st_mode)
        assert mode == 0o700


# =========================================================================
# 5. set_level — runtime DEBUG bump (cli.py's --verbose wiring)
# =========================================================================

class TestSetLevel:
    def test_set_level_updates_file_handler(self, tmp_path):
        logger = EnvoyLogger(log_dir=str(tmp_path / "logs"), file_level="INFO")
        assert logger._file_handler.level == logging.INFO
        logger.set_level("DEBUG")
        assert logger._file_handler.level == logging.DEBUG

    def test_set_level_invalid_value_falls_back_to_debug(self, tmp_path):
        logger = EnvoyLogger(log_dir=str(tmp_path / "logs"))
        logger.set_level("not-a-level")
        assert logger._file_handler.level == logging.DEBUG
