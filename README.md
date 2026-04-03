# Envoy

Your AI chief of staff from the command line. Manage email, Slack, calendar, to-dos, SharePoint, and more — powered by Claude via Amazon Bedrock.

## How It Works

```
Phonetool        Outlook          Slack           SharePoint       Amazon Bedrock
(builder-mcp)    (aws-outlook-mcp) (slack-mcp)    (sharepoint-mcp)  (Claude)
     │                │               │                │               │
     ▼                ▼               ▼                ▼               ▼
  People ──────► Email/Cal/Todo ► Messages ──────► Documents ──► AI Analysis
                                                                       │
                                                        ┌──────────────┼──────────────┐
                                                        ▼              ▼              ▼
                                                     Console        Email/Slack    To-Do
```

## Quick Start

```bash
git clone https://github.com/mrelph/envoy.git
cd envoy
./install.sh
envoy init       # configure identity + agent personality
envoy            # launch interactive REPL
```

See [INSTALL.md](INSTALL.md) for detailed setup instructions.

## Interactive REPL

Running `envoy` opens the REPL with slash commands and natural language chat:

```
markrelp · Mon 8:03am › /briefing
⠋ 📊 Gathering data…

markrelp · Mon 8:04am › prep for my 1:1 with jsmith
⠋ 🧩 Loading skill…

markrelp · Mon 8:05am › /digest 7
⠋ 📧 Email…
```

Type `/help` to see all commands. Most accept a number of days: `/digest 7`, `/catchup 3`, `/followup 14`.

## Features

### Core Commands (built-in)

| Command | Slash | Description |
|---|---|---|
| `envoy digest` | `/digest` | Team email digest with AI analysis |
| `envoy digest --vip` | `/boss` | Track your management chain's emails |
| `envoy cleanup` | `/cleanup` | AI-powered inbox junk cleanup (with confirmation) |
| `envoy customers` | `/customers` | External customer emails with action items |
| `envoy catchup` | `/catchup` | PTO catch-up — email, Slack, calendar, to-dos |
| `envoy yesterbox` | `/yesterbox` | Yesterday's DMs, prioritized |
| — | `/briefing` | Full morning briefing (calendar + email + Slack) |
| — | `/eod` | End-of-day summary |
| — | `/weekly` | Weekly review |
| — | `/todo` | Show pending action items |
| — | `/tickets` | Scan open tickets |

### Agent Skills (extensible)

Skills are loaded on demand via the [Agent Skills](https://agentskills.io) open standard. 8 bundled skills ship with Envoy:

| Skill | Slash | Description |
|---|---|---|
| `prep-1on1` | `/prep-1on1 alias` | 1:1 meeting prep brief |
| `prep-meeting` | `/prep-meeting` | Any meeting prep brief |
| `commitment-tracker` | `/commitments` | Track promises you made |
| `response-times` | `/response-times` | Email response patterns |
| `followup-tracker` | `/followup` | Unanswered sent emails |
| `calendar-audit` | `/cal-audit` | Meeting load & focus time |
| `slack-catchup` | `/slack-catchup` | Focused Slack catch-up |
| `teamsnap` | — | Kids' sports schedules |

Add your own: drop a folder with a `SKILL.md` into `~/.envoy/skills/` or `~/.agents/skills/`.

### Additional Capabilities

| Feature | Description |
|---|---|
| `/reply` | Reply to an email (interactive) |
| `/ea` | Delegate to your EA |
| `/book` | Book a meeting room |
| `/findtime` | Find available meeting times |
| `/search` | Search Slack history |
| `/sharepoint` | Search or browse SharePoint/OneDrive |
| `/cron` | Manage scheduled automation jobs |
| `/models` | View/edit AI model assignments |
| `/settings` | Edit personality and config |
| Export | Generate Word (.docx) and PowerPoint (.pptx) from any report |

### Heartbeat & Routines

Envoy can run autonomously on a schedule, checking your routines and alerting you:

| Command | Slash | Description |
|---|---|---|
| `envoy heartbeat` | `/heartbeat` | Run heartbeat check now |
| `envoy routine list` | `/routines` | View your routines |
| `envoy routine add` | `/routine` | Add a new routine |
| `envoy routine suggest` | `/suggest-routines` | AI-suggested routines |

## CLI Reference

Running `envoy` with no arguments opens the REPL. Subcommands are available for scripting:

```bash
envoy digest --days 7 --email --todo
envoy digest --vip --days 7 --slack
envoy cleanup --days 7 --limit 200
envoy customers --days 7 --team "alice,bob" --email
envoy catchup --days 5
envoy followup --days 7
envoy commitments --days 7
envoy prep-1on1 jsmith
envoy prep-meeting --meeting "Weekly Sync"
envoy cal-audit --days 5
envoy response-times --days 7
envoy slack-catchup --days 3
envoy yesterbox --days 1
envoy heartbeat --notify slack
envoy routine list
envoy routine add --order "Alert me if any sev-2 tickets go stale"
envoy routine suggest
envoy --help
```

### `envoy digest`

| Option | Short | Default | Description |
|---|---|---|---|
| `--alias` | `-a` | `$USER` | Manager alias |
| `--days` | `-d` | `14` | Days to look back |
| `--select` | `-s` | all | Comma-separated aliases to include |
| `--vip` | | off | Track bosses instead of directs |
| `--output` | `-o` | — | Save output to file |
| `--email` | `-e` | off | Email digest to yourself |
| `--slack` | | off | Send digest as Slack DM |
| `--todo` | `-t` | off | Add action items to To-Do |
| `--no-ai` | | off | Skip AI summary |
| `--no-display` | | off | Suppress console output |

### `envoy cleanup`

| Option | Short | Default | Description |
|---|---|---|---|
| `--days` | `-d` | `14` | Days to look back |
| `--limit` | `-l` | `100` | Max emails to scan |

### `envoy customers`

| Option | Short | Default | Description |
|---|---|---|---|
| `--alias` | `-a` | `$USER` | Your alias |
| `--days` | `-d` | `14` | Days to look back |
| `--team` | `-t` | auto | Comma-separated team aliases |
| `--output` | `-o` | — | Save output to file |
| `--email` | `-e` | off | Email report to yourself |
| `--slack` | | off | Send report as Slack DM |

### Other subcommands

| Command | Key Options |
|---|---|
| `envoy catchup` | `--days` (default: 5) |
| `envoy followup` | `--days` (default: 7) |
| `envoy commitments` | `--days` (default: 7) |
| `envoy cal-audit` | `--days` (default: 5) |
| `envoy response-times` | `--days` (default: 7) |
| `envoy slack-catchup` | `--days` (default: 3) |
| `envoy yesterbox` | `--days` (default: 1) |
| `envoy prep-1on1 <alias>` | Takes alias as argument |
| `envoy prep-meeting` | `--meeting` (default: next meeting) |
| `envoy heartbeat` | `--quiet`, `--notify` (slack/email/none) |
| `envoy routine` | `list`, `add`, `remove`, `suggest` |

## Automation

### Built-in Cron Management

```bash
envoy cron presets     # see available templates
envoy cron add --name weekly-digest --schedule "0 8 * * 1" --command "digest --days 7 --slack --no-display"
envoy cron add --name daily-heartbeat --schedule "0 8 * * *" --command "heartbeat --notify slack"
envoy cron list
envoy cron remove --name weekly-digest
```

### Manual Cron

```bash
# Weekly Monday digest via Slack
0 8 * * 1 /usr/local/bin/envoy digest --days 7 --slack --no-display

# Daily heartbeat check
0 8 * * * /usr/local/bin/envoy heartbeat --notify slack

# Daily customer scan
0 9 * * * /usr/local/bin/envoy customers --days 1 --slack
```

## AWS Credentials

Required for AI features. Uses Amazon Bedrock in `us-west-2`.

**Option 1: AWS CLI (recommended)**
```bash
aws login
```

**Option 2: `.env` file**
```bash
cp .env.example .env
# Edit with your AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
```

The tool tries `.env` first, then falls back to the default AWS credential chain.

## Architecture

### Worker Agents

The supervisor agent routes requests to specialized workers, each with focused toolsets:

| Worker | Tier | Tools | Domain |
|---|---|---|---|
| Email | Medium | inbox, read, search, send (with CC/BCC), reply (threaded), forward, manage (move/flag/categorize), cleanup, digest, contacts, attachments | Email operations |
| Comms | Medium | Slack scan (with user resolution + thread context), send messages (DMs, channels, threaded replies), search, mark read, reactions, drafts, file downloads, Slack Lists, EA delegation | Slack messaging |
| Calendar | Light | view, create (recurring, optional attendees, room resources), find times, book rooms, shared calendars | Calendar management |
| Productivity | Medium | to-dos (list, add with due dates/importance, complete, update, delete), tickets, memory, cron, briefings | Task management |
| Research | Medium | Phonetool, Kingpin, Wiki, Taskei, Broadcast, web search (Brave) | Internal & external lookups |
| SharePoint | Medium | search, files, read, write, lists, analyze | SharePoint/OneDrive |

### Supervisor Tools

The supervisor layer provides cross-domain capabilities:

| Tool | Purpose |
|---|---|
| `gather` | Parallel multi-source fetch with cross-reference intelligence |
| `read_email_thread` | Drill into specific emails (cached for follow-up) |
| `get_attachment` | Download and preview email attachments |
| `search_emails` | Targeted email search |
| `lookup_person` | Phonetool profile lookup |
| `current_time` | Live date/time/timezone |
| `show_context` | Inspect conversation context for drill-downs |

### Cross-Reference Intelligence

When gathering data from multiple sources, Envoy automatically extracts entities (people, projects, ticket IDs) and identifies overlaps. If Alice is mentioned in both an email and a Slack message, or a SIM ticket appears in email and your to-do list, the briefing surfaces these connections explicitly.

### MCP Servers

| Server | Purpose |
|---|---|
| `builder-mcp` | Phonetool, Kingpin, Wiki, Taskei, Broadcast, Meetings |
| `aws-outlook-mcp` | Email, calendar, to-do |
| `ai-community-slack-mcp` | Slack channels, DMs, search |
| `amazon-sharepoint-mcp` | SharePoint/OneDrive files and lists |

### AI Models

Configurable per tier via `/models` or `~/.envoy/models.json`:

| Tier | Used For | Default |
|---|---|---|
| Agent | Conversational REPL | Claude Opus |
| Heavy | Summaries, document analysis | Claude Opus |
| Medium | Classification, scans, workers | Claude Sonnet |
| Light | Simple extraction, lookups | Claude 3.5 Haiku |
| Memory | Memory compression | Nova Micro |

### Memory System

Envoy maintains persistent memory across sessions with entity-aware compression:

- **Raw entries**: Last 14 days of actions, decisions, and observations stored as JSONL
- **Entity index**: People, projects, and topics auto-extracted and indexed for fast recall
- **Per-entity summaries**: Older entries compressed into structured per-entity summaries (not a single blob)
- **Recall**: Query by entity for precise results, or general recall for recent context
- **Size limits**: 2MB cap with automatic pruning and compression

### Agent Skills

Skills follow the [Agent Skills](https://agentskills.io) open standard:
- Discovered from `~/.envoy/skills/`, `~/.agents/skills/`, `./.envoy/skills/`, `./.agents/skills/`
- Progressive disclosure: only name + description loaded at startup (~100 tokens/skill)
- Full instructions loaded on demand via `activate_skill` tool
- Cross-compatible with Claude Code, Kiro, and other skills-compatible agents

### Security

- Cron commands are whitelisted to known envoy subcommands; shell metacharacters rejected
- Self-modification tools (soul/envoy/process) require user confirmation before writing
- Memory files enforce 2MB size limits with automatic pruning
- Email deletion moves to Deleted Items (recoverable)
- MCP server stderr suppressed to prevent information leakage
- Demo mode masks all PII (names, emails, aliases)

## Project Structure

```
envoy/
├── envoy                    # Entrypoint (auto-installs venv)
├── cli.py                   # CLI commands → agent prompts
├── agent.py                 # Strands agent factory + system prompt
├── repl.py                  # Interactive REPL with slash commands
├── ui.py                    # Rich console rendering
├── tools.py                 # Strands @tool definitions + worker routing
├── supervisor.py            # Parallel data gathering + cross-referencing
├── templates/
│   ├── commands.md          # Core command prompts
│   ├── skills/              # Bundled Agent Skills (8 skills)
│   └── soul.md / envoy.md / process.md
├── agents/
│   ├── base.py              # MCP connections, Bedrock client, AI invocation, run() helper
│   ├── workers/             # Domain-specific Strands worker agents
│   │   ├── __init__.py      # Worker factory + shared infra
│   │   ├── email_worker.py  # Email operations worker
│   │   ├── comms_worker.py  # Slack + EA delegation worker
│   │   ├── calendar_worker.py   # Calendar management worker
│   │   ├── productivity_worker.py  # To-dos, tickets, memory, cron
│   │   ├── research_worker.py     # Phonetool, Kingpin, Wiki, web search
│   │   └── sharepoint_worker.py   # SharePoint/OneDrive worker
│   ├── skills.py            # Agent Skills loader (agentskills.io)
│   ├── workflows.py         # Compound commands (digest, catchup, etc.)
│   ├── heartbeat.py         # Autonomous heartbeat + routines
│   ├── email.py             # Email: send/reply/draft (CC/BCC), read, classify, flag, attachments
│   ├── slack_agent.py       # Slack: scan, send, reactions, drafts, files, Lists
│   ├── calendar.py          # Calendar: view, create, shared calendars
│   ├── todo.py              # To-Do: list, add, complete, update, delete
│   ├── people.py            # Phonetool domain agent
│   ├── sharepoint_agent.py  # SharePoint/OneDrive domain agent
│   ├── tickets.py           # Tickets domain agent
│   ├── memory2.py           # Entity-aware persistent memory
│   ├── observer.py          # Observer/learning agent
│   ├── internal.py          # Internal websites (Kingpin, Wiki, Taskei)
│   ├── export.py            # Word/PowerPoint export
│   └── teamsnap_agent.py    # TeamSnap integration
```

## Additional Docs

- [INSTALL.md](INSTALL.md) — Detailed installation guide
- [QUICKSTART.md](QUICKSTART.md) — Quick start for experienced users
- [CONTRIBUTING.md](CONTRIBUTING.md) — Development guide
- [AGENTCORE.md](AGENTCORE.md) — AgentCore deployment
- [ROADMAP.md](ROADMAP.md) — Feature roadmap
- [TEAM-HEALTH-SPEC.md](TEAM-HEALTH-SPEC.md) — Team health dashboard spec

## Troubleshooting

| Problem | Solution |
|---|---|
| `MCP server not found` | Install required MCP servers and ensure they're in PATH |
| `AWS credentials not configured` | Run `aws login` or set up `.env` |
| `No direct reports found` | Verify alias and Phonetool access |
| `Import errors` | Delete `venv/` and re-run — dependencies reinstall |
| `Midway expired` | Run `mwinit` (auto-refreshed hourly) |
| `Token limit exceeded` | Document too large for model context — content is auto-truncated |
| `Cleanup too aggressive` | Classifier reads full email bodies and is conservative; only true junk flagged DELETE |
| `Worker unavailable` | Worker failed after retry — check MCP connections with `/status` |
