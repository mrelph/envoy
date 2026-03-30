"""Skill loader — discover, parse, and activate Agent Skills (agentskills.io)."""

import os
import re
import yaml
from pathlib import Path
from typing import Dict, Optional

CONFIG_DIR = Path.home() / ".envoy"

# Scan paths in priority order (project > user-client > user-shared)
SKILL_PATHS = [
    Path(".") / ".envoy" / "skills",
    Path(".") / ".agents" / "skills",
    CONFIG_DIR / "skills",
    Path.home() / ".agents" / "skills",
]


def _parse_skill_md(path: Path) -> Optional[dict]:
    """Parse a SKILL.md file into {name, description, body, location, dir}."""
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

    return {
        "name": meta["name"],
        "description": meta["description"],
        "metadata": meta.get("metadata", {}),
        "allowed_tools": meta.get("allowed-tools", ""),
        "body": m.group(2).strip(),
        "location": str(path),
        "dir": str(path.parent),
    }


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
