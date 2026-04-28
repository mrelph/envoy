# Building Envoy: An AI Chief of Staff from the Command Line

If you manage a team at a large company, your mornings probably look something like this: scan 80 emails to find the 5 that matter, check Slack for anything you missed overnight, review your calendar for back-to-backs you need to prep for, chase down action items from last week, and figure out which customer thread your directs need help with — all before your first meeting at 9am.

Envoy was built to do that job for you. It's an AI chief of staff that runs from your terminal — a single agent that connects to your email, Slack, calendar, to-dos, tickets, and internal tools, cross-references everything, and tells you what actually needs your attention. Ask it to brief you and it pulls from all sources in parallel, prioritizes by urgency, connects related threads across systems, and recommends specific actions. Ask it to catch you up after PTO and it reconstructs the week you missed. It can draft replies, track commitments you've made, audit your calendar for focus time, and run autonomously on a schedule to flag things before they become problems.

It's built on Amazon Bedrock (Claude) and the Model Context Protocol (MCP), and it's designed around a simple premise: the highest-leverage thing an AI can do for a busy manager isn't answer questions — it's triage the firehose and surface what matters.

This post walks through the key architectural decisions behind it.

## The Core Idea: Supervisor + Specialist Workers

Envoy uses a two-tier agent architecture. A **supervisor agent** handles conversation, reasoning, and routing. Six **specialist workers** handle domain-specific operations:

```
User → Supervisor Agent (Claude Opus)
         ├── Email Worker (Claude Sonnet)
         ├── Comms Worker (Slack + EA delegation)
         ├── Calendar Worker
         ├── Productivity Worker (to-dos, tickets, memory)
         ├── Research Worker (Phonetool, Kingpin, Wiki)
         └── SharePoint Worker
```

The supervisor doesn't touch MCP servers directly for most operations. Instead, it delegates natural language requests to the right worker. Each worker has 5–8 focused tools and runs on a cheaper, faster model tier. This keeps the supervisor's context window clean and lets workers be experts in their domain.

The routing is simple — the supervisor has tools like `email_worker(request)` and `comms_worker(request)` that accept a natural language description of what to do. The worker agent interprets it and calls the right MCP tools. If a worker fails, the supervisor retries once with a fresh instance.

## Persistent MCP Connections

MCP servers are subprocess-based — each one is a separate process that communicates over stdio. Starting a subprocess takes ~0.9 seconds, which adds up fast when you're making dozens of calls across a briefing.

Envoy keeps MCP connections alive across calls using a persistent connection pool:

```python
_persistent = {}  # server_name → (stdio_cm, session_cm, session)
```

The first call to any MCP server opens the subprocess and caches the session. Subsequent calls reuse it. If a connection dies (broken pipe, timeout), it's automatically evicted and reopened on the next call. A background event loop keeps the transports alive across synchronous `run()` calls.

This cuts the overhead from ~0.9s per call to near-zero for cached connections. For a morning briefing that makes 30+ MCP calls, that's the difference between 30 seconds of connection overhead and essentially none.

## Parallel Data Gathering with Cross-Referencing

The most important supervisor tool is `gather`. When you ask for a briefing, Envoy doesn't fetch email, then Slack, then calendar sequentially. It fires all of them in parallel:

```python
sources = "email,slack,calendar,todos,tickets"
# Each source runs concurrently via asyncio.gather()
```

After all sources return, Envoy does something that makes it more than a dashboard: **entity extraction and cross-referencing**. It scans all results for people, projects, and ticket IDs, then identifies overlaps. If Alice emailed you about a project and there's a meeting with her tomorrow, the briefing surfaces that connection explicitly.

Every item gets a reference ID (E1, S1, C1, T1) that persists in conversation context. When you say "tell me more about E3," the supervisor pulls the cached data instantly — no re-fetching.

## The Memory System

Envoy maintains three layers of persistent configuration and one layer of runtime memory:

1. **Soul** (`~/.envoy/soul.md`) — Agent identity and personality. Communication style, behavioral rules, the agent's name. This is who the agent *is*.

2. **Envoy** (`~/.envoy/envoy.md`) — User facts and preferences. Your alias, team, key people, favorite Slack channels, EA info. This is what the agent knows *about you*.

3. **Process** (`~/.envoy/process.md`) — Learned operational patterns. Email rules, meeting preferences, cleanup patterns. This is how the agent has learned *to work for you*.

4. **Runtime memory** (`~/.envoy/memory/`) — Entity-aware observations stored as JSONL. Actions taken, decisions made, deferred items. Older entries get compressed into per-entity summaries (not a single blob), so recalling "what happened with Project X" stays fast even after months of use.

The agent can update all three config files, but always asks for confirmation first. Over time, Envoy learns your patterns — who matters, how you like reports formatted, which emails are junk.

## Agent Skills: Progressive Disclosure

Envoy ships with 8 bundled skills (1:1 prep, calendar audit, commitment tracking, etc.) and supports custom skills via the [Agent Skills](https://agentskills.io) open standard.

The key design choice is **progressive disclosure**. At startup, only skill names and one-line descriptions are loaded into the system prompt — about 100 tokens per skill. When a task matches a skill, the supervisor calls `activate_skill` to load the full instructions on demand. This keeps the base system prompt lean while supporting an unlimited skill library.

Skills are just markdown files in a folder. Drop a `SKILL.md` into `~/.envoy/skills/` and it's available immediately.

## The TUI

The default interface is a full-screen Textual TUI with animated spinners, MCP health indicators, and toast notifications. It falls back to a plain REPL if Textual isn't available.

The TUI and CLI share a common dispatch layer (`dispatch.py`) that maps slash commands and natural language to agent calls. The same commands work in both interfaces — `/briefing` in the TUI does the same thing as `envoy briefing` from the CLI.

This matters for automation. You can run `envoy digest --days 7 --slack --no-display` from cron and get a weekly digest delivered to your Slack DMs, using the exact same code path as the interactive TUI.

## Model Tiering

Not every task needs the most expensive model. Envoy uses five tiers:

| Tier | Default Model | Used For |
|------|--------------|----------|
| Agent | Claude Opus | Conversational supervisor |
| Heavy | Claude Opus | Summaries, document analysis |
| Medium | Claude Sonnet | Workers, classification |
| Light | Claude 3.5 Haiku | Simple extraction |
| Memory | Nova Micro | Memory compression |

Tiers are configurable via `/models` in the TUI. The email classifier runs on Haiku (fast, cheap, good enough). The briefing synthesizer runs on Opus (needs reasoning across sources). Workers default to Sonnet (good balance). This keeps costs reasonable while maintaining quality where it matters.

## Heartbeat and Autonomous Operation

Envoy can run autonomously via `envoy heartbeat`, checking user-defined routines and alerting when something needs attention. Routines are natural language rules like "Alert me if any sev-2 tickets go stale" or "Flag emails from the VP that I haven't replied to within 4 hours."

Combined with the built-in cron manager, this turns Envoy from an interactive tool into a background operator that watches your work streams and surfaces what matters.

## What I Learned Building It

**MCP is the right abstraction.** Wrapping Outlook, Slack, and Phonetool behind MCP servers means the agent code never deals with OAuth tokens, API pagination, or rate limits. It just calls tools. When a new MCP server appears (SharePoint, Kingpin), adding it is a config change, not a rewrite.

**Workers need session hygiene.** Strands agents persist conversation history for continuity, but corrupted sessions (mismatched tool calls) can permanently break a worker. Auto-clearing stale sessions on validation errors was essential for reliability.

**Progressive disclosure scales.** Loading full skill instructions into every system prompt would blow the context window. Loading just names and activating on demand keeps the base prompt under 4K tokens while supporting dozens of skills.

**Cross-referencing is the killer feature.** Any tool can show you your inbox. The value of an AI assistant is connecting your inbox to your calendar to your Slack to your tickets and telling you what actually matters right now.
