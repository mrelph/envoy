# Multi-Agent Architecture Evolution Plan

## Current State
Hierarchical multi-agent: one supervisor with specialized worker agents. Workers are reactive, don't call each other, and skills augment the supervisor only via prompt injection.

## Phase 1: Worker-to-Worker Delegation ✅ COMPLETE
Let workers call each other (depth-limited to 1 hop) instead of round-tripping through the supervisor.

**Implemented:**
- `delegate_to_worker(worker_name, request)` tool injected into all workers via `_import_create`
- Depth guard (max 1 hop) via thread-local counter
- Workers have sibling descriptions in system prompt
- `_LockedWorker` serializes concurrent calls

---

## Phase 2: Planning Agent (Pre-Router) ✅ COMPLETE
For complex multi-step requests, decompose into a plan before executing.

**Implemented:** `agents/planner.py`
- `needs_planning(query)` heuristic — triggers for multi-domain/complex requests, bypasses for simple ones
- `generate_plan(query)` — light-tier LLM (Haiku) generates JSON plan: `[{id, tool, request, depends_on}]`
- `execute_plan(plan)` — ThreadPoolExecutor runs steps in parallel (no deps) or sequential (with deps)
- `plan_and_execute(query)` — full pipeline, feeds gathered context to supervisor for synthesis
- Integrated in `dispatch.py` — complex freeform queries go through planner before agent
- Graceful fallback — if planner fails, falls through to direct agent call

---

## Phase 3: Skills as Subagents ✅ COMPLETE
Skills get their own agent instance with scoped tools, not just prompt injection.

**Implemented:** Extended `agents/skills.py`
- SKILL.md frontmatter extension: `tools:`, `model:`, `memory_namespace:`
- Skills with `tools:` declared → `is_subagent=True` → spawns own Strands Agent
- `spawn_skill_agent(skill)` — creates Agent with scoped tools + namespaced memory
- `run_skill(name, request)` — invokes subagent, falls back to instructions on failure
- `_get_namespaced_memory_tools(namespace)` — isolated remember/recall per skill
- `_resolve_skill_tools(names)` — maps tool names to worker delegates or supervisor tools
- `activate_skill` tool updated — routes subagents through `run_skill`, legacy unchanged
- Backward compatible: existing skills without `tools:` continue as prompt injection

**Example SKILL.md (subagent):**
```yaml
---
name: deal-tracker
description: Track active deals by scanning email
tools:
  - email
  - research
  - vault_write
model: light
memory_namespace: deals
---
```

---

## Phase 4: Shared Workspace (Emergent Collaboration) ✅ COMPLETE
Agents work on a shared artifact asynchronously.

**Implemented:** `agents/workspace.py`
- `Workspace` dataclass: findings[], action_items[], open_questions[], draft_sections{}
- Priority-aware ordering (🔴 high items surface first)
- `make_workspace_tools()` — workspace_append + workspace_read injected into all workers
- `synthesize()` — medium-tier LLM assembles workspace into polished response
- Small workspaces (<2K chars) returned directly (no LLM call needed)
- Integrated with planner: create workspace → execute plan → synthesize → clear
- Fallback: if workers don't use workspace, raw results returned as before
- Thread-safe lifecycle: create/get/clear with lock

---

## Sequencing

| Phase | Value | Risk | Timeline |
|-------|-------|------|----------|
| 1. Worker-to-Worker | High | Low | 1-2 days |
| 2. Planner | High | Medium | 3-5 days |
| 3. Skill Subagents | Medium | Medium | 1 week |
| 4. Shared Workspace | High (complex) | High | 2 weeks |
