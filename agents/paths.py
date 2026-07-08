"""Centralized ~/.envoy path resolution.

Tiny, dependency-free module (stdlib only: os, pathlib) so it can be
imported from anywhere in the codebase — including modules that must stay
free of heavy imports (strands, mcp, boto3) — without side effects.

The config directory defaults to ``~/.envoy`` but can be relocated with the
``ENVOY_CONFIG`` environment variable (e.g. for tests, multiple profiles, or
an alternate machine layout).

Two flavors are provided for every well-known path:

* Module-level constants (``CONFIG_DIR``, ``SOUL_FILE``, ``SESSIONS_DIR``,
  ...) resolved once at import time. These mirror the module-level
  constants that used to be scattered across the codebase (e.g.
  ``CONFIG_DIR = Path.home() / ".envoy"`` in half a dozen files) — callers
  that import them keep exactly that pattern, including tests that
  ``monkeypatch.setattr(some_module, "CONFIG_DIR", tmp_dir)`` to sandbox a
  single module.
* Functions (``config_dir()``, ``soul_file()``, ``sessions_dir()``, ...)
  that re-read ``ENVOY_CONFIG``/``$HOME`` on every call. Use these from any
  call site that currently resolves its path lazily inside a function body
  (rather than caching it in a module-level constant) — switching such a
  site to the cached constant would silently stop honoring a per-test
  ``$HOME`` redirect (see tests/conftest.py's ``envoy_home`` fixture) that
  happens *after* this module was first imported.
"""

import os
from pathlib import Path


def config_dir() -> Path:
    """Return the Envoy config directory, re-read from the environment every call."""
    return Path(os.environ.get("ENVOY_CONFIG", "~/.envoy")).expanduser()


def soul_file() -> Path:
    return config_dir() / "soul.md"


def envoy_file() -> Path:
    return config_dir() / "envoy.md"


def process_file() -> Path:
    return config_dir() / "process.md"


def models_file() -> Path:
    return config_dir() / "models.json"


def mcp_file() -> Path:
    return config_dir() / "mcp.json"


def env_file() -> Path:
    return config_dir() / ".env"


def sessions_dir() -> Path:
    return config_dir() / "sessions"


def memory_dir() -> Path:
    return config_dir() / "memory"


def skills_dir() -> Path:
    return config_dir() / "skills"


def logs_dir() -> Path:
    return config_dir() / "logs"


def backups_dir() -> Path:
    return config_dir() / "backups"


def pending_rules_file() -> Path:
    return config_dir() / "pending_rules.json"


def sent_file() -> Path:
    return config_dir() / "sent.json"


def commands_file() -> Path:
    return config_dir() / "commands.md"


def update_stamp() -> Path:
    return config_dir() / "update-available"


def config_json_file() -> Path:
    return config_dir() / "config.json"


CONFIG_JSON_FILE = config_json_file()


def exports_dir() -> Path:
    return config_dir() / "exports"


# --- Module-level constants (resolved once, at import time) ---
#
# Prefer these when replacing a module's own pre-existing module-level
# constant of the same name (they're a drop-in alias) — most such constants
# are already re-pointed per-test via monkeypatch.setattr(module, "NAME",
# tmp_path), which works identically whether the module defines the name
# itself or imports it from here.

CONFIG_DIR = config_dir()
SOUL_FILE = soul_file()
ENVOY_FILE = envoy_file()
PROCESS_FILE = process_file()
MODELS_FILE = models_file()
MCP_FILE = mcp_file()
ENV_FILE = env_file()
SESSIONS_DIR = sessions_dir()
MEMORY_DIR = memory_dir()
SKILLS_DIR = skills_dir()
LOGS_DIR = logs_dir()
BACKUPS_DIR = backups_dir()
PENDING_RULES_FILE = pending_rules_file()
SENT_FILE = sent_file()
COMMANDS_FILE = commands_file()
UPDATE_STAMP = update_stamp()
