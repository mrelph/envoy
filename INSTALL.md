# Envoy — Install Guide

## Prerequisites

- **Python 3.7+** — `python3 --version`
- **AWS credentials** — for AI features (Amazon Bedrock / Claude)
- **MCP servers** installed and in PATH:
  - `builder-mcp` — Phonetool access
  - `aws-outlook-mcp` — Outlook email, calendar, to-do
  - `ai-community-slack-mcp` — Slack integration (optional)
  - `amazon-sharepoint-mcp` — SharePoint/OneDrive (optional)
- **Midway auth** — `mwinit` (auto-refreshed on each run)

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
# Interactive REPL
envoy

# Or use subcommands directly
envoy digest --days 7
envoy cleanup
envoy --help
```

Type `/help` in the REPL to see all slash commands.

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
| `Midway expired` | Run `mwinit` (auto-refreshed hourly) |
