"""Unit tests for agents/paths.py — the centralized ~/.envoy path resolver.

Covers:
  * default resolution (~/.envoy under $HOME) via the envoy_home fixture
  * ENVOY_CONFIG override
  * that every named constant/function lands inside the resolved config dir

agents.paths has no heavy deps, so it's safe to `importlib.reload()` freely
in these tests without touching strands/mcp/boto3 stubs.
"""

import importlib

import pytest


@pytest.fixture
def paths(envoy_home):
    """Import (and reload) agents.paths after $HOME has been sandboxed.

    agents.paths may already have been imported by another module earlier in
    the test session (with the real $HOME), so its module-level constants
    need a fresh import to reflect envoy_home. The live functions
    (config_dir(), soul_file(), ...) don't need this — they re-read the
    environment on every call — but reloading keeps both flavors consistent
    for assertions below.
    """
    import agents.paths as paths_mod
    importlib.reload(paths_mod)
    return paths_mod


# ---------------------------------------------------------------------------
# Default resolution: ~/.envoy under $HOME
# ---------------------------------------------------------------------------

class TestDefaultResolution:
    def test_config_dir_function_matches_envoy_home(self, envoy_home, paths):
        assert paths.config_dir() == envoy_home

    def test_config_dir_constant_matches_envoy_home_after_reload(self, envoy_home, paths):
        assert paths.CONFIG_DIR == envoy_home

    def test_config_dir_function_is_live_without_reload(self, envoy_home):
        """Even without reloading the module, config_dir() re-reads $HOME
        every call — that's the whole point of the function flavor."""
        import agents.paths as paths_mod
        assert paths_mod.config_dir() == envoy_home


# ---------------------------------------------------------------------------
# ENVOY_CONFIG override
# ---------------------------------------------------------------------------

class TestEnvoyConfigOverride:
    def test_config_dir_function_respects_envoy_config(self, envoy_home, monkeypatch, tmp_path):
        custom = tmp_path / "custom-envoy-config"
        monkeypatch.setenv("ENVOY_CONFIG", str(custom))
        import agents.paths as paths_mod
        assert paths_mod.config_dir() == custom

    def test_envoy_config_supports_tilde_expansion(self, envoy_home, monkeypatch):
        monkeypatch.setenv("ENVOY_CONFIG", "~/custom-envoy-config")
        import agents.paths as paths_mod
        assert paths_mod.config_dir() == envoy_home.parent / "custom-envoy-config"

    def test_module_constants_respect_envoy_config_after_reload(self, envoy_home, monkeypatch, tmp_path):
        # Module-level constants are resolved once, at import/reload time —
        # unlike config_dir(), they don't pick up a later env var change
        # without a reload. monkeypatch tears ENVOY_CONFIG back down (and the
        # `paths` fixture reloads fresh under envoy_home) before any other
        # test runs, so this reload doesn't leak into later tests.
        custom = tmp_path / "custom-envoy-config"
        monkeypatch.setenv("ENVOY_CONFIG", str(custom))
        import agents.paths as paths_mod
        importlib.reload(paths_mod)
        assert paths_mod.CONFIG_DIR == custom
        assert paths_mod.SOUL_FILE == custom / "soul.md"

    def test_unset_envoy_config_falls_back_to_dot_envoy(self, envoy_home, monkeypatch):
        monkeypatch.delenv("ENVOY_CONFIG", raising=False)
        import agents.paths as paths_mod
        assert paths_mod.config_dir() == envoy_home


# ---------------------------------------------------------------------------
# Every constant/function lands inside the resolved config dir
# ---------------------------------------------------------------------------

_FILE_FUNCS = [
    "soul_file", "envoy_file", "process_file", "models_file", "mcp_file",
    "env_file", "sessions_dir", "memory_dir", "skills_dir", "logs_dir",
    "backups_dir", "pending_rules_file", "sent_file", "commands_file",
    "update_stamp", "config_json_file", "exports_dir",
]

_CONSTANT_NAMES = [
    "SOUL_FILE", "ENVOY_FILE", "PROCESS_FILE", "MODELS_FILE", "MCP_FILE",
    "ENV_FILE", "SESSIONS_DIR", "MEMORY_DIR", "SKILLS_DIR", "LOGS_DIR",
    "BACKUPS_DIR", "PENDING_RULES_FILE", "SENT_FILE", "COMMANDS_FILE",
    "UPDATE_STAMP", "CONFIG_JSON_FILE",
]


class TestFunctionsPointInsideConfigDir:
    @pytest.mark.parametrize("func_name", _FILE_FUNCS)
    def test_function_result_is_under_config_dir(self, envoy_home, paths, func_name):
        fn = getattr(paths, func_name)
        result = fn()
        assert result.parent == envoy_home or result == envoy_home
        # Every one of these is a file/dir directly under CONFIG_DIR.
        assert envoy_home in result.parents or result == envoy_home

    def test_function_results_are_all_distinct_paths(self, envoy_home, paths):
        results = {getattr(paths, name)() for name in _FILE_FUNCS}
        assert len(results) == len(_FILE_FUNCS)


class TestConstantsPointInsideConfigDir:
    @pytest.mark.parametrize("const_name", _CONSTANT_NAMES)
    def test_constant_is_under_config_dir(self, envoy_home, paths, const_name):
        value = getattr(paths, const_name)
        assert envoy_home in value.parents

    def test_sessions_dir_and_memory_dir_are_directories_not_files(self, envoy_home, paths):
        # Sanity check on naming: *_DIR constants shouldn't have a file suffix.
        assert paths.SESSIONS_DIR.suffix == ""
        assert paths.MEMORY_DIR.suffix == ""
        assert paths.SKILLS_DIR.suffix == ""
        assert paths.BACKUPS_DIR.suffix == ""
        assert paths.LOGS_DIR.suffix == ""


# ---------------------------------------------------------------------------
# config_dir() returns a pathlib.Path, always expanded/absolute
# ---------------------------------------------------------------------------

class TestConfigDirType:
    def test_config_dir_is_a_path(self, envoy_home, paths):
        from pathlib import Path
        assert isinstance(paths.config_dir(), Path)

    def test_config_dir_is_absolute(self, envoy_home, paths):
        assert paths.config_dir().is_absolute()
