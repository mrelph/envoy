"""Config tools — soul, envoy, process self-modification."""

import os
from strands import tool
from agents.base import outlook, builder, run


def _config_has_similar(path: str, new_rule: str, threshold: float = 0.6) -> str:
    """Check if a config file already has a similar rule."""
    if not os.path.exists(path):
        return ""
    new_words = set(new_rule.lower().split())
    if len(new_words) < 2:
        return ""
    for line in open(path):
        line = line.strip()
        if not line.startswith("- "):
            continue
        existing_words = set(line[2:].strip().lower().split())
        if not existing_words:
            continue
        overlap = len(new_words & existing_words) / max(len(new_words | existing_words), 1)
        if overlap >= threshold:
            return line[2:].strip()
    return ""


@tool
def update_soul(rule: str) -> str:
    """Add or update a rule in the agent's soul file (~/.envoy/soul.md).
    IMPORTANT: Always confirm with the user before calling this.

    Args:
        rule: The rule or personality directive to add
    """
    path = os.path.expanduser("~/.envoy/soul.md")
    existing = _config_has_similar(path, rule)
    if existing:
        return f"⚠️ Similar rule already exists: \"{existing}\"\nNo change made. Use `/settings` to edit manually."
    with open(path, "a") as f:
        f.write(f"\n- {rule}\n")
    return f"✅ Updated soul: {rule}\n⚠️ This change persists across sessions. Use `/settings` to review."


@tool
def update_envoy(preference: str) -> str:
    """Add or update a preference in the user's envoy config (~/.envoy/envoy.md).
    IMPORTANT: Always confirm with the user before calling this.

    Args:
        preference: The preference to add
    """
    path = os.path.expanduser("~/.envoy/envoy.md")
    existing = _config_has_similar(path, preference)
    if existing:
        return f"⚠️ Similar preference already exists: \"{existing}\"\nNo change made. Use `/settings` to edit manually."
    with open(path, "a") as f:
        f.write(f"\n- {preference}\n")
    return f"✅ Updated preferences: {preference}\n⚠️ This change persists across sessions. Use `/settings` to review."


@tool
def update_process(rule: str, section: str = "General") -> str:
    """Add a learned operational pattern to process memory (~/.envoy/process.md).
    IMPORTANT: Always confirm with the user before calling this.

    Args:
        rule: The process rule to add
        section: Section to file it under (Email, Meetings, Cleanup, Slack, Calendar, or any new section)
    """
    path = os.path.expanduser("~/.envoy/process.md")
    header = f"## {section}"
    existing = _config_has_similar(path, rule)
    if existing:
        return f"⚠️ Similar rule already exists: \"{existing}\"\nNo change made. Use `/settings` to edit manually."
    if not os.path.exists(path):
        tmpl = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "process.md")
        if os.path.exists(tmpl):
            import shutil
            shutil.copy(tmpl, path)
        else:
            with open(path, "w") as f:
                f.write(f"# Process Memory\n\n{header}\n- {rule}\n")
            return f"Created process memory: [{section}] {rule}"

    content = open(path).read()
    if header in content:
        content = content.replace(header, f"{header}\n- {rule}", 1)
    else:
        content = content.rstrip() + f"\n\n{header}\n- {rule}\n"
    with open(path, "w") as f:
        f.write(content)
    return f"Updated process memory: [{section}] {rule}"


@tool
def add_vip(alias: str) -> str:
    """Look up a person by alias in Phonetool and add them to High Priority People.

    Args:
        alias: The person's Amazon alias
    """
    info = {"alias": alias, "email": f"{alias}@amazon.com", "name": "", "title": ""}
    try:
        async def _lookup():
            async with builder() as session:
                res = await session.call_tool("ReadInternalWebsites",
                    arguments={"inputs": [f"https://phonetool.amazon.com/users/{alias}"]})
                return str(res.content[0].text) if res.content else ""
        text = run(_lookup())
        for line in text.split("\n"):
            line = line.strip()
            if ("Job Title:" in line or "Business Title:" in line) and not info["title"]:
                info["title"] = line.split(":", 1)[1].strip()
            elif line and not info["name"] and not line.startswith(("#", "[", "!", "|", "-", "*")):
                candidate = line.split("|")[0].strip()
                if candidate and len(candidate.split()) <= 5 and candidate[0].isupper():
                    info["name"] = candidate
    except Exception:
        pass

    entry = f"- {info['name'] or alias} | {info['alias']} | {info['email']} | {info['title']}"
    path = os.path.expanduser("~/.envoy/envoy.md")
    content = open(path).read() if os.path.exists(path) else ""
    section = "# High Priority People"
    if section in content:
        if alias in content.split(section)[1].split("\n#")[0]:
            return f"{info['name'] or alias} ({alias}) is already in High Priority People."
        content = content.replace(section, f"{section}\n{entry}", 1)
    else:
        content = content.rstrip() + f"\n\n{section}\n{entry}\n"
    with open(path, "w") as f:
        f.write(content)

    label = f"{info['name']} ({alias})" if info["name"] else alias
    title_part = f" — {info['title']}" if info["title"] else ""
    return f"Added {label}{title_part} to High Priority People."


ALL_CONFIG_TOOLS = [update_soul, update_envoy, update_process, add_vip]
