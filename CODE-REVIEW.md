# Envoy Code Review — Recommendations

_Reviewed: 2026-04-20_

Overall assessment: Solid, coherent project. Clean layered architecture (supervisor → workers → MCP), progressive disclosure of skills, persistent MCP sessions, and sensible defaults. The main issues are consistency gaps, leaky internals, partial handling of paths that should be unified, and a handful of real bugs.

---

## High priority

### 1. REPL is out of sync with TUI for system commands
- `repl.py` handles `/settings`, `/backup` but NOT `/models`, `/mwinit`, or `/skills`. So `/models` falls through to `dispatch` → returns `("/models", False)` → REPL does nothing (same bug recently fixed in TUI still exists in REPL).
- **Fix:** Port `_handle_models` logic into REPL, or better — move it into `dispatch.py` so both front-ends share it. Same pattern for `/skills` (already in dispatch) vs the ad-hoc `/status`, `/settings`, `/backup` checks in REPL.

### 2. `dispatch.py` signature mismatch vs. docstring
- Docstring says `dispatch → (prompt_for_agent, needs_input_field, input_label)` but the actual return is `(result_or_cmd, handled)`. That's a 2-tuple, not a 3-tuple. Callers rely on the 2-tuple, so just fix the docstring.

### 3. Token leak of `set_user_input` on the callback handler but never called
- `agent.py` attaches `reasoning_callback_handler.set_user_input` and stores it on `agent._reasoning_callback`, but nothing in the codebase actually invokes it. Either wire it into `_run_command` before dispatch (for user-turn attribution in logs) or remove the dead branch.

### 4. `gather()` race + accidental context wipes
- `gather()` calls `clear_context()` at entry. If the agent issues two `gather` calls in one turn (e.g., during a briefing), the first one's ref IDs become stale mid-response. The single `_context` is not thread-safe either — TUI uses `@work(thread=True)` so two concurrent commands can step on each other.
- **Fix:** Scope context by session_id, or at least guard with a `threading.Lock` and don't clear on subsequent same-session gathers (merge / re-number instead).

### 5. Persistent MCP session dead-connection handling is subtly broken
- In `_mcp_session`, the `try: yield session` cannot actually detect a dead connection — yielding doesn't exercise the transport. If the subprocess died, the `call_tool` inside the caller raises, the connection is never removed from `_persistent`, and every subsequent call sees the same dead session until the process dies or manual clear.
- **Fix:** Wrap the yielded session with a lightweight `call_tool` that on specific transport errors removes `_persistent[server_name]` and retries once.

### 6. Cron command validator is wrong
- In `manage_cron`: `first_word = command.strip().split()[0]`. The user passes commands like `digest --days 7 --email`, which works. But the description in `cron presets` says `envoy digest --days ...` — if a user follows that format literally, `first_word` becomes `"envoy"` → rejected.
- Also, `schedule` is never validated (e.g., `"0 8 * * * ; rm -rf /"`) — the `_DANGEROUS_CHARS` check only runs on `command`. Add the same check on `schedule` and `name`.

### 7. `cron` exec path lookup is broken
- `_envoy_path()` resolves `os.path.abspath(os.path.join(os.path.dirname(__file__), "envoy"))`. But `tools.py` is in the project root, so `__file__` dir IS the project root — this actually works. However when installed via symlink in `/usr/local/bin/envoy`, users will expect to run `envoy` (the symlink), not `/home/alice/envoy/envoy`. If the repo moves, cron jobs break silently. Consider resolving `shutil.which("envoy")` first.

### 8. Background `git fetch` in the `envoy` wrapper blocks startup anyway
- The script launches `(...) &` and then immediately `wait $UPDATE_PID`, which defeats the backgrounding. Every startup pays for a network fetch. Either drop the `wait` or run it truly detached so users aren't blocked when offline / on bad wifi.

---

## Medium priority

### 9. Importing from private names across modules
- `tools.py` imports `_load_models`, `_persistent`, etc. from `agents.base`. `tui.py` imports `_load_models` too. Leading-underscore names shouldn't leak. Either promote to public (`load_models`) or expose a narrow accessor like `current_models()`.

### 10. `_demo_wrap` patches `t._tool_func` in place
- This is framework-internal surgery on Strands' `@tool`. It'll break when Strands upgrades. Wrap at call-time via `logged_tool` or a proper decorator that preserves tool metadata.

### 11. Two independent memory/observer pipelines write to the same place
- `tools._delegate` calls `memory.remember(...)` AND `observer.observe(...)` AND `observer.maybe_analyze()` on every single worker call. `tui._run_command` also calls `observer.observe(...)` on every command. You're double-logging. Pick one boundary.

### 12. Default model `us.anthropic.claude-opus-4-6-v1` is used for the *agent* tier — expensive for a REPL
- Fine as a default for `heavy`, but the supervisor agent fires on every prompt. `claude-sonnet-4` is probably a better default here; power users who want Opus will say so. Either way, make the tradeoff visible in the README and in `/models` output (add a "cost hint" column).

### 13. `_get_bedrock_client()` TTL doesn't refresh if creds are bad
- Caches 50min but never catches `ExpiredTokenException`. A long-running session (heartbeat cron) will fail silently past the token lifetime. Wrap `invoke_ai` to catch `ExpiredTokenException` → null the cache → retry once.

### 14. `invoke_ai` silently strips `reasoningContent` when both text and thinking blocks are present
- It picks the first text block and returns. For thinking models (`deepseek.r1`, `kimi-k2-thinking`), the user loses the reasoning entirely. OK if intentional — but document it.

### 15. `_mask_output` in demo mode is applied per-tool but not to Markdown output from the main agent
- The system prompt gets masked (`_build_system_prompt`), worker outputs get masked (`_demo_wrap`), but the final Markdown from `agent(prompt)` rendered in TUI doesn't go through `_mask_output`. Demo mode will leak names through the supervisor's synthesis.

### 16. `parse_email_search_result` swallows all errors and returns `[]`
- If Outlook MCP returns a new schema, you'll get "No emails found" forever with no diagnostic. At minimum, log the exception at WARNING, not just the masked `log_error` call (which, by the way, isn't a public method in the shown snippet — confirm `get_logger().log_error` exists).

### 17. Hardcoded `~/.envoy/...` paths appear in 15+ modules
- Centralize as `CONFIG_DIR` constants in one place (e.g., `agents/base.py`) so tests can override via an env var.

### 18. The TUI's "Submit on Enter" via `TextArea.Changed` is fragile
- `on_input_changed` triggers on every keystroke. Fine for small text, but pasted multi-line content with a trailing newline submits instantly. Most users expect Ctrl+Enter to submit in a multi-line area. Consider `Input` widget for single-line; keep `TextArea` only if explicitly multi-line, and bind `Enter` via key handler, not via `Changed`.

### 19. `_get_hint` keyword matching is order-sensitive and overlapping
- `"meeting"` → Calendar, `"prep-meeting"` → Prep? With dict ordering, the first match in `SPINNER_HINTS.items()` wins, so `/prep-meeting` shows `📅 Calendar`, not `🧩 Prep`. Order more specific keys first, or use a regex table.

### 20. `SUPERVISOR_TOOLS` duplicates `search_emails` / `lookup_person` with worker equivalents
- Both `research_worker` and `supervisor.lookup_person` can look up Phonetool; both `email_worker.search_email` and `supervisor.search_emails` search email. The agent has to choose and sometimes picks wrong. Either mark one as "preferred" in tool docstrings or remove duplication.

---

## Low priority / polish

### 21. `_handle_models` doesn't validate `model_id` against the catalog
- A typo writes arbitrary text to `models.json` and all future calls fail at Bedrock. Add a check: if `model_id not in {m[0] for m in MODEL_CATALOG}`, warn but allow (user may know a newer ID).

### 22. `update_soul` / `update_envoy` / `update_process` append without de-duplication
- After a year, `soul.md` has 500 lines of "be concise". Consider diffing before append or offering an AI-driven compact step.

### 23. `backup.py` includes `memory/` and `skills/` wholesale
- Skills are often symlinked or sourced from repos. Back those up by path reference, not content — or exclude by default.

### 24. `_check_mcp_servers` ignores exceptions entirely
- `check_mcp_connections` returns a dict on failure (`{}`), so MCP status displays blank. Surface at least one error line in the TUI when all servers are down.

### 25. `VERSION` file read at import time, no try/except
- `tui.py` and `cli.py` both do `open(...).read()` at import. If the file is ever missing (container build, etc.), the whole import chain dies. Default to `"0.0.0-dev"` on failure.

### 26. Large functions in `workflows.py` all follow the same pattern (gather → prompt → invoke_ai)
- You have ~10 of these. A `_ai_report(sections, prompt_template, alias, days, tier="heavy")` helper would cut ~200 lines and reduce copy-paste drift (e.g., one forgets the error handler, another uses `max_tokens=10000` vs `8000` inconsistently).

### 27. Error strings sometimes start with "⚠️", sometimes "Error:", sometimes plain
- Standardize. A simple `format_error(context, exc) -> str` would help both readability and later grep/log scraping.

### 28. No tests in the tree
- For a 40-file agentic system with a lot of string parsing (email IDs, cron expressions, ref IDs) this is risky. Even 3–4 smoke tests for `dispatch`, `_mcp_session` with a mock session, and `parse_email_search_result` on a captured payload would catch most regressions.

---

## Concrete quick wins (in order)

1. Move `/models` handling into `dispatch.py` so REPL works too.
2. Validate `schedule` and `name` in `manage_cron` the same way `command` is validated.
3. Drop the `wait $UPDATE_PID` in the `envoy` wrapper.
4. Add dead-connection retry inside `_mcp_session`.
5. Add `ExpiredTokenException` handling in `invoke_ai`.
6. Fix `_get_hint` ordering so `prep-*` wins over `meeting`/`calendar`.
7. Guard `_context` with a `threading.Lock`, or scope it by session.
8. Centralize `~/.envoy` paths into a single `paths.py`.
