# Contributing to Direct Reports Email Digest

## Development Setup

```bash
# Clone the repo
cd directs-digest

# Create virtual environment (or let the entrypoint script do it automatically)
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Project Layout

```
directs-digest/
├── directs-digest          # Bash entrypoint — auto-creates venv, runs cli.py
├── cli.py                  # CLI interface (Click + Rich)
├── service.py              # Core business logic
├── agent_handler.py        # AgentCore deployment handler
├── agent_config.json       # AgentCore configuration
├── requirements.txt        # Python dependencies
├── .env.example            # AWS credentials template
└── .gitignore
```

## Key Components

### `directs-digest` (entrypoint)

Bash wrapper that:
1. Resolves its own location (handles symlinks)
2. Creates a Python venv if missing
3. Installs dependencies into the venv
4. Executes `cli.py` with all passed arguments

### `cli.py`

Built with [Click](https://click.palletsprojects.com/) and [Rich](https://rich.readthedocs.io/). Two commands:

- `interactive` — TUI mode with prompts for all options
- `generate` — Non-interactive CLI with flags

Both commands use `DirectsDigestService` from `service.py` for all logic.

### `service.py` — `DirectsDigestService`

All MCP and AI interactions live here. Key methods:

| Method | What it does |
|---|---|
| `get_direct_reports(alias)` | Calls `builder-mcp` → Phonetool to get direct reports |
| `get_management_chain(alias, levels)` | Walks up the management chain (VIP mode) |
| `get_recent_emails(alias, days)` | Calls `aws-outlook-mcp` → Outlook email search |
| `generate_digest(alias, days, selected, vip)` | Orchestrates data collection, returns markdown |
| `generate_ai_summary(digest, alias, days)` | Sends digest to Bedrock Claude, returns analysis |
| `extract_action_items(summary)` | Parses `### Actions & High Priority` sections from AI output |
| `email_digest(digest, alias, days)` | Converts markdown → HTML, sends via Outlook MCP |
| `add_to_todo(items, list_name)` | Creates tasks in Microsoft To-Do via MCP |

### MCP Server Communication

The service uses the [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) to communicate with external tools:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Each MCP server is configured as StdioServerParameters
self.builder_mcp_params = StdioServerParameters(command="builder-mcp", args=[])

# Usage pattern: open connection, create session, call tools
async with stdio_client(self.builder_mcp_params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        result = await session.call_tool("ReadInternalWebsites", arguments={...})
```

### AI Integration

Uses Amazon Bedrock with `us.anthropic.claude-opus-4-6-v1`. The prompt in `generate_ai_summary()` asks Claude to produce:

1. Top 3-5 highest priority items across all directs
2. Per-person sections with summary, email list, and action items

Credentials are loaded from `.env` first, falling back to the default AWS credential chain.

## Adding Features

### Adding a new output format

1. Add the CLI flag in `cli.py` (both `generate` and `interactive` commands)
2. Implement the output logic in `service.py`
3. Wire it up in both command handlers

### Adding a new MCP server

1. Add `StdioServerParameters` in `DirectsDigestService.__init__()`
2. Create async methods that use `stdio_client()` + `ClientSession`
3. Wrap async methods with sync wrappers using `asyncio.run()`

### Modifying the AI prompt

Edit the `prompt` string in `service.py` → `generate_ai_summary()`. The prompt defines the exact output format, so changes there will affect `extract_action_items()` parsing.

## Dependencies

| Package | Purpose |
|---|---|
| `mcp` | MCP Python SDK for server communication |
| `click` | CLI framework |
| `rich` | Terminal formatting, progress bars, tables |
| `boto3` / `botocore[crt]` | AWS SDK for Bedrock API calls |
| `python-dotenv` | Load `.env` file for AWS credentials |

## Testing

```bash
# Test MCP connectivity
python3 test_mcp.py

# Test the agent handler locally
python3 agent_handler.py
```

## Code Style

- Async methods prefixed with `_` and suffixed with `_async` (e.g., `_generate_digest_async`)
- Public sync wrappers call `asyncio.run()` on the async versions
- MCP connections are opened per-call (not persistent) using `async with` context managers
- Error handling prints to console and returns graceful fallback values
