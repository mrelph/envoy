"""Skill builder — generate, save, and suggest new Agent Skills from within Envoy."""

import os
from pathlib import Path
from agents.base import invoke_ai
from agents.memory2 import _load_entries
from agents.skills import get_skills, reload_skills, CONFIG_DIR

SKILLS_DIR = CONFIG_DIR / "skills"

_GENERATE_PROMPT = """\
Generate an Agent Skill SKILL.md file for the following request.

The file MUST follow this exact format:
---
name: {slug}
description: {description}
metadata:
  author: envoy
  version: "1.0"
allowed-tools: {tools}
---

# {title}

## When to use
[When should this skill activate]

## Steps
[Numbered steps the agent should follow]

## Output format
[How to format the result]

## Tips
[Helpful notes]

User request: {request}

Generate the complete SKILL.md content now. Use the slug "{slug}" as the name."""

_SUGGEST_PROMPT = """\
Based on these recent user interactions and observations, suggest 2-3 new Agent Skills
that would automate recurring patterns. Each suggestion should include:
- A short slug name (lowercase, hyphenated)
- A one-line description
- What it would do (2-3 sentences)

Only suggest skills that don't already exist. Existing skills: {existing}

Recent activity:
{activity}

Format each as:
### skill-name
Description: ...
What it does: ..."""


def generate_skill(request: str, slug: str = "", tools: str = "") -> str:
    """Use AI to generate a SKILL.md from a natural language description."""
    if not slug:
        slug = invoke_ai(
            f"Generate a short lowercase hyphenated slug (2-3 words) for this skill: {request}\nReturn ONLY the slug, nothing else.",
            max_tokens=20, tier="light"
        ).strip().strip('"').strip("'")

    description = invoke_ai(
        f"Write a one-sentence description for an agent skill that does: {request}\nReturn ONLY the description.",
        max_tokens=80, tier="light"
    ).strip()

    title = slug.replace("-", " ").title()

    content = invoke_ai(
        _GENERATE_PROMPT.format(
            slug=slug, description=description, tools=tools or "email_worker, comms_worker",
            title=title, request=request
        ),
        max_tokens=1200, tier="medium"
    ).strip()

    return content, slug


def save_skill(content: str, slug: str) -> str:
    """Save a generated skill to ~/.envoy/skills/{slug}/SKILL.md."""
    skill_dir = SKILLS_DIR / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(content)
    reload_skills()
    return str(skill_file)


def suggest_skills(days: int = 14) -> str:
    """Analyze recent memory/observations and suggest new skills."""
    entries = _load_entries(days)
    if not entries:
        return "No recent activity to analyze. Use Envoy more and try again later."

    observations = [e for e in entries if e.get("type") == "observation"]
    actions = [e for e in entries if e.get("type") != "observation"][-30:]
    activity_lines = []
    for e in (observations[-20:] + actions[-20:]):
        activity_lines.append(f"- {e.get('text', '')[:150]}")

    if not activity_lines:
        return "Not enough activity data to suggest skills yet."

    existing = ", ".join(get_skills().keys())
    return invoke_ai(
        _SUGGEST_PROMPT.format(existing=existing, activity="\n".join(activity_lines)),
        max_tokens=800, tier="medium"
    )
