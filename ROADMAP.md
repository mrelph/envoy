# Envoy Roadmap

Last updated: 2026-04-01

## 🔴 High Impact, Reasonable Effort

### 1. Worker retry + graceful degradation
When a worker fails (bad tool call, MCP timeout, throttle), the whole request degrades. `_delegate` in tools.py has no retry, no fallback, no partial-result handling. A single failed worker poisons the response.

### 2. Context carryover between turns
The `_context` dict in supervisor.py is shallow. "What did Curtis say in that email?" after a briefing doesn't work because raw email bodies aren't retained, just summaries. The agent loses source data after synthesis.

### 3. Attachment handling
Email attachments are referenced but there's no download/preview/summarize flow. "What's in the PDF Alice sent me?" is a natural ask with no answer today.

### 4. Proactive notifications
Patrol exists but is cron-based. No webhook/push path. A Slack bot listener that triggers Envoy on @mention or DM would make it feel alive rather than batch-only.

## 🟡 Medium Impact

### 5. Multi-turn drill-down
"Show me my inbox" → "Reply to the third one" → "CC Bob on that" — this chain requires tracking numbered references across turns. `last_emails` context helps but there's no structured reference system.

### 6. Delegation tracking
`/ea` delegates to your EA but there's no follow-up loop. A delegation ledger with auto-follow-up would close the loop.

### 7. Team health dashboard
No persistent "team health" view — who's overloaded, who has stale tickets, who hasn't sent a status update. This is the chief-of-staff killer feature.

### 8. Smart scheduling
"Schedule a 1:1 with jsmith next week, 30 min, find a room at SEA54" as a single natural language command that handles the full flow: check availability → propose times → book room → send invite.

## 🟢 Nice to Have

### 9. Conversation export
Save a REPL session as a doc. "Export this conversation as a Quip doc" or "Save this briefing to SharePoint."

### 10. Notification preferences
Let users configure urgency thresholds. "Only Slack me for 🔴 items, email me the rest."

### 11. Cross-reference intelligence
"This email from Alice mentions the same project as Bob's Slack message" — connecting dots across sources. The memory entity system has the bones but it's not surfaced in synthesis prompts.

### 12. Undo / audit trail
"What did Envoy do on my behalf today?" — a log of all actions taken (emails sent, meetings booked, to-dos created) with the ability to reverse them.

## Recommended Build Order

1. **Worker retry + graceful degradation** — Immediate quality-of-life fix
2. **Team health dashboard** — The "chief of staff" positioning demands this
3. **Full scheduling flow** — High wow factor, daily utility
