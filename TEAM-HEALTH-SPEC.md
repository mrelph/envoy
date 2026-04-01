# Team Health Dashboard — Spec

Last updated: 2026-04-01

## What it is

A `/team-health` command (REPL slash + CLI subcommand) that produces a per-person rollup of your direct reports across email, calendar, tickets, and Slack — surfacing who needs attention.

## Data sources (all exist today)

| Signal | Source | Existing code |
|---|---|---|
| Direct reports list | Phonetool via `people.get_direct_reports()` | ✅ |
| Email volume per person | Outlook search `from:{alias}@amazon.com` | ✅ `email_search` |
| Sent email (last status update) | Outlook search `folder:sentitems from:{alias}` | ✅ `email_search` with folder |
| Open tickets per person | Ticketing `search-tickets` with assignee filter | ✅ `scan_tickets` (needs per-person filter) |
| Calendar load | Calendar view per person | ⚠️ Only works for self today — shared calendar access needed |
| Slack activity | Slack search `from:@{alias}` | ✅ `search` tool in slack MCP |

## Per-person signals to compute

1. **Email volume** (last 7d) — sent count, received count. Low sent = possibly blocked or disengaged
2. **Last status email** — when did they last send a team/org-wide update? Stale = flag
3. **Open ticket count** — total open, any sev-2+, any stale (no update 7+ days)
4. **Meeting load** — % of working hours in meetings (if shared calendar accessible)
5. **Slack recency** — last message timestamp. Silent for 3+ days = flag

## Output format

```
## Team Health — markrelp's directs (7 days)

| Name          | 📧 Sent | 📧 Recv | 🎫 Open | 🔴 Sev2+ | 📅 Mtg% | ⚠️ Flags          |
|---------------|---------|---------|---------|----------|---------|-------------------|
| Alice (alice) |      42 |     118 |       3 |        0 |     62% |                   |
| Bob (bobalias)|       8 |      34 |       7 |        1 | unavail | 🎫 stale ticket   |
| Carol (carol) |       2 |      15 |       1 |        0 |     45% | 📧 low send volume|

### 🔴 Needs Attention
- **Bob**: Sev-2 ticket SIM-12345 has no update in 9 days. 7 open tickets total.
- **Carol**: Only 2 emails sent in 7 days — may be blocked or on PTO.

### 🟢 Looking Good
- **Alice**: Healthy email volume, no stale tickets, manageable meeting load.
```

## Implementation plan

### 1. New data-gathering function — `agents/team_health.py`

- Takes manager alias + days
- Calls `people.get_direct_reports()` to get the list
- For each person, runs parallel async fetches:
  - `email_search` with `from:{alias}@amazon.com` (sent count)
  - `email_search` with `to:{alias}@amazon.com` (received count)
  - `email_search` in `sentitems` for last status-like email
  - `TicketingReadActions` search-tickets filtered by assignee
  - Slack search `from:@{alias}` for recency
- Returns structured dict per person

### 2. AI synthesis

Feed the raw numbers + ticket details to `invoke_ai` with a prompt that generates the flags and narrative.

### 3. Wire up

- Add `team_health` to `workflows.py` (or new `agents/team_health.py`)
- Add `/team-health` slash command in `repl.py`
- Add `envoy team-health` CLI subcommand in `cli.py`
- Add to `commands.md` template
- Optionally add `--email` / `--slack` / `--todo` output flags (reuse existing patterns)

## Constraints & risks

- **Ticket search by assignee**: Current `scan_tickets` doesn't filter by person. Need to add an `assignedTo` or `fullText` filter to the TicketingReadActions call. The MCP supports it.
- **Shared calendars**: May not have permission to view others' calendars. Degrade gracefully — show "unavail" for meeting load.
- **Rate limiting**: N people × 5 API calls = potentially 25-50 MCP calls. Needs to be fully parallel with `asyncio.gather` and bounded concurrency.
- **Team size**: Works well for 5-10 directs. For 20+ need pagination or sampling.

## Estimated effort

| Component | Effort |
|---|---|
| `agents/team_health.py` — data gathering | ~150 lines |
| AI synthesis prompt | ~30 lines |
| `workflows.py` integration | ~20 lines |
| `repl.py` slash command | ~5 lines |
| `cli.py` subcommand | ~15 lines |
| `commands.md` template | ~10 lines |
| **Total** | **~230 lines** |

## Not in v1

- Historical trending ("Bob's ticket count is up 3x this week")
- Kingpin goal status per person
- PTO detection (would need calendar or Phonetool OOO)
- Customizable thresholds (hardcode sensible defaults first)
