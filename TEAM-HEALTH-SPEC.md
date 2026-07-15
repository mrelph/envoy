# Team Health Dashboard — Spec

Last updated: 2026-07-14

> **Note:** Ticket signals were removed from team-health on 2026-07-14 (ticket
> tracking pulled too many irrelevant tickets and was removed from Envoy
> entirely). The dashboard now rolls up email and Slack signals only.

## What it is

A `/team-health` command (REPL slash + CLI subcommand) that produces a per-person rollup of your direct reports across email, calendar, and Slack — surfacing who needs attention.

## Data sources (all exist today)

| Signal | Source | Existing code |
|---|---|---|
| Direct reports list | Phonetool via `people.get_direct_reports()` | ✅ |
| Email volume per person | Outlook search `from:{alias}@amazon.com` | ✅ `email_search` |
| Sent email (last status update) | Outlook search `folder:sentitems from:{alias}` | ✅ `email_search` with folder |
| Calendar load | Calendar view per person | ⚠️ Only works for self today — shared calendar access needed |
| Slack activity | Slack search `from:@{alias}` | ✅ `search` tool in slack MCP |

## Per-person signals to compute

1. **Email volume** (last 7d) — sent count, received count. Low sent = possibly blocked or disengaged
2. **Last status email** — when did they last send a team/org-wide update? Stale = flag
3. **Meeting load** — % of working hours in meetings (if shared calendar accessible)
4. **Slack recency** — last message timestamp. Silent for 3+ days = flag

## Output format

```
## Team Health — markrelp's directs (7 days)

| Name          | 📧 Sent | 📧 Recv | 📅 Mtg% | ⚠️ Flags          |
|---------------|---------|---------|---------|-------------------|
| Alice (alice) |      42 |     118 |     62% |                   |
| Bob (bobalias)|       8 |      34 | unavail | 💬 slack silent   |
| Carol (carol) |       2 |      15 |     45% | 📧 low send volume|

### 🔴 Needs Attention
- **Bob**: No Slack activity in 5 days and low email volume — check in.
- **Carol**: Only 2 emails sent in 7 days — may be blocked or on PTO.

### 🟢 Looking Good
- **Alice**: Healthy email volume, active on Slack, manageable meeting load.
```

## Implementation plan

### 1. New data-gathering function — `agents/team_health.py`

- Takes manager alias + days
- Calls `people.get_direct_reports()` to get the list
- For each person, runs parallel async fetches:
  - `email_search` with `from:{alias}@amazon.com` (sent count)
  - `email_search` with `to:{alias}@amazon.com` (received count)
  - `email_search` in `sentitems` for last status-like email
  - Slack search `from:@{alias}` for recency
- Returns structured dict per person

### 2. AI synthesis

Feed the raw numbers to `invoke_ai` with a prompt that generates the flags and narrative.

### 3. Wire up

- Add `team_health` to `workflows.py` (or new `agents/team_health.py`)
- Add `/team-health` slash command in `repl.py`
- Add `envoy team-health` CLI subcommand in `cli.py`
- Add to `commands.md` template
- Optionally add `--email` / `--slack` / `--todo` output flags (reuse existing patterns)

## Constraints & risks

- **Shared calendars**: May not have permission to view others' calendars. Degrade gracefully — show "unavail" for meeting load.
- **Rate limiting**: N people × 3 API calls = potentially 15-45 MCP calls. Needs to be fully parallel with `asyncio.gather` and bounded concurrency.
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

- Historical trending ("Bob's email volume is down 3x this week")
- Kingpin goal status per person
- PTO detection (would need calendar or Phonetool OOO)
- Customizable thresholds (hardcode sensible defaults first)
