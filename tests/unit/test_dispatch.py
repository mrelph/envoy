"""Tests for dispatch.py — slash command parsing and substitution.

The dispatch() function is the heart of how user input becomes an agent prompt.
These tests cover:
  1. COMMANDS table integrity (pure data, no mocks)
  2. Slash-command parsing & {days}/{arg} substitution
  3. ARG_COMMANDS (commands that need an argument)
  4. System commands (return handled=False so the UI handles them)
  5. Natural-language passthrough

A FakeAgent records the prompt it was given so we can assert on substitution.
"""

import importlib
import os

import pytest

import dispatch
from dispatch import (
    ARG_COMMANDS,
    COMMAND_GROUPS,
    COMMANDS,
    DEFAULT_DAYS,
)


# --- helpers --------------------------------------------------------------

class FakeAgent:
    """Records prompts and returns a fixed marker string."""

    def __init__(self, response="AGENT_RESPONSE"):
        self.prompts = []
        self.response = response

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.response

    @property
    def last_prompt(self):
        return self.prompts[-1] if self.prompts else None


# =========================================================================
# 1. COMMANDS table integrity (no mocks, pure data)
# =========================================================================

class TestCommandsTableIntegrity:
    def test_every_entry_is_two_tuple(self):
        for cmd, entry in COMMANDS.items():
            assert isinstance(entry, tuple), f"{cmd}: entry must be a tuple"
            assert len(entry) == 2, f"{cmd}: entry must be (description, template)"

    def test_every_entry_description_is_str(self):
        for cmd, (desc, _) in COMMANDS.items():
            assert isinstance(desc, str) and desc, f"{cmd}: description must be non-empty str"

    def test_every_entry_template_is_str_or_none(self):
        for cmd, (_, tpl) in COMMANDS.items():
            assert tpl is None or isinstance(tpl, str), (
                f"{cmd}: template must be str or None, got {type(tpl).__name__}"
            )

    def test_every_command_starts_with_slash(self):
        for cmd in COMMANDS:
            assert cmd.startswith("/"), f"command {cmd!r} must start with '/'"

    def test_system_commands_have_none_template(self):
        """Commands in the System group are handled by the UI layer — their template is None."""
        system_group = next(cmds for name, cmds in COMMAND_GROUPS if name == "System")
        for cmd in system_group:
            assert cmd in COMMANDS, f"{cmd} listed in System group but not in COMMANDS"
            _, tpl = COMMANDS[cmd]
            assert tpl is None, f"system command {cmd} should have None template (UI handles it)"

    def test_arg_commands_all_exist_in_commands(self):
        for cmd in ARG_COMMANDS:
            assert cmd in COMMANDS, f"{cmd} in ARG_COMMANDS but not in COMMANDS"

    def test_default_days_all_exist_in_commands(self):
        for cmd in DEFAULT_DAYS:
            assert cmd in COMMANDS, f"{cmd} in DEFAULT_DAYS but not in COMMANDS"

    def test_default_days_values_are_positive_ints(self):
        for cmd, days in DEFAULT_DAYS.items():
            assert isinstance(days, int), f"{cmd}: default days must be int"
            assert days > 0, f"{cmd}: default days must be positive"

    def test_default_days_commands_use_days_placeholder(self):
        """Every command with a default-days entry should actually use {days} in its
        template — unless it has a None template (custom handler parses days itself)."""
        for cmd in DEFAULT_DAYS:
            _, tpl = COMMANDS[cmd]
            if tpl is None:
                continue  # custom-handled (e.g. /team-health, /schedule)
            assert "{days}" in tpl, f"{cmd}: has DEFAULT_DAYS but template lacks {{days}}"

    def test_arg_commands_use_arg_placeholder(self):
        """Most ARG_COMMANDS substitute {arg} — verify those that have a template do."""
        for cmd in ARG_COMMANDS:
            _, tpl = COMMANDS[cmd]
            if tpl is not None:
                assert "{arg}" in tpl, f"{cmd}: in ARG_COMMANDS but template lacks {{arg}}"

    def test_command_groups_only_reference_known_commands(self):
        for group_name, cmds in COMMAND_GROUPS:
            for cmd in cmds:
                assert cmd in COMMANDS, (
                    f"COMMAND_GROUPS[{group_name!r}] references unknown command {cmd!r}"
                )


# =========================================================================
# 2. Slash-command parsing & substitution
# =========================================================================

class TestDigestAndDaysSubstitution:
    """digest/customers/catchup all have a matching templates/commands.md section,
    so their prompt is built from that shared template (see
    TestTemplateSourcedPrompts below) rather than the short hardcoded string in
    COMMANDS. These tests just check day-substitution ended up in the prompt —
    the exact-text assertions live in TestTemplateSourcedPrompts."""

    def test_digest_no_arg_uses_default_days(self, monkeypatch):
        monkeypatch.setenv("USER", "jsmith")
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/digest", agent)
        assert handled is True
        assert result == "AGENT_RESPONSE"
        assert f"`{DEFAULT_DAYS['/digest']}`" in agent.last_prompt
        assert "team email digest" in agent.last_prompt

    def test_digest_with_explicit_days(self, monkeypatch):
        monkeypatch.setenv("USER", "jsmith")
        agent = FakeAgent()
        dispatch.dispatch("/digest 14", agent)
        assert "`14`" in agent.last_prompt
        assert "team email digest" in agent.last_prompt

    def test_customers_with_explicit_days(self, monkeypatch):
        monkeypatch.setenv("USER", "jsmith")
        agent = FakeAgent()
        dispatch.dispatch("/customers 30", agent)
        assert "`30`" in agent.last_prompt
        assert "customer emails" in agent.last_prompt

    def test_customers_no_arg_uses_default_14(self, monkeypatch):
        monkeypatch.setenv("USER", "jsmith")
        agent = FakeAgent()
        dispatch.dispatch("/customers", agent)
        assert "`14`" in agent.last_prompt

    def test_catchup_no_arg_uses_default_5(self):
        agent = FakeAgent()
        dispatch.dispatch("/catchup", agent)
        assert "`5`" in agent.last_prompt

    def test_briefing_ignores_extra_numeric_arg(self):
        """/briefing has no {days} placeholder — numeric arg shouldn't appear in prompt."""
        agent = FakeAgent()
        dispatch.dispatch("/briefing 14", agent)
        # Template has no placeholders so format() leaves it untouched.
        assert agent.last_prompt == "Give me a full briefing — calendar, inbox, and Slack"

    def test_calendar_no_arg(self):
        agent = FakeAgent()
        dispatch.dispatch("/calendar", agent)
        assert agent.last_prompt == "Review my calendar for today"

    def test_unknown_slash_command_returns_help_hint(self):
        """Unknown slash commands return a 'command not found' message — they do not
        burn LLM tokens by being passed verbatim to the agent."""
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/notarealcommand", agent)
        assert handled is True
        assert "Unknown command" in result
        assert "/notarealcommand" in result
        assert "/help" in result
        assert agent.last_prompt is None  # agent was NOT called

    def test_command_is_case_insensitive(self, monkeypatch):
        """parts[0].lower() — uppercase slash commands should still match."""
        monkeypatch.setenv("USER", "jsmith")
        agent = FakeAgent()
        dispatch.dispatch("/DIGEST 10", agent)
        assert "`10`" in agent.last_prompt
        assert "team email digest" in agent.last_prompt


# =========================================================================
# 2b. Non-numeric day args — previously silently dropped, now hinted
# =========================================================================

class TestNonNumericDayArg:
    """/digest last week (etc.) used to silently fall back to the default with
    no indication the arg was ignored. Days-taking commands now append a
    one-line notice to the response instead of swallowing the arg silently."""

    def test_digest_non_numeric_arg_falls_back_and_notes_it(self, monkeypatch):
        monkeypatch.setenv("USER", "jsmith")
        agent = FakeAgent(response="Here is your digest.")
        result, handled = dispatch.dispatch("/digest last week", agent)
        assert handled is True
        # Falls back to the default day count for the prompt sent to the agent.
        assert f"`{DEFAULT_DAYS['/digest']}`" in agent.last_prompt
        # The original non-numeric text is never silently discarded — it's
        # surfaced in the final response as a one-line notice.
        assert result.startswith("Here is your digest.")
        assert "last week" in result
        assert "isn't a number" in result
        assert f"/digest {DEFAULT_DAYS['/digest']}" in result

    def test_catchup_non_numeric_arg_uses_default_and_notes_it(self):
        agent = FakeAgent(response="Catch-up report.")
        result, handled = dispatch.dispatch("/catchup a couple weeks", agent)
        assert handled is True
        assert f"`{DEFAULT_DAYS['/catchup']}`" in agent.last_prompt
        assert "a couple weeks" in result
        assert "isn't a number" in result

    def test_digest_numeric_arg_still_works_without_notice(self, monkeypatch):
        """Sanity check: numeric day args are unaffected by the new notice logic."""
        monkeypatch.setenv("USER", "jsmith")
        agent = FakeAgent(response="Here is your digest.")
        result, handled = dispatch.dispatch("/digest 30", agent)
        assert handled is True
        assert "`30`" in agent.last_prompt
        assert result == "Here is your digest."
        assert "isn't a number" not in result

    def test_no_notice_when_no_arg_given(self):
        """No arg at all (not a bad one) shouldn't trigger the hint."""
        agent = FakeAgent(response="Digest here.")
        result, handled = dispatch.dispatch("/digest", agent)
        assert handled is True
        assert result == "Digest here."

    def test_non_day_command_ignores_non_numeric_arg_without_notice(self):
        """/calendar has no {days} placeholder and isn't in DEFAULT_DAYS — a
        stray non-numeric arg is just ignored as before, no notice appended."""
        agent = FakeAgent(response="Your calendar.")
        result, handled = dispatch.dispatch("/calendar tomorrow", agent)
        assert handled is True
        assert result == "Your calendar."


# =========================================================================
# 3. ARG_COMMANDS handling
# =========================================================================

class TestArgCommands:
    def test_prep_1on1_with_alias_substitutes_arg(self):
        """prep-1on1 has a matching commands.md section — {arg} maps to {person}
        there (see dispatch._template_kwargs); exact-text coverage lives in
        TestTemplateSourcedPrompts."""
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/prep-1on1 jsmith", agent)
        assert handled is True
        assert "jsmith" in agent.last_prompt
        assert "1:1" in agent.last_prompt.lower()

    def test_prep_1on1_no_arg_returns_usage_message(self):
        """ARG_COMMANDS with no arg are intercepted with a Usage: hint — agent NOT called."""
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/prep-1on1", agent)
        assert handled is True
        assert isinstance(result, str)
        assert result.startswith("Usage:")
        assert "/prep-1on1" in result
        assert "alias" in result
        assert agent.prompts == [], "agent should NOT be called when arg is missing"

    def test_reply_with_full_string_arg(self):
        agent = FakeAgent()
        dispatch.dispatch("/reply about the budget", agent)
        # parts[1] is everything after the command — full multi-word arg.
        assert agent.last_prompt == "Reply to the email about about the budget"

    def test_reply_no_arg_returns_usage(self):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/reply", agent)
        assert handled is True
        assert result.startswith("Usage:")
        assert agent.prompts == []

    def test_search_arg_passed_through(self):
        agent = FakeAgent()
        dispatch.dispatch("/search quarterly results", agent)
        assert agent.last_prompt == "Search Slack for: quarterly results"

    def test_book_arg_passed_through(self):
        agent = FakeAgent()
        dispatch.dispatch("/book SEA20 at 3pm", agent)
        assert agent.last_prompt == "Find me a room in SEA20 at 3pm"

    def test_ea_no_arg_returns_usage(self):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/ea", agent)
        assert handled is True
        assert result.startswith("Usage:")
        assert "EA" in result

    def test_prep_meeting_no_arg_uses_default_subject(self):
        """/prep-meeting with no arg defaults to "my next meeting" rather than nagging
        the user — it's the only ARG-style command with a sensible default. prep-meeting
        has a matching commands.md section, so the prompt comes from there."""
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/prep-meeting", agent)
        assert handled is True
        assert result == "AGENT_RESPONSE"
        assert "my next meeting" in agent.last_prompt


# =========================================================================
# 4. System commands — return (cmd, False) for UI to handle
# =========================================================================

class TestSystemCommands:
    @pytest.mark.parametrize("cmd", ["/help", "/status", "/exit", "/settings", "/backup"])
    def test_system_command_unhandled(self, cmd):
        """These return (cmd, False) so the TUI / REPL can intercept."""
        agent = FakeAgent()
        result, handled = dispatch.dispatch(cmd, agent)
        assert handled is False, f"{cmd}: should NOT be handled internally"
        assert result == cmd, f"{cmd}: result should be cmd verbatim"
        assert agent.prompts == [], f"{cmd}: agent must not be called"

    def test_models_no_arg_calls_internal_handler(self, monkeypatch):
        """/models is internally handled — patch _handle_models to avoid touching ~/.envoy."""
        monkeypatch.setattr(dispatch, "_handle_models", lambda arg: f"MODELS:{arg!r}")
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/models", agent)
        assert handled is True
        assert result == "MODELS:''"
        assert agent.prompts == []

    def test_doctor_calls_internal_handler(self, monkeypatch):
        monkeypatch.setattr(dispatch, "_run_doctor", lambda: "DOCTOR_OUTPUT")
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/doctor", agent)
        assert handled is True
        assert result == "DOCTOR_OUTPUT"
        assert agent.prompts == []

    def test_skills_command_handled(self, monkeypatch):
        """/skills imports agents.skills.get_skills — patch via sys.modules to avoid touching disk."""
        import sys
        import types
        fake_mod = types.ModuleType("agents.skills")
        fake_mod.get_skills = lambda: {}
        monkeypatch.setitem(sys.modules, "agents.skills", fake_mod)

        agent = FakeAgent()
        result, handled = dispatch.dispatch("/skills", agent)
        assert handled is True
        assert "No skills configured" in result
        assert agent.prompts == []

    def test_skills_command_with_skills(self, monkeypatch):
        import sys
        import types
        fake_mod = types.ModuleType("agents.skills")
        fake_mod.get_skills = lambda: {
            "eod": {"name": "eod", "description": "End of day summary"},
        }
        monkeypatch.setitem(sys.modules, "agents.skills", fake_mod)

        agent = FakeAgent()
        result, handled = dispatch.dispatch("/skills", agent)
        assert handled is True
        assert "eod" in result
        assert "End of day summary" in result
        assert agent.prompts == []

    def test_doctor_aws_hint_is_actionable(self, envoy_home, monkeypatch):
        """envoy doctor previously suggested `aws login`, which isn't a real
        AWS CLI command. It should now point at mwinit / SSO instead — and no
        longer mention the nonexistent `aws login`."""
        import boto3
        def _boom_client(*a, **k):
            raise RuntimeError("Unable to locate credentials")
        monkeypatch.setattr(boto3, "client", _boom_client)
        output = dispatch._run_doctor()
        assert "aws login" not in output
        assert "mwinit" in output
        assert "AWS SSO" in output

    def test_mcp_command_handled(self, monkeypatch):
        import sys
        import types
        fake_init = types.ModuleType("init_cmd")
        fake_init.run_mcp = lambda arg: f"MCP_OUTPUT:{arg!r}"
        monkeypatch.setitem(sys.modules, "init_cmd", fake_init)

        agent = FakeAgent()
        result, handled = dispatch.dispatch("/mcp list", agent)
        assert handled is True
        assert result == "MCP_OUTPUT:'list'"
        assert agent.prompts == []


# =========================================================================
# Internally-handled commands (heartbeat, skill-builder)
# =========================================================================

class TestHeartbeatCommands:
    def _patch_heartbeat(self, monkeypatch, **fns):
        import sys
        import types
        mod = types.ModuleType("agents.heartbeat")
        for name, fn in fns.items():
            setattr(mod, name, fn)
        monkeypatch.setitem(sys.modules, "agents.heartbeat", mod)

    def test_routine_with_arg_calls_add_routine(self, monkeypatch):
        calls = []
        self._patch_heartbeat(monkeypatch, add_routine=lambda a: calls.append(a) or "ADDED")
        result, handled = dispatch.dispatch("/routine check inbox", FakeAgent())
        assert handled is True
        assert result == "ADDED"
        assert calls == ["check inbox"]

    def test_routine_no_arg_returns_usage(self, monkeypatch):
        self._patch_heartbeat(monkeypatch, add_routine=lambda a: "should-not-be-called")
        result, handled = dispatch.dispatch("/routine", FakeAgent())
        assert handled is True
        assert result.startswith("Usage:")
        assert "/routine" in result

    def test_routines_lists(self, monkeypatch):
        self._patch_heartbeat(monkeypatch, get_routines=lambda: "ROUTINES")
        result, handled = dispatch.dispatch("/routines", FakeAgent())
        assert handled is True
        assert result == "ROUTINES"

    def test_heartbeat_runs(self, monkeypatch):
        captured = {}

        def fake_run(quiet, notify):
            captured["quiet"] = quiet
            captured["notify"] = notify
            return "HB_RAN"

        self._patch_heartbeat(monkeypatch, run_heartbeat=fake_run)
        result, handled = dispatch.dispatch("/heartbeat", FakeAgent())
        assert handled is True
        assert result == "HB_RAN"
        assert captured == {"quiet": False, "notify": "none"}

    def test_suggest_routines(self, monkeypatch):
        self._patch_heartbeat(monkeypatch, suggest_routines=lambda: "SUGGESTIONS")
        result, handled = dispatch.dispatch("/suggest-routines", FakeAgent())
        assert handled is True
        assert result == "SUGGESTIONS"


class TestSkillBuilderCommands:
    def _patch_skill_builder(self, monkeypatch, **fns):
        import sys
        import types
        mod = types.ModuleType("agents.skill_builder")
        for name, fn in fns.items():
            setattr(mod, name, fn)
        monkeypatch.setitem(sys.modules, "agents.skill_builder", mod)

    def test_build_skill_with_description(self, monkeypatch):
        self._patch_skill_builder(
            monkeypatch,
            generate_skill=lambda desc: ("CONTENT", "my-slug"),
            save_skill=lambda content, slug: f"/path/{slug}",
        )
        result, handled = dispatch.dispatch("/build-skill triage critical alerts", FakeAgent())
        assert handled is True
        assert "my-slug" in result
        assert "/path/my-slug" in result
        assert "CONTENT" in result

    def test_build_skill_no_arg_returns_usage(self, monkeypatch):
        self._patch_skill_builder(
            monkeypatch,
            generate_skill=lambda desc: ("X", "y"),
            save_skill=lambda c, s: "p",
        )
        result, handled = dispatch.dispatch("/build-skill", FakeAgent())
        assert handled is True
        assert result.startswith("Usage:")
        assert "/build-skill" in result

    def test_suggest_skills_default_days(self, monkeypatch):
        captured = {}
        self._patch_skill_builder(
            monkeypatch,
            suggest_skills=lambda days: captured.update(days=days) or "SUGGESTIONS",
        )
        result, handled = dispatch.dispatch("/suggest-skills", FakeAgent())
        assert handled is True
        assert result == "SUGGESTIONS"
        assert captured["days"] == 14  # default

    def test_suggest_skills_with_days(self, monkeypatch):
        captured = {}
        self._patch_skill_builder(
            monkeypatch,
            suggest_skills=lambda days: captured.update(days=days) or "SUGGESTIONS",
        )
        dispatch.dispatch("/suggest-skills 30", FakeAgent())
        assert captured["days"] == 30


# =========================================================================
# 5. Natural-language input
# =========================================================================

class TestNaturalLanguagePassthrough:
    def test_plain_word(self):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("morning", agent)
        assert handled is True
        assert agent.last_prompt == "morning"
        assert result == "AGENT_RESPONSE"

    def test_greeting(self):
        agent = FakeAgent()
        dispatch.dispatch("hi", agent)
        assert agent.last_prompt == "hi"

    def test_full_sentence(self):
        agent = FakeAgent()
        dispatch.dispatch("What's on my schedule for tomorrow?", agent)
        assert agent.last_prompt == "What's on my schedule for tomorrow?"

    def test_whitespace_stripped(self):
        agent = FakeAgent()
        dispatch.dispatch("   hello world   ", agent)
        assert agent.last_prompt == "hello world"

    def test_empty_input_returns_handled_with_none(self):
        """Empty/whitespace-only input short-circuits — agent is NOT called."""
        agent = FakeAgent()
        result, handled = dispatch.dispatch("", agent)
        assert handled is True
        assert result is None
        assert agent.prompts == []

    def test_whitespace_only_input(self):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("   \n\t  ", agent)
        assert handled is True
        assert result is None
        assert agent.prompts == []


# =========================================================================
# 6. Shared command-prompt templates (templates/commands.md via dispatch)
# =========================================================================

class TestTemplateSourcedPrompts:
    """Commands with a matching templates/commands.md section (digest, customers,
    prep-1on1, ...) build their prompt from that shared template — the same one
    cli.py's subcommands consume, with ~/.envoy/commands.md override support —
    via dispatch._load_commands()/_build_prompt(), instead of the short
    hardcoded string in COMMANDS. This is what keeps `/digest` (TUI/REPL) and
    `envoy digest` (CLI) from drifting apart."""

    def test_digest_prompt_matches_commands_md_template(self, monkeypatch):
        monkeypatch.setenv("USER", "jsmith")
        agent = FakeAgent()
        dispatch.dispatch("/digest 21", agent)
        expected = dispatch._build_prompt(
            dispatch._load_commands()["digest"], days=21, alias="jsmith",
        )
        assert agent.last_prompt == expected
        # Sanity: it's the full template body, not the old one-liner.
        assert "team email digest" in expected
        assert "`21`" in expected
        assert "`jsmith`" in expected

    def test_customers_prompt_matches_commands_md_template(self, monkeypatch):
        monkeypatch.setenv("USER", "asmith")
        agent = FakeAgent()
        dispatch.dispatch("/customers 9", agent)
        expected = dispatch._build_prompt(
            dispatch._load_commands()["customers"], days=9, alias="asmith",
        )
        assert agent.last_prompt == expected

    def test_prep_1on1_prompt_maps_arg_to_person(self, monkeypatch):
        monkeypatch.setenv("USER", "asmith")
        agent = FakeAgent()
        dispatch.dispatch("/prep-1on1 bwilliams", agent)
        expected = dispatch._build_prompt(
            dispatch._load_commands()["prep-1on1"], person="bwilliams", days=7,
            alias="asmith",
        )
        assert agent.last_prompt == expected
        assert "bwilliams" in expected

    def test_cleanup_prompt_includes_default_limit(self, monkeypatch):
        monkeypatch.setenv("USER", "asmith")
        agent = FakeAgent()
        dispatch.dispatch("/cleanup", agent)
        expected = dispatch._build_prompt(
            dispatch._load_commands()["cleanup"], days=14, limit=100, alias="asmith",
        )
        assert agent.last_prompt == expected
        assert "`100`" in agent.last_prompt

    def test_fallback_to_hardcoded_template_when_no_commands_md_section(self):
        """/briefing has no matching commands.md section — commands.md only has
        an unrelated 'morning-briefing' entry that no CLI subcommand consumes
        either — so it falls back to the hardcoded COMMANDS entry unchanged."""
        assert "briefing" not in dispatch._load_commands()
        agent = FakeAgent()
        dispatch.dispatch("/briefing", agent)
        assert agent.last_prompt == "Give me a full briefing — calendar, inbox, and Slack"

    def test_fallback_when_load_commands_raises(self, monkeypatch):
        """Never crash: if templates/commands.md can't be read, dispatch still
        returns the hardcoded fallback prompt instead of blowing up."""
        def _boom():
            raise FileNotFoundError("no commands.md")
        monkeypatch.setattr(dispatch, "_load_commands", _boom)
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/digest 14", agent)
        assert handled is True
        assert agent.last_prompt == "Generate a team digest for the last 14 days"

    def test_fallback_when_template_section_body_empty(self, monkeypatch):
        """A command whose template lookup returns nothing (e.g. section missing
        from a stripped-down ~/.envoy/commands.md override) still gets a prompt."""
        monkeypatch.setattr(dispatch, "_load_commands", lambda: {})
        agent = FakeAgent()
        dispatch.dispatch("/catchup 3", agent)
        assert agent.last_prompt == "I was out of office for 3 days, give me a full catch-up"


# =========================================================================
# 7. /learn — surfaces agents.learning's pending-confirmation queue
# =========================================================================

class TestLearnCommand:
    @pytest.fixture
    def learning_mod(self, envoy_home):
        import agents.learning as learning
        importlib.reload(learning)
        return learning

    def test_learn_registered_in_commands_and_system_group(self):
        assert "/learn" in COMMANDS
        assert COMMANDS["/learn"][1] is None
        system_group = next(cmds for name, cmds in COMMAND_GROUPS if name == "System")
        assert "/learn" in system_group

    def test_learn_no_pending_rules(self, learning_mod):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/learn", agent)
        assert handled is True
        assert "No pending" in result
        assert agent.prompts == []

    def test_learn_list_shows_numbered_rules(self, learning_mod):
        learning_mod.apply_learning("check calendar before booking", "Calendar")
        learning_mod.apply_learning("always CC the EA", "Email")
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/learn list", agent)
        assert handled is True
        assert "`1`" in result and "check calendar before booking" in result
        assert "`2`" in result and "always CC the EA" in result

    def test_learn_confirm_writes_rule_and_dequeues(self, learning_mod):
        learning_mod.apply_learning("batch digests every morning", "General")
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/learn confirm 1", agent)
        assert handled is True
        assert "Learned" in result
        assert learning_mod.list_pending() == []

    def test_learn_reject_discards_rule(self, learning_mod):
        learning_mod.apply_learning("never book meetings after 5pm", "Calendar")
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/learn reject 1", agent)
        assert handled is True
        assert "Rejected" in result
        assert learning_mod.list_pending() == []

    def test_learn_confirm_no_number_shows_usage(self, learning_mod):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/learn confirm", agent)
        assert handled is True
        assert "Usage" in result

    def test_learn_unknown_subcommand_shows_usage(self, learning_mod):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/learn frobnicate", agent)
        assert handled is True
        assert "Usage" in result


# =========================================================================
# 8. dispatch_with_learning — pending-rule summary hint appended to responses
# =========================================================================

class TestPendingSummaryHint:
    def test_freeform_response_gets_pending_summary_appended(self, envoy_home):
        import agents.learning as learning
        importlib.reload(learning)
        learning.apply_learning("always confirm before sending external mail", "Email")

        agent = FakeAgent(response="Here is your briefing, it is a fairly long response indeed.")
        result, handled = dispatch.dispatch_with_learning("what's on my plate today", agent)
        assert handled is True
        assert result.startswith("Here is your briefing")
        assert "learned rule" in result
        assert "/learn confirm 1" in result

    def test_no_summary_appended_when_queue_empty(self, envoy_home):
        import agents.learning as learning
        importlib.reload(learning)

        agent = FakeAgent(response="Here is your briefing, it is a fairly long response indeed.")
        result, handled = dispatch.dispatch_with_learning("what's on my plate today", agent)
        assert result == "Here is your briefing, it is a fairly long response indeed."

    def test_learn_commands_own_output_not_double_annotated(self, envoy_home):
        """/learn's own output already lists the pending queue — dispatch_with_learning
        should not also tack the one-line hint onto it."""
        import agents.learning as learning
        importlib.reload(learning)
        learning.apply_learning("always confirm before sending external mail", "Email")

        agent = FakeAgent()
        result, handled = dispatch.dispatch_with_learning("/learn list", agent)
        assert result.count("learned rule") <= 1
