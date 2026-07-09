"""Skill builder — generate, save, and suggest new Agent Skills from within Envoy."""

import json
import os
import re
from pathlib import Path
from agents.base import invoke_ai
from agents.memory2 import _load_entries
from agents.skills import get_skills, reload_skills, CONFIG_DIR

SKILLS_DIR = CONFIG_DIR / "skills"

# A slug becomes a filesystem directory name (SKILLS_DIR / slug) — keep it
# limited to a safe, boring character set so it can never escape SKILLS_DIR
# or collide with something unexpected.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _sanitize_slug(raw: str) -> str:
    """Normalize an untrusted slug into a safe filesystem path component.

    Lowercases, turns whitespace into hyphens, strips anything outside
    [a-z0-9-], and drops leading/trailing hyphens. Raises ValueError if
    nothing usable remains — e.g. the slug was pure punctuation, or a path
    traversal attempt like "../../evil" whose separators get stripped away
    (leaving "evil", which is fine) versus one that evaporates entirely.
    """
    s = re.sub(r"\s+", "-", (raw or "").strip().lower())
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not s or not _SLUG_RE.match(s):
        raise ValueError(f"unusable skill slug: {raw!r}")
    return s


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

_GENERATE_JSON_PROMPT = """\
Generate an Agent Skill SKILL.md file for the following request.

Respond with ONLY a single JSON object (no prose, no markdown code fences) with exactly
these three keys:
- "slug": a short lowercase-hyphenated name (2-3 words){slug_hint}
- "description": a one-sentence description of what the skill does
- "body": the complete SKILL.md file content, following this exact format:

---
name: <slug>
description: <description>
metadata:
  author: envoy
  version: "1.0"
allowed-tools: {tools}
---

# <Title Case of the slug>

## When to use
[When should this skill activate]

## Steps
[Numbered steps the agent should follow]

## Output format
[How to format the result]

## Tips
[Helpful notes]

User request: {request}

Return the JSON object now."""

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


def _extract_first_json_object(text: str):
    """Find and parse the first balanced top-level {...} object in text.

    Tolerates surrounding prose or markdown fences that a model might add
    despite being asked for raw JSON. Returns None if nothing parses.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _generate_skill_single_call(request: str, slug: str, tools_desc: str):
    """Ask for {slug, description, body} as one JSON object in a single AI call.

    Returns (content, slug) on success, or None if the response couldn't be
    parsed into something usable — callers should fall back to the
    sequential 3-call path in that case.
    """
    slug_hint = f' — use exactly "{slug}" for the slug' if slug else ""
    prompt = _GENERATE_JSON_PROMPT.format(request=request, tools=tools_desc, slug_hint=slug_hint)
    raw = invoke_ai(prompt, max_tokens=1200, tier="medium")

    data = _extract_first_json_object(raw)
    if not isinstance(data, dict):
        return None

    body = data.get("body")
    slug_out = slug or data.get("slug")
    if not body or not slug_out:
        return None

    return str(body).strip(), str(slug_out).strip().strip('"').strip("'")


def _generate_skill_sequential(request: str, slug: str, tools_desc: str):
    """Original 3-call path: slug, then description, then body.

    Kept as the fallback for when the single structured call can't be
    parsed, so behavior degrades gracefully rather than breaking.
    """
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
            slug=slug, description=description, tools=tools_desc,
            title=title, request=request
        ),
        max_tokens=1200, tier="medium"
    ).strip()

    return content, slug


def generate_skill(request: str, slug: str = "", tools: str = "") -> str:
    """Use AI to generate a SKILL.md from a natural language description.

    Makes a single structured AI call requesting {slug, description, body}
    as JSON. Falls back to the previous 3-call sequence (slug, then
    description, then body) if the response can't be parsed as JSON.
    """
    tools_desc = tools or "email_worker, comms_worker"

    if slug:
        try:
            slug = _sanitize_slug(slug)
        except ValueError:
            return f"Error: invalid skill slug '{slug}' — could not derive a safe name.", ""

    result = _generate_skill_single_call(request, slug, tools_desc)
    if result is None:
        result = _generate_skill_sequential(request, slug, tools_desc)
    content, slug_out = result

    try:
        slug_out = _sanitize_slug(slug_out)
    except ValueError:
        return "Error: could not derive a safe skill slug for this skill.", ""

    return content, slug_out


def save_skill(content: str, slug: str) -> str:
    """Save a generated skill to ~/.envoy/skills/{slug}/SKILL.md."""
    try:
        slug = _sanitize_slug(slug)
    except ValueError:
        return f"Error: invalid skill slug '{slug}' — refusing to save."

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
