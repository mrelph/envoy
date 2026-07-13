# Envoy — Install Guide

## Prerequisites

- **Python 3.10+** — `python3 --version`
- **AWS credentials** — for AI features (Amazon Bedrock / Claude)
- **MCP servers** installed and in PATH:
  - `builder-mcp` — Phonetool, Wiki, Taskei, Broadcast
  - `aws-outlook-mcp` — Outlook email, calendar, to-do
  - `slack-mcp` — Slack integration (optional; `ai-community-slack-mcp` works as fallback)
  - `amazon-sharepoint-mcp` — SharePoint/OneDrive (optional)
  - `kingpin-mcp` — Kingpin goals/projects/milestones (optional)
  - `instructai-mcp` — InstructAI business queries (optional)
  - `amazon-quick-mcp` — QuickSight Q (optional)
  - Add custom servers via `/mcp add` or `~/.envoy/mcp.json`

## Install

```bash
# 1. Extract the tarball
tar xzf envoy.tar.gz
cd envoy

# 2. Run the installer (creates venv, installs deps, links to PATH)
./install.sh

# 3. Configure your identity and agent personality
envoy init
```

That's it. `envoy init` walks you through:
1. Your alias (auto-detected from `$USER`)
2. Phonetool lookup (role, manager, directs)
3. Email preferences and signature
4. EA delegation setup
5. AI-generated agent personality (optional)

Config is saved to `~/.envoy/`.

## One-liner install (optional)

`curl -fsSL https://raw.githubusercontent.com/mrelph/envoy/main/get-envoy.sh | bash` clones the repo to `~/.envoy` (or `$ENVOY_DIR`), sets up the venv, and links `envoy` onto your `PATH` — but piping `curl` straight into `bash` runs the script with your privileges before you've reviewed it. If you'd rather inspect it first:

```bash
curl -fsSL https://raw.githubusercontent.com/mrelph/envoy/main/get-envoy.sh -o get-envoy.sh
less get-envoy.sh        # read it
bash get-envoy.sh        # run it once you're satisfied
```

Or skip the script entirely and follow the tarball/git-clone steps above.

## AWS Credentials

Required for all AI features. Uses Amazon Bedrock (Claude) in `us-west-2`.

**Option A: AWS CLI (recommended)**
```bash
aws login
```

**Option B: `.env` file**
```bash
# Create at ~/.envoy/.env (outside the project, won't be overwritten)
cat > ~/.envoy/.env << 'EOF'
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_REGION=us-west-2
EOF
```

A project-local `.env` also works (copy `.env.example`), but `~/.envoy/.env` is preferred — it survives reinstalls.

## Run It

```bash
# Interactive TUI (default)
envoy

# Or use subcommands directly
envoy digest --days 7
envoy cleanup
envoy --help
```

Type `/help` in the TUI to see all slash commands.

## What's Available

Once installed, Envoy provides full access to:

- **Email** — read full threads, send (with CC/BCC), reply, forward, draft, flag/categorize, attachments, contacts, cleanup
- **Slack** — scan with user name resolution and thread context, send to DMs/channels/threads, reactions, drafts, file downloads, Slack Lists
- **Calendar** — view, create (recurring, optional attendees, room resources, reminders), shared calendars, find times, book rooms
- **To-Do** — list, add (with due dates/importance/reminders), complete, update, delete, subtasks
- **SharePoint** — search, browse, read, write, lists
- **Research** — Phonetool, Kingpin, Wiki, Taskei, Broadcast, web search, InstructAI (revenue/pipeline/partners), QuickSight Q (dashboards/topics)
- **Skills** — bundled Agent Skills + on-demand skill creation via `/build-skill` and `/suggest-skills`

## Updating

Get the latest `envoy.tar.gz`, then:

```bash
tar xzf envoy.tar.gz
cd envoy
./install.sh
```

Your config in `~/.envoy/` (credentials, personality, memory) is preserved across updates.

## Troubleshooting

| Problem | Solution |
|---|---|
| `MCP server not found` | Install required MCP servers and ensure they're in PATH |
| `AWS credentials not configured` | Run `aws login` or create `~/.envoy/.env` |
| `No direct reports found` | Verify alias and Phonetool access |
| `Import errors` | Delete `venv/` and re-run `./install.sh` |
