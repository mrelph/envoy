# CLAUDE.md

Envoy is an AI chief-of-staff CLI/TUI (Python) that manages email, Slack, calendar, to-dos, and SharePoint. Built on the Strands Agents framework with Claude via Amazon Bedrock; all external data flows through MCP servers.

## Commands

```bash
./install.sh                                # one-time setup (creates venv, installs deps)
./envoy                                     # run — bash wrapper, auto-creates venv, launches TUI
./venv/bin/pytest tests/ -q                 # full test suite
./venv/bin/pytest tests/unit/test_dispatch.py -v   # single test file
```

No linter/formatter is configured. There is no pyproject.toml or setup.py — modules live at the repo root and `tests/conftest.py` adds the root to `sys.path`.

## Architecture

Request flow: `envoy` (bash wrapper) → `cli.py` (Click) → `tui.py` (Textual TUI, default) or `repl.py` (fallback) → `dispatch.py` (slash-command parsing; freeform goes to agent) → `agent.py` (supervisor Strands agent) → `tools.py` (worker-delegate @tool defs) → `agents/workers/*` (domain workers, per-tier models) → `agents/*.py` (async domain agents) → MCP servers via `agents/base.py`.

- `agents/base.py` — persistent MCP connections (subprocess kept alive on a shared background event loop), Bedrock client, sync `run()` bridge
- `agents/workers/__init__.py` — worker factory, shared infra (`_model`, `_USER`, `WORKER_NAMES`)
- `supervisor.py` — parallel multi-source `gather` + cross-referencing
- `templates/commands.md` — prompt templates for core commands; `templates/skills/` — bundled Agent Skills (agentskills.io standard)
- User config/state lives in `~/.envoy/` (soul.md, envoy.md, process.md, models.json, mcp.json, skills/) — never in the repo

## Adding things (see CONTRIBUTING.md for full steps)

- New core command: prompt in `templates/commands.md` → subcommand in `cli.py` → `COMMANDS` + `COMMAND_GROUPS` dicts in `dispatch.py`
- New worker: `agents/my_agent.py` (async MCP wrappers) → `agents/workers/my_worker.py` with `create()` → register in `agents/workers/__init__.py` → delegate tool in `tools.py` + `_ALL_TOOLS_RAW`
- New MCP server: `_MCP_PARAM_DEFS` in `agents/base.py` + `_mcp_session("Name")` factory

## Conventions

- Domain agents are async; workers/tools bridge to sync via `run()` from `agents.base`
- Heavy imports (strands, mcp, boto3) are lazy-loaded inside functions, never at module top
- Worker agents pass `callback_handler=None` to suppress streaming output
- Errors return graceful messages — never crash the TUI
- AI model IDs are configured per tier in `~/.envoy/models.json` (live Bedrock catalog via `/models`) — do not hardcode model IDs

## Tests

- Unit tests only (`tests/unit/`); `tests/conftest.py` stubs `strands`, `mcp`, `boto3` at import time — no MCP servers, AWS creds, or network needed
- Fixtures: `envoy_home` (redirects `$HOME` to tmpdir), `fake_mcp_result(value)`, `no_ai` (stubs `invoke_ai`, returns recorder list)
- AI calls and MCP I/O are intentionally untested — keep it that way for new unit tests

## Gotchas

- The `envoy` wrapper runs a git-tag update check on launch; many MCP servers (builder-mcp, aws-outlook-mcp, etc.) are Amazon-internal and unavailable off-network — tests don't need any of this
- Project structure is documented in both README.md and CONTRIBUTING.md; keep both in sync when moving files
- `soul.md` / `envoy.md` in the repo root are gitignored personal config copies; real files live in `~/.envoy/`
- Version is read from the `VERSION` file (currently 3.4.0); release tags are `v*`
