"""Shared Workspace — structured collaboration artifact for multi-agent output.

Workers post to typed slots in the workspace. A synthesizer assembles
the final output. Per-request lifecycle: create → append → synthesize → clear.

Workspace structure:
    findings[]       — facts, data points, observations from any source
    action_items[]   — things the user needs to do
    open_questions[] — unresolved items needing user input
    draft_sections{} — named prose sections (e.g., "calendar", "priorities")
    metadata{}       — source tracking, timestamps
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from agents.base import invoke_ai


# ── Data Model ──────────────────────────────────────────────────────

@dataclass
class WorkspaceEntry:
    content: str
    source: str  # which worker/agent posted this
    timestamp: float = field(default_factory=time.time)
    priority: str = "normal"  # high, normal, low


@dataclass
class Workspace:
    """A per-request structured artifact that agents collaborate on."""
    id: str
    query: str  # the original user request
    findings: list = field(default_factory=list)
    action_items: list = field(default_factory=list)
    open_questions: list = field(default_factory=list)
    draft_sections: dict = field(default_factory=dict)  # name → text
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def append(self, section: str, content: str, source: str = "", priority: str = "normal"):
        """Add content to a workspace section."""
        entry = WorkspaceEntry(content=content, source=source, priority=priority)
        if section == "findings":
            self.findings.append(entry)
        elif section == "action_items":
            self.action_items.append(entry)
        elif section == "open_questions":
            self.open_questions.append(entry)
        elif section.startswith("draft:"):
            # draft:calendar, draft:priorities, etc.
            name = section[6:]
            existing = self.draft_sections.get(name, "")
            self.draft_sections[name] = (existing + "\n" + content).strip()
        else:
            # Generic — treat as finding
            self.findings.append(entry)

    def read(self, section: str = "") -> str:
        """Read workspace contents. Empty section = everything."""
        if not section:
            return self._format_all()
        if section == "findings":
            return self._format_entries(self.findings)
        if section == "action_items":
            return self._format_entries(self.action_items)
        if section == "open_questions":
            return self._format_entries(self.open_questions)
        if section.startswith("draft:"):
            name = section[6:]
            return self.draft_sections.get(name, "")
        return self.draft_sections.get(section, self._format_all())

    def _format_entries(self, entries: list) -> str:
        if not entries:
            return "(empty)"
        # Sort high priority first
        sorted_entries = sorted(entries, key=lambda e: {"high": 0, "normal": 1, "low": 2}.get(e.priority, 1))
        lines = []
        for e in sorted_entries:
            prefix = "🔴 " if e.priority == "high" else ""
            src = f" [{e.source}]" if e.source else ""
            lines.append(f"- {prefix}{e.content}{src}")
        return "\n".join(lines)

    def _format_all(self) -> str:
        parts = []
        if self.findings:
            parts.append(f"## Findings\n{self._format_entries(self.findings)}")
        if self.action_items:
            parts.append(f"## Action Items\n{self._format_entries(self.action_items)}")
        if self.open_questions:
            parts.append(f"## Open Questions\n{self._format_entries(self.open_questions)}")
        for name, text in self.draft_sections.items():
            parts.append(f"## {name.title()}\n{text}")
        return "\n\n".join(parts) if parts else "(workspace is empty)"

    @property
    def is_empty(self) -> bool:
        return not self.findings and not self.action_items and not self.open_questions and not self.draft_sections


# ── Workspace Manager (per-request lifecycle) ───────────────────────

_lock = threading.Lock()
_active: Optional[Workspace] = None


def create(query: str) -> Workspace:
    """Create a new workspace for a request. Clears any previous one."""
    global _active
    with _lock:
        _active = Workspace(id=f"ws-{int(time.time())}", query=query)
    return _active


def get() -> Optional[Workspace]:
    """Get the active workspace (None if none active)."""
    return _active


def clear():
    """Clear the active workspace."""
    global _active
    with _lock:
        _active = None


# ── Tools for Workers ───────────────────────────────────────────────

def make_workspace_tools():
    """Create workspace_append and workspace_read tools for injection into workers."""
    from strands import tool

    @tool
    def workspace_append(section: str, content: str, priority: str = "normal") -> str:
        """Post a finding, action item, or draft to the shared workspace.

        Sections:
        - findings: facts, data points, observations
        - action_items: things the user needs to do (use priority="high" for urgent)
        - open_questions: unresolved items needing user input
        - draft:<name>: prose section (e.g., "draft:calendar", "draft:priorities")

        Args:
            section: Which section to post to (findings, action_items, open_questions, draft:<name>)
            content: What to post (concise — one fact or item per call)
            priority: high, normal, or low (affects ordering in output)
        """
        ws = get()
        if not ws:
            return "No active workspace. Content noted but not posted."
        ws.append(section, content, source="", priority=priority)
        return f"Posted to {section}."

    @tool
    def workspace_read(section: str = "") -> str:
        """Read the current workspace contents to see what other agents have posted.

        Args:
            section: Which section to read (empty = all). Options: findings, action_items, open_questions, draft:<name>
        """
        ws = get()
        if not ws:
            return "No active workspace."
        return ws.read(section)

    return [workspace_append, workspace_read]


# ── Synthesizer ─────────────────────────────────────────────────────

def synthesize(workspace: Optional[Workspace] = None) -> str:
    """Assemble workspace contents into a polished final output.
    
    Uses a medium-tier LLM to synthesize findings, action items,
    questions, and draft sections into a coherent response.
    """
    ws = workspace or get()
    if not ws or ws.is_empty:
        return ""

    raw = ws._format_all()
    
    # If the workspace is small enough, just return it formatted
    if len(raw) < 2000:
        return raw

    prompt = f"""Synthesize this structured workspace into a polished response for the user.
Their original question: "{ws.query}"

Rules:
- Lead with 🔴 action items (highest priority first)
- Group findings into clear themes, don't just list them
- Surface open questions at the end
- Be concise — the user wants signal, not noise
- Include draft sections as coherent prose (not raw bullets)
- Do NOT print internal reference IDs like [E1], [S1] — refer to items by description; they're tracked silently for drill-down

Workspace contents:
{raw[:12000]}"""

    try:
        return invoke_ai(prompt, max_tokens=4000, tier="medium")
    except Exception:
        # Fallback — return raw formatted workspace
        return raw
