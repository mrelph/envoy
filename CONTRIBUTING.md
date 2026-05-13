# Contributing to Envoy

## Development Setup

```bash
git clone https://github.com/mrelph/envoy.git
cd envoy
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Project Layout

```
envoy/
├── envoy                    # Bash entrypoint (auto-installs venv)
├── cli.py                   # CLI commands (Click) → agent prompts
├── agent.py                 # Strands agent factory + system prompt
├── tui.py                   # Textual TUI (default interface)
├── tui.css                  # TUI stylesheet
├── dispatch.py              # Shared command dispatch (TUI + REPL)
├── repl.py                  # Plain text REPL fallback
├── ui.py                    # MCP health checks + model catalog
├── tools.py                 # Strands @tool definitions + worker routing
├── supervisor.py            # Parallel data gathering + context
├── init_cmd.py              # envoy init / settings interactive setup
├── envoy_logger.py          # Structured JSON logging
├── templates/
│   ├── commands.md          # Core command prompts (editable)
│   ├── skills/              # Bundled Agent Skills (11 skills)
│   └── soul.md / envoy.md / process.md  # Config templates
├── agents/
│   ├── base.py              # MCP connections (persistent), Bedrock client, run() helper
│   ├── workers/             # Domain-specific Strands worker agents
│   │   ├── __init__.py      # Worker factory + shared infra (_model, _USER, get_worker)
│   │   ├── email_worker.py  # Email operations worker
│   │   ├── comms_worker.py  # Slack + EA delegation worker
│   │   ├── calendar_worker.py   # Calendar management worker
│   │   ├── productivity_worker.py  # To-dos, tickets, memory, cron
│   │   ├── research_worker.py     # Phonetool, Kingpin, Wiki, web search, InstructAI, QuickSight
│   │   └── sharepoint_worker.py   # SharePoint/OneDrive worker
│   ├── skills.py            # Agent Skills loader (agentskills.io)
│   ├── skill_builder.py     # /build-skill + /suggest-skills generators
│   ├── learning.py          # Active learning loop (reflection, correction, self-analysis)
│   ├── workflows.py         # Compound commands (digest, catchup, etc.)
│   ├── heartbeat.py         # Autonomous heartbeat + routines
│   ├── watcher.py           # Long-running background watcher (envoy watch)
│   ├── email.py             # Email: send/reply/draft (CC/BCC), read full threads, classify, flag, attachments, contacts
│   ├── slack_agent.py       # Slack: scan (user resolution + threads), send (DM/channel/threaded), reactions, drafts, files, Lists
│   ├── calendar.py          # Calendar: view, create (recurring/optional attendees/resources), shared calendars
│   ├── todo.py              # To-Do: list, add (due dates/importance/reminders), complete, update, delete
│   ├── people.py            # Phonetool domain agent
│   ├── sharepoint_agent.py  # SharePoint/OneDrive domain agent
│   ├── tickets.py           # Tickets domain agent
│   ├── memory2.py           # Entity-aware persistent memory
│   ├── observer.py          # Backward-compat shim — redirects to memory2.remember()
│   ├── internal.py          # Internal websites (Kingpin, Wiki, Taskei)
│   ├── export.py            # Word/PowerPoint export
│   └── teamsnap_agent.py    # TeamSnap integration
```

## Architecture

### Request Flow

1. User types in TUI (`tui.py`) or plain REPL (`repl.py`) or runs CLI subcommand (`cli.py`)
2. Slash commands are parsed by `dispatch.py`; freeform input goes directly to the Strands agent
3. The supervisor agent (`agent.py` + `tools.py`) routes to specialized workers
4. Workers (`agents/workers/`) have focused toolsets and run on appropriate model tiers
5. Workers call domain agents (`agents/*.py`) which talk to MCP servers via persistent connections
6. Results flow back through the supervisor to the TUI/REPL

### Worker Agents

| Worker | Model Tier | Tools | Domain |
|---|---|---|---|
| Email | Medium | inbox, read full threads, search, send (CC/BCC), reply, forward, draft, move, flag/categorize/importance, cleanup, digest, contacts, attachments | Email operations |
| Comms | Medium | Slack scan (user ID resolution + thread replies), send (DM/channel/threaded), search, mark read, reactions, drafts, file downloads, Slack Lists, EA delegation | Slack messaging |
| Calendar | Light | view, create (recurring, optional attendees, room resources, reminders, showAs, all-day), find times, book rooms, shared calendars | Calendar management |
| Productivity | Medium | to-dos (list, add with due dates/importance/reminders, complete, update, delete), tickets, memory, cron, briefings | Task management |
| Research | Medium | Phonetool, Kingpin, Wiki, Taskei, Broadcast, web search (Brave), InstructAI, QuickSight Q | Internal & external lookups |
| SharePoint | Medium | search, files, read, write, lists, analyze | SharePoint/OneDrive |

### MCP Servers

All MCP connections are managed in `agents/base.py` via async context managers:

```python
from agents.base import outlook, builder, slack, sharepoint

async with outlook() as session:
    result = await session.call_tool("email_search", {"query": "..."})
```

| Server | Context Manager | Purpose |
|---|---|---|
| `builder-mcp` | `builder()` | Phonetool, Wiki, Taskei, Broadcast |
| `aws-outlook-mcp` | `outlook()` | Email, calendar, to-do |
| `slack-mcp` | `slack()` | Slack channels, DMs (with `ai-community-slack-mcp` fallback) |
| `amazon-sharepoint-mcp` | `sharepoint()` | SharePoint/OneDrive |
| `kingpin-mcp` | `kingpin()` | Kingpin goals, projects, milestones |
| `instructai-mcp` | `instructai()` | InstructAI business questions |
| `amazon-quick-mcp` | `quicksight()` | QuickSight Q dashboards/topics |
| `node ~/TeamSnapMCP/dist/wrapper.js` | `teamsnap()` | TeamSnap (kids' sports) |

User overrides for any MCP server live in `~/.envoy/mcp.json` (standard `mcpServers` shape — entries override built-ins by name, new names are added). Manage interactively with `/mcp add|remove|list`.

### MCP Capability Coverage

Each domain agent fully utilizes its MCP server's capabilities:

**Email (aws-outlook-mcp)**
- `email_send` — with CC/BCC support
- `email_reply` / `email_forward` — full thread context
- `email_draft` — with CC/BCC
- `email_read` — full thread bodies (used in classify, yesterbox, commitments, follow-up, response drafting)
- `email_search` — with folder and date filtering
- `email_inbox` / `email_folders` / `email_list_folders` — folder browsing with query
- `email_move` — move/delete
- `email_update` — flag (with due dates), categorize, set importance
- `email_attachments` — download and inspect attachments
- `email_contacts` — contact lookup
- `email_categories` — available categories

**Slack (ai-community-slack-mcp)**
- `list_channels` — DMs, group DMs, public/private channels
- `batch_get_conversation_history` — channel messages
- `batch_get_thread_replies` — threaded conversation context
- `batch_get_user_info` — resolve user IDs to real names
- `batch_get_channel_info` — channel metadata
- `post_message` — DMs, channels, and threaded replies (via threadTs)
- `open_conversation` — open DMs (single or group)
- `search` — message search
- `batch_set_last_read` — mark channels read
- `reaction_tool` — add/remove emoji reactions
- `create_draft` / `list_drafts` — draft management
- `download_file_content` — file and canvas downloads
- `get_channel_sections` — sidebar section awareness
- `lists_items_list` / `lists_items_info` — Slack Lists

**Calendar (aws-outlook-mcp)**
- `calendar_view` — day/week view, shared calendars
- `calendar_meeting` — create/read/update/delete with recurrence, optional attendees, room resources, reminders, showAs, isAllDay
- `calendar_availability` — multi-user availability check
- `calendar_room_booking` — room search
- `calendar_search` — event search
- `calendar_shared_list` — list shared calendars

**To-Do (aws-outlook-mcp)**
- `todo_lists` — list, create, update, delete lists
- `todo_tasks` — list, create (with due dates/importance/reminders), get, update, delete, complete
- `todo_checklist` — subtask management

### Agent Skills

Skills follow the [Agent Skills](https://agentskills.io) open standard. The loader (`agents/skills.py`) scans:
- `~/.envoy/skills/` and `~/.agents/skills/` (user-level)
- `./.envoy/skills/` and `./.agents/skills/` (project-level)

Bundled skills live in `templates/skills/` and are copied to `~/.envoy/skills/` on install/init.

## Adding Features

### Adding a new core command

1. Add the prompt template to `templates/commands.md`
2. Add the CLI subcommand in `cli.py`
3. Add the slash command to the `COMMANDS` dict in `dispatch.py` (and to `COMMAND_GROUPS` for `/help`)
4. If it needs a compound workflow, add it to `agents/workflows.py`

### Adding a new skill

1. Create `templates/skills/my-skill/SKILL.md` with YAML frontmatter (`name`, `description`) and markdown instructions
2. The skill is auto-discovered and available via `activate_skill`
3. Add a slash command mapping in `dispatch.py` if desired
4. Or just run `/build-skill <description>` inside Envoy and let `agents/skill_builder.py` generate one for you

### Adding a new worker agent

1. Create the domain agent in `agents/my_agent.py` (async MCP wrappers)
2. Add MCP params to `agents/base.py` if it's a new MCP server
3. Create `agents/workers/my_worker.py` with a `create()` function that returns an `Agent`
4. Import shared infra from `agents.workers` (`_model`, `_USER`) and `run` from `agents.base`
5. Register in `agents/workers/__init__.py`: add to factory imports and `WORKER_NAMES`
6. Add the `my_worker` delegate tool in `tools.py`
7. Add to `_ALL_TOOLS_RAW`

### Adding a new MCP server

1. Add params to `_MCP_PARAM_DEFS` dict in `agents/base.py`
2. Create a session factory: `my_server = _mcp_session("MyServer")`
3. Create async wrapper functions in a new `agents/my_agent.py`

## Security Notes

- Cron commands are whitelisted to known envoy subcommands; shell metacharacters rejected
- Self-modification tools require user confirmation before writing
- Memory files enforce 2MB size limits
- MCP server stderr is suppressed (routed to `/dev/null`)
- Never store credentials in code — use `.env` or `aws login`

## Dependencies

| Package | Purpose |
|---|---|
| `strands-agents` | Agent framework (Bedrock integration) |
| `mcp` | MCP Python SDK for server communication |
| `click` | CLI framework |
| `rich` | Terminal formatting, panels, tables |
| `textual` | Full-screen TUI framework (built on Rich) |
| `boto3` / `botocore[crt]` | AWS SDK for Bedrock |
| `python-dotenv` | Load `.env` credentials |
| `python-docx` | Word document generation |
| `python-pptx` | PowerPoint generation |
| `markdown` | Markdown processing |

## Tests

Unit tests live under `tests/unit/`. They stub out `strands` and `mcp` at import time so no MCP servers, AWS creds, or network access are required.

```bash
./venv/bin/pytest tests/ -q              # full suite
./venv/bin/pytest tests/unit/test_dispatch.py -v   # one file
```

Shared fixtures (`tests/conftest.py`):
- `envoy_home` — redirects `$HOME` so `~/.envoy` writes land in a tmpdir
- `fake_mcp_result(value)` — builds a fake MCP `CallToolResult` from a Python value
- `no_ai` — stubs `invoke_ai` across `agents.base` and re-exporting modules; returns a recorder list

Coverage is concentrated on parsing, dispatch, cron validation, memory, learning, skills, and supervisor context. AI calls and MCP I/O are intentionally not exercised — those are integration concerns.

## Code Style

- Domain agents are async; workers and tools bridge to sync via `run()` from `agents.base`
- MCP connections are persistent — subprocess stays alive across calls via a shared background event loop
- Heavy imports (strands, mcp, boto3) are lazy-loaded on first use, not at module import time
- Worker agents use `callback_handler=None` to suppress streaming output
- Error handling returns graceful messages, never crashes the TUI
- Analytical workflows read full email bodies (not just previews) before AI classification
- Slack scans resolve user IDs to names and include thread replies for full context
