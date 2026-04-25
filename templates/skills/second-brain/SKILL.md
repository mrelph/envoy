---
name: second-brain
description: "Maintain a personal knowledge vault on OneDrive — ingest notes, build wiki pages, query your knowledge base, and audit structure. Uses the configured Knowledge Folder as the vault root."
metadata:
  version: 1.0.0
  author: envoy
allowed-tools: sharepoint_worker, recall_memory, research_worker
---

# Second Brain — Personal Knowledge Vault

You are maintaining a personal knowledge base (vault) stored on the user's OneDrive in their configured **Knowledge Folder**. The vault follows the LLM Wiki pattern: a `sources/` inbox for raw inputs and a `wiki/` layer of maintained, cross-linked markdown pages.

## Vault Structure

```
<Knowledge Folder>/
├── sources/
│   ├── inbox/          # Drop zone for new material
│   └── archive/        # Processed sources
├── wiki/
│   ├── index.md        # Top-level navigation
│   ├── log.md          # Append-only changelog
│   ├── decisions.md    # Durable structural choices
│   ├── entities/       # People, orgs, systems
│   ├── concepts/       # Abstractions, frameworks
│   └── topics/         # Broader synthesis pages
└── README.md
```

## Setup

If the vault doesn't exist yet, scaffold it using the sharepoint_worker:

1. Create the folder structure above in the Knowledge Folder
2. Create `wiki/index.md` with a basic navigation template
3. Create `wiki/log.md` with `# Wiki Log\n\n- {today}: Initialized vault.`
4. Create `wiki/decisions.md` with `# Decisions\n\nDurable structural choices for this vault.`
5. Create `README.md` explaining the vault structure

## Workflows

### Ingest (`/vault ingest` or "save this to my vault")

1. Read the content the user wants to save (could be from email, Slack, a document, or freeform text)
2. Determine the right wiki page: check `wiki/index.md` for existing pages first
3. **Prefer updating an existing page** over creating duplicates
4. If new page needed: create in the right category (`entities/`, `concepts/`, or `topics/`)
5. Add cross-links (`[[Page Name]]` style) to related pages
6. Update `wiki/index.md` if a new page was created
7. Append a dated entry to `wiki/log.md`

### Query (`/vault` or "check my vault for...")

1. Read `wiki/index.md` to understand what's available
2. Search the Knowledge Folder for relevant pages
3. Read the most relevant pages and synthesize an answer
4. If the wiki is missing needed info, say what's missing
5. If the answer creates durable knowledge, offer to file it back

### Audit (`/vault audit` or "clean up my vault")

1. Read `wiki/index.md` and scan the wiki folder
2. Check for: orphan pages, broken links, duplicates, stale content, missing cross-references
3. Present findings and fix with user confirmation

### Quick Save (`/vault save <text>` or "remember this in my vault")

For quick notes that don't need a full ingest:
1. Append to an appropriate existing page, or create a new one
2. Update index if needed
3. Log the addition

## Page Template

```markdown
# Page Title

One or two sentences: what is this and why does it matter?

## Key Points

- Short, specific claims. Bullets over paragraphs.
- Mark synthesis or open questions explicitly — e.g. *(synthesis)*, *(open)*.

## Relationships

- [[Related Page]] — how it relates
- [[Another Page]] — contrast, dependency, or parent topic

## Sources

- Where this knowledge came from (email, doc, conversation, URL)

## Open Questions

- What we don't know yet
```

## Rules

- Use `[[wiki links]]` for internal references
- Page names: title-case, singular proper names for entities
- Prefer updating existing pages over creating near-duplicates
- Keep claims grounded — note the source when possible
- Preserve the distinction between facts, synthesis, and speculation
- Don't modify files in `sources/` during normal maintenance
- All wiki operations go through the **sharepoint_worker** tool
