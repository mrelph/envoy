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
├── repl.py                  # Interactive REPL with slash commands
├── ui.py                    # Rich console rendering
├── tools.py                 # Strands @tool definitions + worker routing
├── supervisor.py            # Parallel data gathering + context
├── init_cmd.py              # envoy init / settings interactive setup
├── envoy_logger.py          # Structured JSON logging
├── cot_renderer.py          # Chain-of-thought log renderer
├── templates/
│   ├── commands.md          # Core command prompts (editable)
│   ├── skills/              # Bundled Agent Skills (8 skills)
│   └── soul.md / envoy.md / process.md  # Config templates
├── agents/
│   ├── base.py              # MCP connections, Bedrock client, AI invocation
│   ├── workers.py           # Domain-specific Strands worker agents (6 workers)
│   ├── skills.py            # Agent Skills loader (agentskills.io)
│   ├── workflows.py         # Compound commands (digest, catchup, etc.)
│   ├── email.py             # Email domain agent
│   ├── slack_agent.py       # Slack domain agent
│   ├── calendar.py          # Calendar domain agent
│   ├── todo.py              # To-Do domain agent
│   ├── people.py            # Phonetool domain agent
│   ├── sharepoint_agent.py  # SharePoint/OneDrive domain agent
│   ├── tickets.py           # Tickets domain agent
│   ├── memory.py / memory2.py  # Persistent memory
│   ├── observer.py          # Observer/learning agent
│   ├── internal.py          # Internal websites (Kingpin, Wiki, Taskei)
│   ├── export.py            # Word/PowerPoint export
│   └── teamsnap_agent.py    # TeamSnap integration
```

## Architecture

### Request Flow

1. User types in REPL (`repl.py`) or runs CLI subcommand (`cli.py`)
2. Slash commands map to agent prompts; freeform input goes directly to the Strands agent
3. The supervisor agent (`agent.py` + `tools.py`) routes to specialized workers
4. Workers (`agents/workers.py`) have focused toolsets and run on appropriate model tiers
5. Workers call domain agents (`agents/*.py`) which talk to MCP servers
6. Results flow back through the supervisor to the user

### Worker Agents

| Worker | Model Tier | Tools | Domain |
|---|---|---|---|
| Email | Medium | inbox, search, send, reply, cleanup, digest | Email operations |
| Comms | Medium | Slack scan, DM, channel history, mark read | Slack messaging |
| Calendar | Light | view, create, find times, book rooms | Calendar management |
| Productivity | Medium | to-dos, tickets, memory, cron, briefings | Task management |
| Research | Light | Phonetool, Kingpin, Wiki, Taskei, Broadcast | Internal lookups |
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
| `builder-mcp` | `builder()` | Phonetool, Kingpin, Wiki, Taskei |
| `aws-outlook-mcp` | `outlook()` | Email, calendar, to-do |
| `ai-community-slack-mcp` | `slack()` | Slack channels, DMs |
| `amazon-sharepoint-mcp` | `sharepoint()` | SharePoint/OneDrive |

### Agent Skills

Skills follow the [Agent Skills](https://agentskills.io) open standard. The loader (`agents/skills.py`) scans:
- `~/.envoy/skills/` and `~/.agents/skills/` (user-level)
- `./.envoy/skills/` and `./.agents/skills/` (project-level)

Bundled skills live in `templates/skills/` and are copied to `~/.envoy/skills/` on install/init.

## Adding Features

### Adding a new core command

1. Add the prompt template to `templates/commands.md`
2. Add the CLI subcommand in `cli.py`
3. Add the slash command in `repl.py`
4. If it needs a compound workflow, add it to `agents/workflows.py`

### Adding a new skill

1. Create `templates/skills/my-skill/SKILL.md` with YAML frontmatter (`name`, `description`) and markdown instructions
2. The skill is auto-discovered and available via `activate_skill`
3. Add a slash command mapping in `repl.py` if desired

### Adding a new worker agent

1. Create the domain agent in `agents/my_agent.py` (async MCP wrappers)
2. Add MCP params to `agents/base.py` if it's a new MCP server
3. Add `_create_my_worker()` in `agents/workers.py` with focused tools
4. Register in the worker factory and `WORKER_NAMES`
5. Add the `my_worker` delegate tool in `tools.py`
6. Add to `_ALL_TOOLS_RAW`

### Adding a new MCP server

1. Add `StdioServerParameters` in `agents/base.py`
2. Create a context manager: `my_server = _mcp_session(MY_PARAMS, "MyServer")`
3. Register in `MCP_SERVERS` dict
4. Create async wrapper functions in a new `agents/my_agent.py`

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
| `boto3` / `botocore[crt]` | AWS SDK for Bedrock |
| `python-dotenv` | Load `.env` credentials |
| `python-docx` | Word document generation |
| `python-pptx` | PowerPoint generation |
| `markdown` | Markdown processing |

## Code Style

- Domain agents are async; workers wrap with `asyncio.run()`
- MCP connections use `async with` context managers (not persistent)
- Worker agents use `callback_handler=None` to suppress streaming output
- Error handling returns graceful messages, never crashes the REPL
