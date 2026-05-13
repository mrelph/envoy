"""Unit tests for agents.skills — discovery, catalog rendering, cache reload."""

from pathlib import Path

import pytest

from agents import skills as skills_mod


# --- Helpers ---------------------------------------------------------------

def _redirect_skill_paths(monkeypatch, envoy_home):
    """Point skills module at the per-test envoy_home dir.

    `agents.skills` captures `CONFIG_DIR` and `SKILL_PATHS` at import time
    using the real `Path.home()`, so monkeypatching $HOME after the import
    does nothing — we have to overwrite those module-level constants.
    Returns the user-shared skills dir under the fake home.
    """
    user_skills = envoy_home / "skills"
    user_skills.mkdir(exist_ok=True)
    # Replace the scan list with a single isolated dir so we don't pick up
    # whatever is on the developer's machine.
    monkeypatch.setattr(skills_mod, "CONFIG_DIR", envoy_home, raising=True)
    monkeypatch.setattr(skills_mod, "SKILL_PATHS", [user_skills], raising=True)
    # Make sure the cache from a previous test doesn't bleed through.
    skills_mod.reload_skills()
    return user_skills


def _write_skill(base: Path, slug: str, name: str, description: str, body: str = "Body text."):
    skill_dir = base / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "allowed-tools: email_worker, comms_worker\n"
        "---\n"
        f"\n{body}\n"
    )
    return skill_md


# --- get_skills -----------------------------------------------------------

class TestGetSkills:
    def test_discovers_skill_with_valid_frontmatter(self, envoy_home, monkeypatch):
        base = _redirect_skill_paths(monkeypatch, envoy_home)
        _write_skill(base, "foo", "foo", "Does foo things.")

        result = skills_mod.get_skills()

        assert "foo" in result
        assert result["foo"]["name"] == "foo"
        assert result["foo"]["description"] == "Does foo things."
        # body should have stripped frontmatter
        assert "Body text." in result["foo"]["body"]
        # location/dir should point at the SKILL.md we wrote
        assert result["foo"]["location"].endswith("SKILL.md")

    def test_skill_folder_without_skill_md_is_ignored(self, envoy_home, monkeypatch):
        base = _redirect_skill_paths(monkeypatch, envoy_home)
        # Create a dir but no SKILL.md inside.
        (base / "empty").mkdir()
        # And one valid skill so we know discovery actually ran.
        _write_skill(base, "valid", "valid", "Real skill.")

        result = skills_mod.get_skills()

        assert "valid" in result
        assert "empty" not in result
        assert len(result) == 1

    def test_malformed_frontmatter_is_skipped_gracefully(self, envoy_home, monkeypatch):
        base = _redirect_skill_paths(monkeypatch, envoy_home)

        # Missing frontmatter delimiters
        no_fm_dir = base / "no-frontmatter"
        no_fm_dir.mkdir()
        (no_fm_dir / "SKILL.md").write_text("Just a plain markdown file, no metadata.\n")

        # Frontmatter present but missing required `name`
        missing_name_dir = base / "missing-name"
        missing_name_dir.mkdir()
        (missing_name_dir / "SKILL.md").write_text(
            "---\ndescription: no name here\n---\n\nBody.\n"
        )

        # Invalid YAML inside frontmatter
        bad_yaml_dir = base / "bad-yaml"
        bad_yaml_dir.mkdir()
        (bad_yaml_dir / "SKILL.md").write_text(
            "---\nname: x\ndescription: [unclosed\n---\n\nBody.\n"
        )

        # One good skill so we can prove discovery still works
        _write_skill(base, "ok", "ok", "Good skill.")

        result = skills_mod.get_skills()

        assert "ok" in result
        assert "no-frontmatter" not in result
        assert "missing-name" not in result
        assert "bad-yaml" not in result


# --- build_catalog --------------------------------------------------------

class TestBuildCatalog:
    def test_empty_input_returns_empty_string(self, envoy_home, monkeypatch):
        _redirect_skill_paths(monkeypatch, envoy_home)
        assert skills_mod.build_catalog({}) == ""

    def test_multi_skill_catalog_lists_each_skill(self, envoy_home, monkeypatch):
        base = _redirect_skill_paths(monkeypatch, envoy_home)
        _write_skill(base, "alpha", "alpha", "Alpha skill description.")
        _write_skill(base, "beta", "beta", "Beta skill description.")

        skills = skills_mod.get_skills()
        catalog = skills_mod.build_catalog(skills)

        # Wraps in <available_skills>...</available_skills>
        assert catalog.startswith("<available_skills>")
        assert catalog.rstrip().endswith("</available_skills>")
        # Each skill name + description appears exactly once
        assert 'name="alpha"' in catalog
        assert "Alpha skill description." in catalog
        assert 'name="beta"' in catalog
        assert "Beta skill description." in catalog


# --- reload_skills --------------------------------------------------------

class TestReloadSkills:
    def test_reload_picks_up_newly_added_skill(self, envoy_home, monkeypatch):
        base = _redirect_skill_paths(monkeypatch, envoy_home)
        _write_skill(base, "first", "first", "First skill.")

        first = skills_mod.get_skills()
        assert "first" in first
        assert "second" not in first

        # Add a skill on disk *after* the cache was populated.
        _write_skill(base, "second", "second", "Second skill.")

        # Without reload the cache should still be stale.
        cached = skills_mod.get_skills()
        assert "second" not in cached

        skills_mod.reload_skills()
        refreshed = skills_mod.get_skills()
        assert "first" in refreshed
        assert "second" in refreshed
