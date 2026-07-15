"""Skill loader — discover, parse, and activate Agent Skills (agentskills.io).

Skills can operate in two modes:
1. **Prompt injection** (legacy) — skill body injected into supervisor context
2. **Subagent** (new) — skill spawns its own Strands Agent with scoped tools and namespaced memory

A skill opts into subagent mode by declaring `tools:` in its frontmatter.
"""

import os
import re
from pathlib import Path
from typing import Dict, Optional

from agents.paths import CONFIG_DIR

# Scan paths in priority order (project > user-client > user-shared)
SKILL_PATHS = [
    Path(".") / ".envoy" / "skills",
    Path(".") / ".agents" / "skills",
    CONFIG_DIR / "skills",
    Path.home() / ".agents" / "skills",
]


def _parse_skill_md(path: Path) -> Optional[dict]:
    """Parse a SKILL.md file into skill record.

    Frontmatter fields:
        name: (required) skill identifier
        description: (required) what the skill does
        metadata: optional metadata dict
        allowed-tools: (legacy) space-separated tool names
        tools: (subagent mode) list of worker/tool names this skill can use
        model: (subagent mode) model tier — light, medium, heavy (default: medium)
        memory_namespace: (subagent mode) isolated memory scope name (default: skill name)
    """
    import yaml

    try:
        text = path.read_text()
    except Exception:
        return None

    # Extract YAML frontmatter
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', text, re.DOTALL)
    if not m:
        return None

    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None

    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description"):
        return None

    skill = {
        "name": meta["name"],
        "description": meta["description"],
        "metadata": meta.get("metadata", {}),
        "allowed_tools": meta.get("allowed-tools", ""),
        "body": m.group(2).strip(),
        "location": str(path),
        "dir": str(path.parent),
        # Subagent fields (None means legacy prompt-injection mode)
        "tools": meta.get("tools"),  # list of tool/worker names
        "model": meta.get("model", "medium"),
        "memory_namespace": meta.get("memory_namespace", meta["name"]),
    }
    # A skill is a subagent if it explicitly declares tools
    skill["is_subagent"] = skill["tools"] is not None
    return skill


def discover_skills() -> Dict[str, dict]:
    """Scan all skill paths and return {name: skill_record} dict.
    Project-level skills override user-level (first found wins)."""
    skills = {}
    for base in SKILL_PATHS:
        base = base.expanduser().resolve()
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            skill_md = entry / "SKILL.md"
            if entry.is_dir() and skill_md.exists():
                skill = _parse_skill_md(skill_md)
                if skill and skill["name"] not in skills:
                    skills[skill["name"]] = skill
    return skills


def build_catalog(skills: Dict[str, dict]) -> str:
    """Build the skill catalog XML for injection into the system prompt."""
    if not skills:
        return ""
    lines = ["<available_skills>"]
    for s in skills.values():
        lines.append(f'  <skill name="{s["name"]}">{s["description"]}</skill>')
    lines.append("</available_skills>")
    return "\n".join(lines)


def activate(name: str, skills: Dict[str, dict]) -> str:
    """Activate a skill by name — return its full instructions."""
    skill = skills.get(name)
    if not skill:
        available = ", ".join(skills.keys()) if skills else "none"
        return f"Skill '{name}' not found. Available: {available}"

    body = skill["body"]

    # List bundled resources
    skill_dir = Path(skill["dir"])
    resources = []
    for subdir in ("scripts", "references", "assets"):
        d = skill_dir / subdir
        if d.is_dir():
            for f in sorted(d.rglob("*")):
                if f.is_file():
                    resources.append(str(f.relative_to(skill_dir)))

    result = f'<skill_content name="{name}">\n{body}\n\nSkill directory: {skill["dir"]}'
    if resources:
        result += "\n\n<skill_resources>\n"
        result += "\n".join(f"  {r}" for r in resources)
        result += "\n</skill_resources>"
    result += "\n</skill_content>"
    return result


# Module-level cache
_skills_cache = None

def get_skills() -> Dict[str, dict]:
    global _skills_cache
    if _skills_cache is None:
        _skills_cache = discover_skills()
    return _skills_cache

def reload_skills():
    global _skills_cache
    _skills_cache = None


def save_skill_md(slug: str, content: str) -> Path:
    """Save a SKILL.md to the user skills directory and reload cache."""
    skill_dir = CONFIG_DIR / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "SKILL.md"
    path.write_text(content)
    reload_skills()
    return path


# ── Subagent Skills ─────────────────────────────────────────────────

_MEMORY_BASE = CONFIG_DIR / "memory" / "skills"
_skill_agents = {}  # cached: skill_name → Agent


def _get_namespaced_memory_tools(namespace: str):
    """Create remember/recall tools scoped to a skill's namespace."""
    from strands import tool

    mem_dir = _MEMORY_BASE / namespace
    mem_dir.mkdir(parents=True, exist_ok=True)
    mem_file = mem_dir / "entries.jsonl"

    @tool
    def remember(entry: str) -> str:
        """Save a note to this skill's memory for future reference.

        Args:
            entry: What to remember (concise observation, decision, or fact)
        """
        import json
        from datetime import datetime
        record = {"ts": datetime.now().isoformat(), "entry": entry}
        with open(mem_file, "a") as f:
            f.write(json.dumps(record) + "\n")
        return f"Remembered: {entry[:100]}"

    @tool
    def recall(query: str = "") -> str:
        """Recall entries from this skill's memory.

        Args:
            query: Optional keyword filter (empty = last 20 entries)
        """
        import json
        if not mem_file.exists():
            return "No memory entries yet."
        lines = mem_file.read_text().strip().split("\n")
        entries = []
        for line in lines[-50:]:  # last 50 max
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        if query:
            entries = [e for e in entries if query.lower() in e.get("entry", "").lower()]
        if not entries:
            return "No matching memory entries."
        return "\n".join(f"[{e['ts'][:16]}] {e['entry']}" for e in entries[-20:])

    return [remember, recall]


def _resolve_skill_tools(tool_names: list) -> list:
    """Resolve tool name strings to actual tool objects from workers and supervisor."""
    tools = []
    from agents.workers import get_worker, WORKER_NAMES

    for name in tool_names:
        if name in WORKER_NAMES:
            # Create a delegate tool for this specific worker
            worker_name = name
            from strands import tool as _tool_dec

            @_tool_dec
            def _delegate(request: str, _wn=worker_name) -> str:
                f"""Delegate a request to the {_wn} worker.

                Args:
                    request: Natural language request for the worker
                """
                worker = get_worker(_wn)
                result = worker(request)
                return str(result.message) if hasattr(result, 'message') else str(result)

            # Rename the tool to match the worker
            _delegate.tool_name = f"{worker_name}_worker"
            tools.append(_delegate)
        else:
            # Try to find it in supervisor tools or _SKILL_TOOLS
            try:
                import tools as _t
                if hasattr(_t, '_SKILL_TOOLS') and name in _t._SKILL_TOOLS:
                    tools.append(_t._SKILL_TOOLS[name])
                else:
                    # Search ALL_TOOLS
                    for t in _t._ALL_TOOLS_RAW:
                        if getattr(t, 'tool_name', getattr(t, '__name__', '')) == name:
                            tools.append(t)
                            break
            except Exception:
                pass
    return tools


def spawn_skill_agent(skill: dict):
    """Create a Strands Agent for a subagent skill.
    
    The agent gets:
    - Skill body as system prompt
    - Scoped tools (only what the skill declared)
    - Namespaced memory tools (remember/recall isolated to this skill)
    - Model tier from skill config
    """
    from strands import Agent
    from strands.models import BedrockModel
    from agents.base import _load_models

    name = skill["name"]
    if name in _skill_agents:
        return _skill_agents[name]

    # Resolve model
    models = _load_models()
    tier = skill.get("model", "medium")
    model_id = models.get(tier, models.get("medium", "us.anthropic.claude-sonnet-5"))

    model = BedrockModel(
        model_id=model_id,
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
    )

    # Build system prompt from skill body
    system_prompt = f"""You are a specialized skill agent: {name}
{skill['description']}

{skill['body']}

You have access to scoped tools and your own memory namespace. Be concise and action-oriented.
If a tool times out or fails, report what you have and return immediately."""

    # Resolve tools
    declared_tools = skill.get("tools", [])
    tools = _resolve_skill_tools(declared_tools)

    # Add namespaced memory
    namespace = skill.get("memory_namespace", name)
    memory_tools = _get_namespaced_memory_tools(namespace)
    tools.extend(memory_tools)

    agent = Agent(
        model=model,
        system_prompt=system_prompt,
        tools=tools,
    )

    _skill_agents[name] = agent
    return agent


def run_skill(name: str, request: str) -> str:
    """Run a skill as a subagent and return its response.
    
    For subagent skills: spawns/retrieves the skill agent and invokes it.
    For legacy skills: falls back to activate() for prompt injection.
    
    Args:
        name: Skill name
        request: Natural language request for the skill
        
    Returns:
        Skill agent's response string, or activation text for legacy skills.
    """
    skills = get_skills()
    skill = skills.get(name)
    if not skill:
        available = ", ".join(skills.keys()) if skills else "none"
        return f"Skill '{name}' not found. Available: {available}"

    # Legacy skills — no tools declared, use prompt injection
    if not skill.get("is_subagent"):
        return activate(name, skills)

    # Subagent skills — spawn and invoke
    try:
        agent = spawn_skill_agent(skill)
        result = agent(request)
        response = str(result.message) if hasattr(result, 'message') else str(result)
        return response[:8000]  # cap to avoid context bloat
    except Exception as e:
        return f"⚠️ Skill '{name}' failed: {e}. Falling back to instructions.\n\n{activate(name, skills)}"
