# Building Envoy: How We Built an AI Chief of Staff from the Command Line

A guide to building an AI-powered personal assistant that manages email, Slack, calendar, and more — using Envoy as a worked example.

---

## The Idea

Envoy started with a simple observation: knowledge workers spend hours every day context-switching between email, Slack, calendar, to-do lists, and internal tools. What if an AI agent could sit across all of those systems, synthesize what matters, and surface it in one place?

The goal was not another chatbot. It was a trusted operator — something closer to an experienced executive assistant who knows your priorities, your people, and how you like things done. It would run from the command line, because that's where builders already live.

The core design principles:

- **Interactive by default, scriptable always.** Running `envoy` drops you into a rich REPL. Running `envoy digest --days 7` executes and exits. Same logic, two interfaces.
- **Parallel data gathering.** A morning briefing shouldn't take 5 minutes of sequential API calls. Fetch email, Slack, calendar, and tickets simultaneously, then cross-reference.
- **Supervisor + workers.** One agent orchestrates, specialized workers handle domains. The email worker doesn't need Slack tools cluttering its context.
- **Progressive disclosure.** Skills load their full instructions only when activated. The system prompt stays lean.
- **Memory across sessions.** The agent remembers what it did yesterday, who it talked to, and what's pending.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                   User (CLI/REPL)                │
├─────────────────────────────────────────────────┤
│              Supervisor Agent (Opus)              │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ gather   │ │ memory   │ │ activate_skill   │ │
│  │ context  │ │ recall   │ │ export           │ │
│  └──────────┘ └──────────┘ └──────────────────┘ │
├─────────────────────────────────────────────────┤
│                 Worker Agents (Sonnet)            │
│  ┌───────┐ ┌──────┐ ┌────────┐ ┌────────────┐  │
│  │ Email │ │Comms │ │Calendar│ │Productivity│  │
│  │       │ │(Slack)│ │        │ │(ToDo/Tix) │  │
│  ├───────┤ ├──────┤ ├────────┤ ├────────────┤  │
│  │Research│ │Share-│ │        │ │            │  │
│  │       │ │Point │ │        │ │            │  │
│  └───────┘ └──────┘ └────────┘ └────────────┘  │
├─────────────────────────────────────────────────┤
│              MCP Servers (External)              │
│  Outlook · Slack · Phonetool · SharePoint        │
├─────────────────────────────────────────────────┤
│              Amazon Bedrock (Claude)              │
│  Opus · Sonnet · Haiku · Nova Micro              │
└─────────────────────────────────────────────────┘
```

---

## Layer 1: The Entrypoint

The first decision: how does the user launch this thing?

Envoy uses a bash script as the entrypoint. It handles environment bootstrapping (venv creation, dependency installation, Midway auth refresh) before handing off to Python. This means the user never runs `pip install` manually — the first `envoy` invocation sets everything up.

The Python CLI uses Click with `invoke_without_command=True`:

```python
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        from repl import run_interactive
        run_interactive()
```

This single pattern gives you both interfaces: bare `envoy` launches the REPL, while `envoy digest --days 7` runs a subcommand and exits.

**Advice for builders:** This is the right default for any tool that's used interactively most of the time. The lazy import (`from repl import ...` inside the function) keeps subcommands fast — they never load the REPL infrastructure.

---

## Layer 2: The REPL

The interactive loop renders a logo, checks MCP server connections, creates the agent, and enters a prompt loop. Slash commands map directly to the same functions that CLI subcommands call:

```
/briefing  →  agent("Give me a full briefing")
/digest 7  →  runs the same digest logic as `envoy digest --days 7`
/prep-1on1 jsmith  →  activates the prep-1on1 skill
```

One implementation, two interfaces. Users don't learn two systems.

**Advice for builders:** Show connection status at startup. If your tool depends on external services, check them immediately and show green/red indicators. It takes a second but saves minutes of debugging.

---

## Layer 3: The Supervisor Agent

The supervisor is a Strands agent running Claude Opus. It has a focused set of high-level tools:

- `gather` — parallel multi-source data fetch with cross-referencing
- `read_email_thread` — drill into a specific email from a previous scan
- `lookup_person` — Phonetool profile lookup
- `search_emails` — targeted email search
- `show_context` — inspect what data is already loaded from previous turns
- `remember` / `recall` — persistent memory
- `activate_skill` — load specialized instructions on demand

The supervisor does NOT have direct access to send emails, post Slack messages, or modify calendars. Those capabilities live in workers. This separation is intentional — it keeps the supervisor's tool list small and its context window clean.

**Advice for builders:** Resist the urge to give your top-level agent every tool. A supervisor with 50 tools will waste tokens on tool selection and make worse decisions. Give it 10-15 orchestration tools and delegate the rest.

---

## Layer 4: Worker Agents

Each worker is a Strands agent with 5-8 domain-specific tools, running on a cheaper model (Sonnet). Workers are created lazily and cached:

```python
_workers = {}

def get_worker(name: str):
    if name not in _workers:
        factories = {
            "email": _email_create,
            "comms": _comms_create,
            "calendar": _calendar_create,
            ...
        }
        _workers[name] = factories[name]()
    return _workers[name]
```

The email worker has: `inbox`, `read_email`, `search_email`, `send_email`, `reply_email`, `forward_email`, `manage_email`, `cleanup_scan`. It doesn't know about Slack. The comms worker has Slack tools. It doesn't know about email.

Each worker gets a tight system prompt: "You are an email specialist. Be concise." No personality, no cross-domain instructions.

**Advice for builders:** Workers should be boring and focused. The personality and judgment live in the supervisor. Workers are execution engines.

---

## Layer 5: MCP Connections

Envoy talks to external systems through MCP (Model Context Protocol) servers. Each server is a separate process:

```python
OUTLOOK_PARAMS = StdioServerParameters(command="aws-outlook-mcp", args=[])
SLACK_PARAMS = StdioServerParameters(command="ai-community-slack-mcp", args=[])
```

Connections are wrapped in async context managers with timeouts:

```python
@asynccontextmanager
async def _mcp_session(params, name):
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            yield TimeoutSession(session, name, timeout=30)
```

A batch runner lets you make multiple calls in a single session, avoiding reconnection overhead:

```python
async def mcp_batch(server_name, calls):
    async with session_fn() as session:
        for tool_name, args in calls:
            results.append(await session.call_tool(tool_name, args))
```

**Advice for builders:** MCP is the right abstraction if you're connecting to multiple external services. Each server is isolated, testable, and replaceable. But always add timeouts — a hung MCP server will freeze your entire agent.


---

## Layer 6: The Gather Pattern

The most important tool in Envoy is `gather`. It fetches data from multiple sources in parallel and cross-references entities across them:

```python
@tool
def gather(sources="email,slack,calendar,todos", days=1):
    results = run(_gather_async(source_list, days, alias))
    xref = _cross_reference(results)
    return combined_output + xref
```

Cross-referencing extracts people, project IDs, and topics from each source, then finds overlaps. If "jsmith" appears in both an email thread and a Slack message, the briefing surfaces that connection.

**Advice for builders:** Parallel fetching is table stakes for a multi-source agent. Sequential calls make briefings painfully slow. And cross-referencing is what turns a data dump into actual intelligence.

---

## Layer 7: Memory

Envoy maintains persistent memory across sessions using three files:

- `entries.jsonl` — append-only log of actions, decisions, observations
- `entities.json` — entity-to-entry index for fast lookup
- `summary.json` — compressed per-entity summaries of older entries

Entity extraction is regex-based (no AI call needed): aliases, project IDs, capitalized names. Entries older than 7 days get compressed into per-entity summaries. The whole system has a 2MB cap with automatic pruning.

```python
def remember(text, entry_type="action"):
    entities = _extract_entities(text)  # regex, no AI
    entry = {"id": ..., "ts": ..., "text": text, "entities": entities}
    # append to JSONL, update index, prune if needed
```

**Advice for builders:** Don't skip memory. Without it, every session starts from zero. But keep it simple — JSONL + entity index is enough. You don't need a vector database for a personal assistant.

---

## Layer 8: Skills (Progressive Disclosure)

Skills follow the Agent Skills open standard. At startup, only name + description are loaded (~100 tokens per skill). Full instructions load on demand:

```python
def build_catalog(skills):
    # Injected into system prompt — just names and one-liners
    return '<skill name="prep-1on1">1:1 meeting prep brief</skill>'

def activate(name, skills):
    # Returns full SKILL.md body only when called
    return skills[name]["body"]
```

Skills are discovered from `~/.envoy/skills/` and `~/.agents/skills/`. Each is a folder with a `SKILL.md` containing YAML frontmatter and markdown instructions.

**Advice for builders:** This pattern scales. 50 skills at 100 tokens each = 5K tokens in the system prompt. Loading all 50 fully would be 50K+ tokens. Progressive disclosure keeps your context window lean.

---

## Layer 9: Workflows (Compound Commands)

Workflows orchestrate multiple agents for complex operations. A PTO catch-up, for example:

1. Fetches team email digest
2. Fetches leadership email digest
3. Fetches your inbox
4. Scans Slack
5. Scans customer emails
6. Fetches to-dos
7. Sends everything to a heavy-tier AI for synthesis

Each step is a try/except — if Slack is down, you still get email and calendar data. The AI prompt structures the output with priority sections.

**Advice for builders:** Make workflows resilient. Partial data is better than no data. Wrap each source in try/except and let the AI synthesize whatever you got.

---

## Layer 10: Personalization

`envoy init` builds three config files through an interactive wizard:

- `soul.md` — agent personality, tone, behavioral rules
- `envoy.md` — user context: name, role, manager, priorities, VIPs
- `process.md` — learned operational patterns (email rules, meeting preferences)

The agent can update these files during conversation (with user confirmation). When you say "always flag emails from my VP," it writes that to `process.md` and remembers it next session.

**Advice for builders:** Separating identity (soul) from user context (envoy) from learned behavior (process) keeps things clean. Users can edit any file directly, and the agent can update them programmatically.

---

## Layer 11: Heartbeat (Autonomous Mode)

Envoy can run on a cron schedule, checking user-defined routines:

```bash
0 8 * * * envoy heartbeat --notify slack
```

Routines are plain-language instructions stored in `~/.envoy/routines.md`. The heartbeat reads them, checks each using existing tools, deduplicates against recent alerts, and notifies via Slack DM.

**Advice for builders:** Autonomous mode is where an AI assistant becomes genuinely useful. But always deduplicate — nobody wants the same alert every morning.

---

## Layer 12: Export

Any report can be exported to Word (.docx) or PowerPoint (.pptx). The export module parses markdown sections and maps them to document elements:

- `#` headers → document headings
- Bullet lists → Word bullet styles
- Code blocks → monospace formatted paragraphs
- `##` sections → PowerPoint slides

**Advice for builders:** Export is a small feature that gets outsized appreciation. People need to share AI output with others who don't use your tool.

---

## Model Tiering

Not every task needs the best model. Envoy uses 5 tiers:

| Tier | Model | Used For |
|---|---|---|
| Agent | Opus | Conversational REPL, judgment calls |
| Heavy | Opus | Long summaries, document analysis |
| Medium | Sonnet | Workers, classification, scans |
| Light | Haiku | Simple extraction, lookups |
| Memory | Nova Micro | Memory compression |

Users can reassign models per tier via `/models` or `~/.envoy/models.json`.

**Advice for builders:** Model tiering saves money and latency. Your email classifier doesn't need Opus. Your memory compressor doesn't need Sonnet.

---

## How to Build Your Own

If you want to build something similar, here's the order of operations:

1. **Pick your MCP servers.** What systems do you need to connect to? Email, Slack, calendar, databases, APIs? Each becomes an MCP server.

2. **Build the entrypoint.** Bash wrapper for bootstrapping + Click group with `invoke_without_command=True` for the REPL/subcommand split.

3. **Build one worker first.** Start with the domain you care about most (probably email). Get it working end-to-end: fetch, read, search, send.

4. **Add the supervisor.** Give it a `gather` tool that calls your worker, plus `remember`/`recall` for memory. This is your MVP.

5. **Add more workers.** Each new domain is a new worker with 5-8 tools. The supervisor routes to them.

6. **Add workflows.** Compound commands that orchestrate multiple workers. Start with a morning briefing.

7. **Add personalization.** Config files for identity, preferences, and learned behavior. Let the agent update them.

8. **Add skills.** Progressive disclosure keeps the system prompt lean as you add capabilities.

9. **Add heartbeat.** Cron-based autonomous checks. This is where it goes from "tool" to "assistant."

10. **Add export.** Word and PowerPoint output for sharing.

---

## Key Lessons

- **Lazy everything.** Lazy imports, lazy worker creation, lazy skill loading. Fast startup matters.
- **Parallel fetching.** Never make the user wait for sequential API calls.
- **Confirm destructive actions.** Always ask before sending, deleting, or modifying.
- **Partial results beat no results.** If one source is down, show what you have.
- **Memory is essential.** Without it, every session is groundhog day.
- **Separate orchestration from execution.** The supervisor thinks. Workers do.
- **Respect the context window.** Progressive disclosure, model tiering, and focused worker prompts all serve this goal.
- **Make it scriptable.** Every interactive feature should also work as a CLI subcommand for cron and pipelines.
