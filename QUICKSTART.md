# Envoy — Quick Start

For experienced users who want to get running fast. See [INSTALL.md](INSTALL.md) for the full guide.

## Install & Run

```bash
git clone https://github.com/mrelph/envoy.git
cd envoy
./install.sh
envoy init       # configure identity + agent personality
envoy            # launch REPL
```

Or one-liner: `curl -fsSL https://raw.githubusercontent.com/mrelph/envoy/main/get-envoy.sh | bash`

Prerequisites: Python 3.7+, `builder-mcp`, `aws-outlook-mcp` in PATH, AWS credentials (`aws login` or `.env`).

## REPL Commands

```
/briefing          Full briefing (calendar + email + Slack)
/digest 7          Team email digest (last 7 days)
/boss              Boss tracker
/cleanup           Inbox cleanup (with confirmation)
/customers 14      Customer email scan
/catchup 5         PTO catch-up
/yesterbox          Yesterday's DMs
/followup 7        Unanswered sent emails
/commitments 7     Promises tracker
/prep-1on1 alias   1:1 prep brief
/prep-meeting      Meeting prep brief
/cal-audit 5       Calendar audit
/sharepoint        SharePoint/OneDrive search
/eod               End-of-day summary
/weekly            Weekly review
/help              All commands
```

Most commands accept a number of days as an argument.

## CLI Scripting

```bash
envoy digest --days 7 --email --todo
envoy digest --vip --days 7 --slack
envoy cleanup --days 7 --limit 200
envoy customers --days 7 --team "alice,bob" --email
envoy catchup --days 5
envoy followup --days 7
envoy prep-1on1 jsmith
envoy --help
```

## Automation

```bash
envoy cron presets                    # see templates
envoy cron add --name weekly-digest \
  --schedule "0 8 * * 1" \
  --command "digest --days 7 --slack --no-display"
```

## Extending with Skills

Drop a folder with a `SKILL.md` into `~/.envoy/skills/` — Envoy picks it up automatically. See [agentskills.io](https://agentskills.io) for the format spec.

## Troubleshooting

| Problem | Fix |
|---|---|
| `MCP server not found` | Install MCP servers, ensure in PATH |
| `AWS credentials` | `aws login` or set up `.env` |
| `Import errors` | Delete `venv/`, re-run |
| `Midway expired` | `mwinit` |
