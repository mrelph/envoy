# Obsidian Vault Integration Plan

## Architecture

Obsidian vaults are local folders of markdown files with `[[wikilinks]]`, YAML frontmatter, and a `.obsidian/` config directory. No API or MCP needed — direct filesystem access.

```
~/.envoy/envoy.md                    Obsidian vault path config
        │
        ▼
agents/obsidian.py                   Core vault reader/searcher/writer
        │
        ├──► research_worker.py      vault_search, vault_read tools
        ├──► supervisor gather()     "vault" as a gather source
        ├──► memory2.py              Vault as extended memory backend
        └──► agent.py                Vault context injected into system prompt
```

## Config (envoy.md)

```markdown
# Obsidian
- Obsidian vault: ~/Documents/MyVault
- Daily note pattern: Daily Notes/%Y-%m-%d
- Vault active tags: #active, #wip, #priority
- Vault output folder: Envoy
```

---

## Phase 1: Read-Only Vault Access

Add to research worker:

- `vault_search(query, tag)` — full-text search across all `.md` files
- `vault_read(path, include_links)` — read a note, resolving `[[wikilinks]]` to show linked context
- `vault_daily(date)` — read today's (or any day's) daily note

Key design:
- Resolve `[[wikilinks]]` by scanning vault for matching filenames (how Obsidian works)
- Parse YAML frontmatter for tags, aliases, dates
- Skip `.obsidian/` and `.trash/` directories
- Index file paths at startup for fast wikilink resolution, read content on demand (vaults can be huge)

## Phase 2: Vault as Gather Source

Add `"vault"` as a source in `gather()`. During briefings/catchups:

1. Pull today's daily note for context on what was planned
2. Search for notes tagged with `#active` / `#wip` to surface ongoing projects
3. Cross-reference vault entities (people, projects) against email/Slack/calendar entities

Entity extraction reuses existing `memory2._extract_entities()`.

## Phase 3: Write — Append + Create

### Append to existing notes (low risk)

- **Daily note journaling** — after briefings, append `## Envoy Summary` with action items, key emails, decisions
- **Meeting notes** — after 1:1/meeting prep, append brief to relevant note or daily note
- **Action item capture** — append `- [ ] task` checkboxes from email/Slack to daily note

Pattern: always append below `---` separator with timestamp header so user sees what Envoy added vs. what they wrote.

### Create new notes (medium risk)

- **Meeting notes** — `Meetings/2026-04-11 - Weekly Sync.md` with attendees, agenda, prep, action items
- **Person notes** — `People/Alice Smith.md` with Phonetool info, recent interactions, talking points (personal CRM)
- **Decision logs** — capture decisions with context, rationale, date
- **Email digests** — save weekly digest as vault note

Pattern: always use frontmatter with `source: envoy`, `created: <timestamp>`, relevant tags. Put in configurable subfolder (default `Envoy/`).

### Tools

- `vault_append(path, content)` — append to existing note (daily note shortcut if path empty)
- `vault_create(path, content, tags, template)` — create new note with frontmatter

## Phase 4: Organize + Suggest

Higher risk — always dry-run first, show plan, get confirmation.

- **Tag suggestions** — scan notes missing frontmatter tags, suggest based on content
- **Link suggestions** — find notes mentioning same topics but not linked, suggest `[[wikilinks]]`
- **Orphan detection** — find notes with no inbound/outbound links, suggest connections
- **Frontmatter normalization** — standardize inconsistent frontmatter (`date:` vs `created:` etc.)
- **Folder reorganization** — suggest moves based on content/tags, never auto-move

### Tools

- `vault_suggest_tags(path_or_all)` — suggest tags for untagged notes
- `vault_suggest_links(path_or_all)` — suggest missing wikilinks
- `vault_orphans()` — find disconnected notes

## Phase 5: Format + Clean

Highest risk — opt-in, show diffs, create backups.

- **Formatting cleanup** — fix broken markdown, normalize headings
- **Summary generation** — add TLDR section to long notes
- **Template application** — apply consistent structure to note types

### Tools

- `vault_normalize(path, dry_run=True)` — show formatting fixes
- `vault_summarize(path)` — generate and prepend summary

---

## Guardrail Framework

| Operation | Confirmation Required | Backup Created |
|---|---|---|
| Append to daily note | No (append-only) | No |
| Append to other notes | Yes | No |
| Create new note | No (non-destructive) | No |
| Add/modify frontmatter | Yes (show diff) | No |
| Add wikilinks to body | Yes (show diff) | No |
| Reorganize/move files | Yes (show full plan) | Yes |
| Modify note body | Yes (show diff) | Yes (.bak) |

## Design Principles

- **Don't build an MCP server.** Vault is local files — direct filesystem is simpler and faster.
- **Don't index entire vault into memory2.** Vaults can be gigabytes. Search on demand.
- **Don't sync bidirectionally with memory2.** Keep them separate — memory2 is ephemeral operational memory, vault is long-term knowledge.
- **Don't parse Obsidian plugins or canvas files.** Stick to `.md` with standard frontmatter and wikilinks.
- **Phase 4-5 could ship as Agent Skills** (`vault-organize/SKILL.md`) rather than core tools.

## Example: Morning Briefing with Vault

```
/briefing

📅 Calendar: 3 meetings today
📧 Email: 12 new, 3 🔴 action required  
💬 Slack: 5 unread DMs
📓 Vault: Your daily note has 4 open tasks from yesterday

🔴 Action Required:
- [E1] Sarah's pricing proposal needs response by EOD
  📓 Related: [[Project Aurora]] — vault note says budget cap is $2.4M
- [S1] @alice asked about migration timeline in #team-infra
  📓 Related: [[Migration Plan]] — last updated 3 days ago

📓 Carried over from yesterday's daily note:
- [ ] Review PR from @bob  
- [ ] Send updated timeline to leadership
- [ ] Book room for Thursday design review
- [ ] Follow up with vendor on SOW

Want me to:
1. Append today's briefing to your daily note?
2. Create a prep note for your 10am 1:1 with Sarah?
3. Mark the PR review as done? (Bob's PR was merged yesterday)
```
