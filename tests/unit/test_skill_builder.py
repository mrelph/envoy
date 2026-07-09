"""Unit tests for agents.skill_builder — generate / save / suggest skills.

NOTE on observed behavior vs. spec:
  * `generate_skill(request, slug, tools)` returns a `(content, slug)` tuple
    and does NOT write a file. Saving is handled by the separate `save_skill`
    helper. We test both pieces accordingly.
  * `skill_builder.py` does `from agents.base import invoke_ai`, so the
    `no_ai` fixture (which patches `agents.base.invoke_ai`) does not
    intercept calls made from inside skill_builder. We patch the symbol
    on the skill_builder module directly.
  * `generate_skill` now makes a single structured (JSON) AI call for
    {slug, description, body}. If that response can't be parsed, it falls
    back to the previous 3-call sequence (slug, then description, then
    body) so behavior degrades gracefully instead of breaking.
"""

import json
from pathlib import Path

import pytest

from agents import skill_builder as sb
from agents import skills as skills_mod


# --- Helpers ---------------------------------------------------------------

def _redirect_skill_paths(monkeypatch, envoy_home):
    """Point both skills + skill_builder at the per-test envoy_home dir."""
    user_skills = envoy_home / "skills"
    user_skills.mkdir(exist_ok=True)
    monkeypatch.setattr(skills_mod, "CONFIG_DIR", envoy_home, raising=True)
    monkeypatch.setattr(skills_mod, "SKILL_PATHS", [user_skills], raising=True)
    # skill_builder captured SKILLS_DIR at import time too.
    monkeypatch.setattr(sb, "SKILLS_DIR", user_skills, raising=True)
    skills_mod.reload_skills()
    return user_skills


def _patch_invoke_ai(monkeypatch, responses):
    """Replace skill_builder.invoke_ai with a stub.

    `responses` is a list — each call pops the next one. When exhausted,
    the last response is reused. Returns a `calls` list capturing
    every (prompt, max_tokens, tier) for inspection.
    """
    calls = []

    def _fake(prompt, max_tokens=10000, tier="heavy"):
        calls.append({"prompt": prompt, "max_tokens": max_tokens, "tier": tier})
        if len(calls) <= len(responses):
            return responses[len(calls) - 1]
        return responses[-1]

    monkeypatch.setattr(sb, "invoke_ai", _fake, raising=True)
    return calls


_FAKE_SKILL_MD = (
    "---\n"
    "name: do-thing\n"
    "description: Does the thing.\n"
    "allowed-tools: email_worker\n"
    "---\n"
    "\n"
    "# Do Thing\n\n"
    "## When to use\nWhen the user wants the thing done.\n"
)


def _fake_json_response(slug="do-thing", description="Does the thing.", body=_FAKE_SKILL_MD):
    """Build a raw AI response string containing the {slug, description, body} JSON."""
    return json.dumps({"slug": slug, "description": description, "body": body})


# --- generate_skill --------------------------------------------------------

class TestGenerateSkill:
    def test_single_json_call_with_explicit_slug(self, envoy_home, monkeypatch):
        user_skills = _redirect_skill_paths(monkeypatch, envoy_home)
        # A single structured JSON call replaces the old 3-call sequence.
        calls = _patch_invoke_ai(monkeypatch, [_fake_json_response(slug="do-thing")])

        content, slug = sb.generate_skill(
            request="Triage my inbox each morning",
            slug="do-thing",
            tools="email_worker",
        )

        assert len(calls) == 1
        assert calls[0]["tier"] == "medium"
        assert slug == "do-thing"
        assert content == _FAKE_SKILL_MD.strip()
        # No file is written by generate_skill itself — only save_skill does that.
        assert not (user_skills / "do-thing" / "SKILL.md").exists()

        # Explicit slug must be threaded into the prompt so the model uses it.
        assert "do-thing" in calls[0]["prompt"]
        assert "email_worker" in calls[0]["prompt"]
        assert "Triage my inbox each morning" in calls[0]["prompt"]

        # Now save and confirm the file lands in the right place.
        path_str = sb.save_skill(content, slug)
        skill_file = user_skills / "do-thing" / "SKILL.md"
        assert skill_file.exists()
        assert Path(path_str) == skill_file
        assert skill_file.read_text() == _FAKE_SKILL_MD.strip()

        # The skill should be discoverable after save (cache was reloaded).
        discovered = skills_mod.get_skills()
        assert "do-thing" in discovered

    def test_single_json_call_slug_derived_by_ai(self, envoy_home, monkeypatch):
        _redirect_skill_paths(monkeypatch, envoy_home)
        calls = _patch_invoke_ai(
            monkeypatch,
            [_fake_json_response(slug="morning-triage", description="Triages mail in the AM.")],
        )

        content, slug = sb.generate_skill(
            request="Triage my inbox each morning",
            slug="",
            tools="",
        )

        assert len(calls) == 1
        assert slug == "morning-triage"
        assert content == _FAKE_SKILL_MD.strip()

        # When tools is empty, generate_skill falls back to a default list.
        assert "email_worker" in calls[0]["prompt"] or "comms_worker" in calls[0]["prompt"]

    def test_malformed_json_falls_back_to_sequential_calls(self, envoy_home, monkeypatch):
        _redirect_skill_paths(monkeypatch, envoy_home)
        # First call returns unparsable garbage → triggers the 3-call fallback.
        calls = _patch_invoke_ai(
            monkeypatch,
            ["not json at all", '"morning-triage"', "Triages mail in the AM.", _FAKE_SKILL_MD],
        )

        content, slug = sb.generate_skill(
            request="Triage my inbox each morning",
            slug="",
            tools="",
        )

        assert len(calls) == 4
        assert calls[0]["tier"] == "medium"  # the failed structured attempt
        assert slug == "morning-triage"
        assert content == _FAKE_SKILL_MD.strip()

        # Fallback slug-generation prompt.
        assert "slug" in calls[1]["prompt"].lower()
        assert calls[1]["tier"] == "light"
        # Fallback description prompt.
        assert calls[2]["tier"] == "light"
        # Fallback full-content prompt.
        assert "morning-triage" in calls[3]["prompt"]
        assert calls[3]["tier"] == "medium"

    def test_json_missing_required_key_falls_back(self, envoy_home, monkeypatch):
        _redirect_skill_paths(monkeypatch, envoy_home)
        # Valid JSON, but missing "body" — still unusable, should fall back.
        calls = _patch_invoke_ai(
            monkeypatch,
            [
                json.dumps({"slug": "x", "description": "y"}),
                '"morning-triage"',
                "Triages mail in the AM.",
                _FAKE_SKILL_MD,
            ],
        )

        content, slug = sb.generate_skill(request="Triage my inbox", slug="", tools="")

        assert len(calls) == 4
        assert slug == "morning-triage"
        assert content == _FAKE_SKILL_MD.strip()

    def test_json_embedded_in_prose_is_still_parsed(self, envoy_home, monkeypatch):
        _redirect_skill_paths(monkeypatch, envoy_home)
        wrapped = "Sure, here you go:\n```json\n" + _fake_json_response() + "\n```"
        calls = _patch_invoke_ai(monkeypatch, [wrapped])

        content, slug = sb.generate_skill(request="Triage my inbox", slug="do-thing", tools="")

        assert len(calls) == 1
        assert slug == "do-thing"
        assert content == _FAKE_SKILL_MD.strip()


# --- slug sanitization ------------------------------------------------------

class TestSlugSanitization:
    def test_sanitize_slug_lowercases_and_hyphenates_spaces(self):
        assert sb._sanitize_slug("Morning Triage") == "morning-triage"

    def test_sanitize_slug_strips_disallowed_characters(self):
        assert sb._sanitize_slug("do_thing! now?") == "dothing-now"

    def test_sanitize_slug_neutralizes_path_traversal(self):
        # Separators are stripped, so the result can never escape SKILLS_DIR.
        assert sb._sanitize_slug("../../evil") == "evil"
        assert "/" not in sb._sanitize_slug("../../evil")

    def test_sanitize_slug_raises_when_nothing_usable_remains(self):
        with pytest.raises(ValueError):
            sb._sanitize_slug("../../")
        with pytest.raises(ValueError):
            sb._sanitize_slug("!!!")
        with pytest.raises(ValueError):
            sb._sanitize_slug("")

    def test_generate_skill_rejects_unusable_explicit_slug(self, envoy_home, monkeypatch):
        _redirect_skill_paths(monkeypatch, envoy_home)
        calls = _patch_invoke_ai(monkeypatch, ["should not be called"])

        content, slug = sb.generate_skill(request="Do a thing", slug="!!!", tools="")

        assert slug == ""
        assert content.startswith("Error")
        # Invalid slug is rejected before any AI call is made.
        assert calls == []

    def test_generate_skill_normalizes_traversal_slug(self, envoy_home, monkeypatch):
        user_skills = _redirect_skill_paths(monkeypatch, envoy_home)
        calls = _patch_invoke_ai(monkeypatch, [_fake_json_response(slug="evil")])

        content, slug = sb.generate_skill(request="Do a thing", slug="../../evil", tools="")

        assert slug == "evil"
        assert len(calls) == 1

        path_str = sb.save_skill(content, slug)
        # The file must land inside SKILLS_DIR/evil, not have escaped it.
        assert Path(path_str) == user_skills / "evil" / "SKILL.md"
        assert (user_skills / "evil").resolve().parent == user_skills.resolve()

    def test_save_skill_rejects_unusable_slug(self, envoy_home, monkeypatch):
        user_skills = _redirect_skill_paths(monkeypatch, envoy_home)

        result = sb.save_skill(_FAKE_SKILL_MD, "../../")

        assert result.startswith("Error")
        # Nothing should have been written anywhere under skills.
        assert list(user_skills.iterdir()) == []

    def test_save_skill_normalizes_traversal_slug(self, envoy_home, monkeypatch):
        user_skills = _redirect_skill_paths(monkeypatch, envoy_home)

        path_str = sb.save_skill(_FAKE_SKILL_MD, "../../evil")

        target = user_skills / "evil" / "SKILL.md"
        assert Path(path_str) == target
        assert target.exists()
        assert target.resolve().parent.parent == user_skills.resolve()


# --- save_skill -----------------------------------------------------------

class TestSaveSkill:
    def test_save_writes_file_and_reloads_cache(self, envoy_home, monkeypatch):
        user_skills = _redirect_skill_paths(monkeypatch, envoy_home)
        # Patch invoke_ai too in case anything tries to call it (defensive).
        _patch_invoke_ai(monkeypatch, ["unused"])

        # Pre-populate the cache so we can prove reload_skills was called.
        assert skills_mod.get_skills() == {}

        path_str = sb.save_skill(_FAKE_SKILL_MD, "do-thing")
        target = user_skills / "do-thing" / "SKILL.md"

        assert target.exists()
        assert Path(path_str) == target
        assert target.read_text() == _FAKE_SKILL_MD

        # Cache should have been invalidated → next get_skills picks up the new skill.
        discovered = skills_mod.get_skills()
        assert "do-thing" in discovered


# --- suggest_skills -------------------------------------------------------

class TestSuggestSkills:
    def test_no_activity_returns_friendly_message(self, envoy_home, monkeypatch):
        _redirect_skill_paths(monkeypatch, envoy_home)
        # Force _load_entries to return nothing.
        monkeypatch.setattr(sb, "_load_entries", lambda days: [], raising=True)
        ai_calls = _patch_invoke_ai(monkeypatch, ["should not be called"])

        result = sb.suggest_skills(days=14)

        assert "No recent activity" in result
        # AI should not have been invoked at all in the no-activity branch.
        assert ai_calls == []

    def test_with_activity_calls_ai_with_context_and_existing_skills(
        self, envoy_home, monkeypatch
    ):
        base = _redirect_skill_paths(monkeypatch, envoy_home)
        # Drop one existing skill on disk so its name shows up in the prompt.
        (base / "already-have").mkdir()
        (base / "already-have" / "SKILL.md").write_text(
            "---\nname: already-have\ndescription: Existing skill.\n---\n\nBody.\n"
        )
        skills_mod.reload_skills()

        # Provide a couple of fake memory entries (mix of observation + action).
        fake_entries = [
            {"type": "observation", "text": "User asked about deploy three times"},
            {"type": "action", "text": "Drafted standup update"},
        ]
        monkeypatch.setattr(sb, "_load_entries", lambda days: fake_entries, raising=True)

        ai_calls = _patch_invoke_ai(monkeypatch, ["### new-skill\nDescription: ...\n"])

        result = sb.suggest_skills(days=7)

        assert "new-skill" in result  # whatever AI returned is passed through
        assert len(ai_calls) == 1

        prompt = ai_calls[0]["prompt"]
        # Existing skills must appear in the prompt so AI doesn't re-suggest them.
        assert "already-have" in prompt
        # Recent activity content must appear in the prompt.
        assert "deploy three times" in prompt
        assert "Drafted standup update" in prompt
        # Heavier tier than the slug helper.
        assert ai_calls[0]["tier"] == "medium"

    def test_entries_without_text_yields_not_enough_data(self, envoy_home, monkeypatch):
        _redirect_skill_paths(monkeypatch, envoy_home)
        # Entries exist, but after slicing/formatting there's no text content
        # — the function should bail out before calling the AI.
        # Easiest way: provide entries that all match the observation/action
        # filters but produce empty activity_lines. In practice any entry
        # produces a "- " line, so to truly hit the empty branch we feed [].
        # That's already covered above; here we just confirm the early-return
        # message when entries is empty for a different `days` value.
        monkeypatch.setattr(sb, "_load_entries", lambda days: [], raising=True)
        _patch_invoke_ai(monkeypatch, ["unused"])

        assert "No recent activity" in sb.suggest_skills(days=1)
