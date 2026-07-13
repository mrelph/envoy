# Envoy Roadmap

## ✅ Done

- **Worker retry + graceful degradation** — `_delegate` in `tools.py` retries on failure with fallback handling
- **Context carryover between turns** — `supervisor.py` retains source data; supervisor tools (`read_email_thread`, `show_context`) drill into cached results
- **Attachment handling** — `get_attachment` supervisor tool downloads, previews, and summarizes email attachments
- **Cross-reference intelligence** — `gather` extracts entities (people, projects, tickets) and surfaces overlaps across sources in synthesis
- **Active learning loop** — `agents/learning.py` reflects after each interaction, detects corrections, and runs weekly self-analysis
- **Skill builder** — `/build-skill` and `/suggest-skills` generate new Agent Skills on demand
- **MCP management** — `/mcp` command + `~/.envoy/mcp.json` user overrides
- **InstructAI + QuickSight** — wired into research worker for revenue/pipeline/dashboard queries
- **Bedrock credential auto-refresh** — `invoke_ai` retries once on `ExpiredTokenException`
- **Live `/models` editor** — interactive model picker against the live Bedrock catalog with `reload_agent()`
- **Team health dashboard** — persistent "team health" view: who's overloaded, who has stale tickets, who hasn't sent a status update. See `TEAM-HEALTH-SPEC.md`.
- **Smart scheduling** — "Schedule a 1:1 with jsmith next week, 30 min, find a room at SEA54" as a single natural language command: check availability → propose times → book room → send invite
- **Multi-turn drill-down** — numbered reference IDs across turns + `drill_down` supervisor tool ("Show me my inbox" → "Reply to the third one" → "CC Bob on that")
- **Proactive notifications** *(partially done)* — activity feed surfaces ambient insights in the TUI and `envoy watch` exists; a webhook/push path (e.g. Slack bot listener on @mention or DM) is still open

## 🔴 High Impact, Reasonable Effort

### 1. Proactive notifications (remaining work)
Heartbeat exists but is cron-based. No webhook/push path. A Slack bot listener that triggers Envoy on @mention or DM would make it feel alive rather than batch-only. (The activity feed and `envoy watch` cover the ambient/polling half.)

## 🟡 Medium Impact

### 2. Delegation tracking
`/ea` delegates to your EA but there's no follow-up loop. A delegation ledger with auto-follow-up would close the loop.

## 🟢 Nice to Have

### 3. Conversation export
Save a REPL session as a doc. "Export this conversation as a Quip doc" or "Save this briefing to SharePoint."

### 4. Notification preferences
Let users configure urgency thresholds. "Only Slack me for 🔴 items, email me the rest."

### 5. Undo / audit trail
"What did Envoy do on my behalf today?" — a log of all actions taken (emails sent, meetings booked, to-dos created) with the ability to reverse them.

### 6. Obsidian integration
Two-way sync between Envoy's memory system and an Obsidian vault. Memory entries become daily notes with `[[wikilinks]]` for entities, enabling Obsidian's graph view to visualize people/project connections. Start with an `/obsidian` export command (~50 lines), then upgrade to live file-based sync. Obsidian → Envoy import via a watched inbox folder where dropped `.md` files get parsed and added to memory. See `OBSIDIAN-PLAN.md`.

## Recommended Build Order

1. **Proactive notifications** — Finish the conversion from batch to event-driven (webhook/push path)
2. **Delegation tracking** — Close the loop on `/ea` delegations
