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
        """Every command with a default-days entry should actually use {days} in its template."""
        for cmd in DEFAULT_DAYS:
            _, tpl = COMMANDS[cmd]
            assert tpl is not None, f"{cmd}: has DEFAULT_DAYS but no template"
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
    def test_digest_no_arg_uses_default_days(self):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/digest", agent)
        assert handled is True
        assert result == "AGENT_RESPONSE"
        assert agent.last_prompt == f"Generate a team digest for the last {DEFAULT_DAYS['/digest']} days"
        assert "7" in agent.last_prompt  # confirms default

    def test_digest_with_explicit_days(self):
        agent = FakeAgent()
        dispatch.dispatch("/digest 14", agent)
        assert agent.last_prompt == "Generate a team digest for the last 14 days"

    def test_customers_with_explicit_days(self):
        agent = FakeAgent()
        dispatch.dispatch("/customers 30", agent)
        assert agent.last_prompt == (
            "Scan for external customer emails with action items from the last 30 days"
        )

    def test_customers_no_arg_uses_default_14(self):
        agent = FakeAgent()
        dispatch.dispatch("/customers", agent)
        assert "14 days" in agent.last_prompt

    def test_catchup_no_arg_uses_default_5(self):
        agent = FakeAgent()
        dispatch.dispatch("/catchup", agent)
        assert "5 days" in agent.last_prompt

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

    def test_command_is_case_insensitive(self):
        """parts[0].lower() — uppercase slash commands should still match."""
        agent = FakeAgent()
        dispatch.dispatch("/DIGEST 10", agent)
        assert agent.last_prompt == "Generate a team digest for the last 10 days"


# =========================================================================
# 3. ARG_COMMANDS handling
# =========================================================================

class TestArgCommands:
    def test_prep_1on1_with_alias_substitutes_arg(self):
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/prep-1on1 jsmith", agent)
        assert handled is True
        assert "jsmith" in agent.last_prompt
        assert agent.last_prompt == "Generate a 1:1 prep brief for my meeting with jsmith"

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
        the user — it's the only ARG-style command with a sensible default."""
        agent = FakeAgent()
        result, handled = dispatch.dispatch("/prep-meeting", agent)
        assert handled is True
        assert result == "AGENT_RESPONSE"
        assert agent.last_prompt == "Generate a prep brief for my meeting: my next meeting"


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
