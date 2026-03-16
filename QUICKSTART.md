# Attaché — Quick Start

## Install

```bash
cd attache

# Option A: Run locally
./attache

# Option B: Install globally
sudo ln -s $(pwd)/attache /usr/local/bin/attache
attache
```

Dependencies auto-install on first run. You need `builder-mcp` and `aws-outlook-mcp` in your PATH, plus AWS credentials for AI features (`aws login` or `.env` file).

## Interactive Mode (default)

```bash
attache
```

Pick from the menu:

1. 📊 Team Digest — summarize your directs' email
2. 🌟 Boss Tracker — track your management chain
3. 🧹 Inbox Cleanup — find and delete junk email
4. 📬 Customer Scan — external emails with action items

## CLI Mode (for scripting)

```bash
# Team digest
attache digest --days 7 --email

# Boss tracker
attache digest --vip --days 7

# Inbox cleanup
attache cleanup --days 7 --limit 200

# Customer scan
attache customers --days 7 --email

# Skip AI (faster, no AWS creds needed)
attache digest --no-ai
```

## Common Recipes

```bash
# Weekly digest emailed to you
attache digest --days 7 --email --no-display

# Save customer report to file
attache customers --days 14 --output report.md

# Specific team members only
attache digest --select "alice,bob" --days 7

# Action items to Microsoft To-Do
attache digest --days 7 --todo
```

## Automation

```bash
# Weekly Monday digest (cron)
0 8 * * 1 /usr/local/bin/attache digest --days 7 --email --no-display

# Daily customer scan (cron)
0 9 * * * /usr/local/bin/attache customers --days 1 --email

# Shell alias
echo 'alias mp="attache"' >> ~/.bashrc && source ~/.bashrc
mp digest --days 7
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `MCP server not found` | Install `builder-mcp` and `aws-outlook-mcp`, ensure in PATH |
| `AWS credentials` | Run `aws login` or set up `.env`. Use `--no-ai` to skip AI. |
| `No direct reports` | Check alias is correct and you have Phonetool access |
| `Import errors` | Delete `venv/` and re-run — dependencies reinstall automatically |
