# Envoy — Quick Install Guide

## Prerequisites

- **Python 3.7+** — `python3 --version`
- **AWS credentials** — for AI features (Amazon Bedrock / Claude)
- **MCP servers** installed and in PATH:
  - `builder-mcp` — Phonetool access
  - `aws-outlook-mcp` — Outlook email, calendar, to-do
  - `ai-community-slack-mcp` — Slack integration (optional)
  - `amazon-sharepoint-mcp` — SharePoint/OneDrive (optional)
- **Midway auth** — `mwinit` (auto-refreshed on each run)

## Option 1: One-Line Install (git)

```bash
curl -fsSL https://raw.githubusercontent.com/mrelph/envoy/main/get-envoy.sh | bash
```

This clones to `~/.envoy/`, installs dependencies, and links `envoy` to your PATH.

## Option 2: Tarball Install

```bash
# Download and extract
tar xzf envoy-v3.0.0.tar.gz
cd envoy

# Install — sets up venv, skills, and adds to PATH
./install.sh
```

## Option 3: Git Clone

```bash
git clone https://github.com/mrelph/envoy.git
cd envoy
./install.sh
```

## First-Time Setup

```bash
# Configure your identity, preferences, and agent personality
envoy init
```

This walks you through:
1. Your alias (auto-detected from `$USER`)
2. Phonetool lookup (role, manager, directs)
3. Email preferences and signature
4. EA delegation setup
5. AI-generated agent personality (optional)

Config is saved to `~/.envoy/`.

## AWS Credentials

Required for all AI features. The tool uses Amazon Bedrock (Claude) in `us-west-2`.

**Option A: `.env` file (recommended)**
```bash
cp .env.example .env
# Edit with your credentials:
#   AWS_ACCESS_KEY_ID=your_key
#   AWS_SECRET_ACCESS_KEY=your_secret
#   AWS_REGION=us-west-2
```

**Option B: AWS CLI**
```bash
aws login
```

## Run It

```bash
# Interactive REPL
envoy

# Or use subcommands directly
envoy digest --days 7
envoy cleanup
envoy --help
```

## What's Included

### Core Commands (built-in)
| Command | Description |
|---|---|
| `envoy digest` | Team email digest |
| `envoy cleanup` | Inbox junk cleanup |
| `envoy customers` | Customer email scan |
| `envoy catchup` | PTO catch-up report |
| `envoy yesterbox` | Yesterday's DMs, prioritized |

### Agent Skills (extensible)
8 bundled skills installed to `~/.envoy/skills/`:

| Skill | Description |
|---|---|
| `prep-1on1` | 1:1 meeting prep brief |
| `prep-meeting` | Any meeting prep brief |
| `commitment-tracker` | Track promises you made |
| `response-times` | Email response patterns |
| `followup-nagger` | Unanswered sent emails |
| `calendar-audit` | Meeting load & focus time |
| `slack-catchup` | Slack catch-up |
| `teamsnap` | Kids' sports schedules |

Add your own skills by dropping a folder with a `SKILL.md` into `~/.envoy/skills/`.
See [agentskills.io](https://agentskills.io) for the format spec.

## Interactive Commands

In the REPL, type `/help` to see all slash commands:

```
/briefing          Full briefing (calendar+email+slack)
/digest 7          Team digest (last 7 days)
/cleanup           Inbox cleanup
/customers         Customer scan
/followup 7        Unanswered sent emails
/commitments       Promises tracker
/prep-1on1 alias   1:1 prep brief
/sharepoint        SharePoint/OneDrive search
/help              All commands
```

Most commands accept a number of days as an argument (e.g., `/digest 7`, `/catchup 3`).

## Updating

```bash
envoy update
```

Or re-run the one-liner to pull the latest.

## Troubleshooting

| Problem | Solution |
|---|---|
| `MCP server not found` | Install `builder-mcp` and `aws-outlook-mcp` and ensure they're in PATH |
| `AWS credentials not configured` | Set up `.env` or run `aws login` |
| `No direct reports found` | Verify alias is correct and you have Phonetool access |
| `Import errors` | Delete `venv/` and re-run — dependencies will reinstall |
| `Midway expired` | Run `mwinit` — Envoy auto-refreshes hourly but manual refresh may be needed |
