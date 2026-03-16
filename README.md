# Attaché

Your AI chief of staff from the command line. Summarize your team's email, clean up inbox junk, track your boss's activity, and surface customer action items — all driven by Claude via Amazon Bedrock.

## How It Works

```
Phonetool (builder-mcp)     Outlook (aws-outlook-mcp)     Amazon Bedrock (Claude)
        │                            │                              │
        ▼                            ▼                              ▼
  Fetch people ──────► Fetch/read their emails ──────► AI analysis & action items
                                                                    │
                                                     ┌──────────────┼──────────────┐
                                                     ▼              ▼              ▼
                                                  Console        Email         To-Do
```

## Quick Start

```bash
# Clone or copy the attache folder
cd attache

# Run it — dependencies auto-install on first run
./attache
```

That's it. The interactive menu appears:

```
╭─ ✈  Attaché ──────────────────────────────────╮
│  Your AI Chief of Staff                    │
╰─────────────────────────────────────────────────╯

  1. 📊  Team Digest      — Summarize your directs' email activity
  2. 🌟  Boss Tracker     — Track your management chain's emails
  3. 🧹  Inbox Cleanup    — Find and delete non-critical email
  4. 📬  Customer Scan    — External emails with action items
  5. 🚪  Exit
```

## Installation

### Prerequisites

- Python 3.7+
- MCP servers installed and in PATH:
  - `builder-mcp` — Phonetool access
  - `aws-outlook-mcp` — Outlook email access
- AWS credentials for AI features — see [AWS Credentials Setup](#aws-credentials-setup)

### Install

```bash
git clone <repo-url> attache
cd attache

# Option A: Run from the project directory
./attache

# Option B: Install globally (run from anywhere)
sudo ln -s $(pwd)/attache /usr/local/bin/attache
attache
```

Dependencies (mcp, click, boto3, rich, python-dotenv) auto-install into a local `venv/` on first run.

## Features

### 📊 Team Digest

Summarize your direct reports' recent email activity with AI-powered analysis.

- Fetches direct reports from Phonetool
- Searches Outlook for each person's sent emails
- AI generates prioritized summary with action items
- Optionally email the digest to yourself or add action items to Microsoft To-Do

```bash
# Interactive
attache            # then choose option 1

# CLI
attache digest --alias yourlogin --days 7
attache digest --days 7 --email --todo
attache digest --days 7 --slack          # send as Slack DM to yourself
attache digest --select "alice,bob" --output digest.md
attache digest --no-ai    # skip AI, raw listing only
```

### 🌟 Boss Tracker

Track your management chain's email activity — see what your bosses are focused on.

- Fetches N levels of your management chain from Phonetool
- Summarizes their recent email activity
- AI highlights what leadership is focused on

```bash
# Interactive
attache            # then choose option 2

# CLI
attache digest --vip --days 7
```

### 🧹 Inbox Cleanup

AI scans your inbox and identifies non-critical email for easy bulk deletion.

- Reads your inbox emails and analyzes content
- Classifies each as DELETE (true junk), REVIEW (probably safe to delete), or KEEP
- Interactive selection — you choose what to delete
- Emails move to Deleted Items (recoverable)

Classification targets:
- External marketing/vendor newsletters
- Automated spam and mass surveys
- Routine automated notifications

```bash
# Interactive
attache            # then choose option 3

# CLI
attache cleanup --days 7 --limit 200
```

### 📬 Customer Scan

Surface external customer emails with action items across you and your team.

- Scans for non-Amazon emails sent to you and your direct reports
- AI categorizes by urgency: Action Required, Follow-Up, FYI
- Highlights overdue or time-sensitive items

```bash
# Interactive
attache            # then choose option 4

# CLI
attache customers --days 7
attache customers --team "alice,bob" --email --output report.md
attache customers --days 7 --slack       # send as Slack DM to yourself
```

### ✅ To-Do Review (Agent Tool)

AI-powered burndown plan for your Microsoft To-Do list. Available as an agent tool (`todo_review`).

- Pulls your full To-Do list
- Cross-references items with recent email (7 days), Slack messages (3 days), and upcoming calendar (5 days)
- AI generates a prioritized burndown plan with categories:
  - **Do Now** — urgent items with active signals
  - **Schedule This Week** — important but not immediate
  - **Quick Wins** — low-effort items you can knock out fast
  - **Consider Closing** — stale items with no recent activity
  - **Summary** — overall status and recommendations

## CLI Reference

Running `attache` with no arguments opens the interactive menu. Subcommands are available for scripting and automation.

### `attache digest`

| Option | Short | Default | Description |
|---|---|---|---|
| `--alias` | `-a` | `$USER` | Manager alias |
| `--days` | `-d` | `14` | Days to look back |
| `--select` | `-s` | all | Comma-separated aliases to include |
| `--vip` | | off | Track bosses instead of directs |
| `--output` | `-o` | — | Save output to file |
| `--email` | `-e` | off | Email digest to yourself |
| `--slack` | | off | Send digest as Slack DM to yourself |
| `--todo` | `-t` | off | Add action items to Microsoft To-Do |
| `--no-ai` | | off | Skip AI summary, show raw digest |
| `--no-display` | | off | Suppress console output |

### `attache cleanup`

| Option | Short | Default | Description |
|---|---|---|---|
| `--days` | `-d` | `14` | Days to look back |
| `--limit` | `-l` | `100` | Max emails to scan |

### `attache customers`

| Option | Short | Default | Description |
|---|---|---|---|
| `--alias` | `-a` | `$USER` | Your alias |
| `--days` | `-d` | `14` | Days to look back |
| `--team` | `-t` | auto (directs) | Comma-separated team aliases |
| `--output` | `-o` | — | Save output to file |
| `--email` | `-e` | off | Email report to yourself |
| `--slack` | | off | Send report as Slack DM to yourself |

## AWS Credentials Setup

Required for all AI features. The tool uses Amazon Bedrock (Claude) in `us-west-2`.

**Option 1: `.env` file (recommended)**

```bash
cp .env.example .env
# Edit .env with your credentials:
```

```
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-west-2
```

**Option 2: AWS CLI**

```bash
aws login
```

The tool tries `.env` first, then falls back to the default AWS credential chain.

## Automation

### Cron: Weekly Monday Digest (Slack)

```bash
crontab -e
# Add:
0 8 * * 1 /usr/local/bin/attache digest --days 7 --slack --no-display
```

### Cron: Daily Customer Scan (Slack)

```bash
0 9 * * * /usr/local/bin/attache customers --days 1 --slack --output /tmp/customers-$(date +\%F).md
```

> **Tip:** The built-in cron presets (`morning-briefing`, `weekly-digest`, `customer-scan`) default to `--slack`. Swap `--slack` for `--email` if you prefer email delivery.

### Shell Alias

```bash
echo 'alias mp="attache"' >> ~/.bashrc
source ~/.bashrc
mp digest --days 7 --slack
```

## Project Structure

```
attache/
├── attache              # Entrypoint script (auto-installs venv)
├── cli.py                 # CLI commands and interactive TUI (Click + Rich)
├── service.py             # Core logic: MCP calls, AI, email, cleanup
├── agent_handler.py       # AgentCore handler for deployed agent mode
├── agent_config.json      # AgentCore agent configuration
├── requirements.txt       # Python dependencies
├── .env.example           # Template for AWS credentials
├── README.md              # This file
├── QUICKSTART.md          # Quick start guide
├── AGENTCORE.md           # AgentCore deployment guide
└── CONTRIBUTING.md        # Contribution guidelines
```

## Architecture

### `service.py` — `AttachéService`

| Method | Description |
|---|---|
| `get_direct_reports(alias)` | Fetches directs from Phonetool via `builder-mcp` |
| `get_management_chain(alias, levels)` | Fetches N levels of managers |
| `get_recent_emails(alias, days)` | Searches Outlook via `aws-outlook-mcp` |
| `generate_digest(alias, days, selected, vip)` | Orchestrates data collection into markdown |
| `generate_ai_summary(digest, alias, days)` | Sends digest to Bedrock Claude for analysis |
| `extract_action_items(summary)` | Parses action items from AI output |
| `email_digest(digest, alias, days)` | Sends formatted HTML email via Outlook MCP |
| `add_to_todo(items, list_name)` | Creates tasks in Microsoft To-Do |
| `fetch_inbox_emails(days, limit)` | Fetches inbox emails with full body content |
| `classify_emails(emails, alias)` | AI classification for inbox cleanup |
| `delete_emails(conversation_ids)` | Bulk move emails to Deleted Items |
| `scan_customer_emails(alias, days, team)` | Scans for external customer emails with action items |
| `todo_review(alias)` | Cross-references To-Do items with email, Slack, and calendar to generate an AI burndown plan |

### MCP Servers

| Server | Tools Used | Purpose |
|---|---|---|
| `builder-mcp` | `ReadInternalWebsites` | Phonetool lookups |
| `aws-outlook-mcp` | `email_search`, `email_read`, `email_send`, `email_move` | Email operations |
| `aws-outlook-mcp` | `todo_lists`, `todo_tasks`, `calendar_view` | To-Do and calendar access |
| Slack MCP | `post_message`, `list_channels`, `batch_get_conversation_history` | Slack DM delivery and message context |

### AI Model

Uses `us.anthropic.claude-opus-4-6-v1` via Amazon Bedrock.

## AgentCore Deployment

This tool can also run as an agent on AgentCore. See [AGENTCORE.md](AGENTCORE.md) for deployment instructions.

## Troubleshooting

| Problem | Solution |
|---|---|
| `MCP server not found` | Ensure `builder-mcp` and `aws-outlook-mcp` are installed and in your PATH |
| `AWS credentials not configured` | Set up `.env` or run `aws login`. Use `--no-ai` to skip AI for digest. |
| `No direct reports found` | Verify alias is correct and you have Phonetool access |
| `Email send failed` | Check `aws-outlook-mcp` is running and you have email permissions |
| `Import errors` | Delete `venv/` and re-run — dependencies will reinstall |
| `To-Do integration fails` | Ensure the To-Do MCP server is configured and accessible |
| `Cleanup too aggressive` | The classifier is tuned to be conservative; only true junk is flagged DELETE |
