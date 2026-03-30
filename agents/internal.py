"""Internal websites agent — Kingpin, Broadcast, Meetings, Wiki, Taskei, Tiny via builder-mcp."""

import asyncio
from agents.base import builder


async def _fetch(url: str) -> str:
    async with builder() as session:
        result = await session.call_tool("ReadInternalWebsites", {"inputs": [url]})
        return result.content[0].text if result.content else "No result."


async def _fetch_many(urls: list) -> str:
    async with builder() as session:
        result = await session.call_tool("ReadInternalWebsites", {"inputs": urls})
        return result.content[0].text if result.content else "No result."


# --- Kingpin ---

async def get_goal(goal_id: str) -> str:
    return await _fetch(f"https://kingpin.amazon.com/#/items/{goal_id}")


async def get_goal_children(goal_id: str) -> str:
    return await _fetch(f"https://kingpin.amazon.com/#/items/{goal_id}#Relationships")


# --- Broadcast ---

async def search_broadcast(query: str) -> str:
    return await _fetch(f"https://broadcast.amazon.com/search?q={query}")


async def get_video(video_id: str) -> str:
    return await _fetch(f"https://broadcast.amazon.com/videos/{video_id}")


# --- Meetings ---

async def get_calendar(alias: str, start_time: str, end_time: str) -> str:
    return await _fetch(
        f"https://meetings.amazon.com/calendar/find/{alias}?startTime={start_time}&endTime={end_time}")


async def get_meeting_detail(entry_id: str, alias: str) -> str:
    return await _fetch(
        f"https://meetings.amazon.com/calendar/get/{entry_id}?alias={alias}")


async def find_rooms(building: str, **kwargs) -> str:
    params = f"https://meetings.amazon.com/rooms/find/{building}"
    extras = []
    if kwargs.get("floor"):
        extras.append(f"floor={kwargs['floor']}")
    if kwargs.get("min_capacity"):
        extras.append(f"minCapacity={kwargs['min_capacity']}")
    if kwargs.get("start_time") and kwargs.get("end_time"):
        extras.append(f"availability=true&startTime={kwargs['start_time']}&endTime={kwargs['end_time']}")
    if extras:
        params += "?" + "&".join(extras)
    return await _fetch(params)


# --- Wiki ---

async def get_wiki(path: str) -> str:
    return await _fetch(f"https://w.amazon.com/bin/view/{path}")


async def get_wiki_owner(path: str) -> str:
    return await _fetch(f"https://w.amazon.com/bin/owner/{path}")


# --- Taskei ---

async def get_task(task_id: str) -> str:
    return await _fetch(f"https://taskei.amazon.dev/tasks/{task_id}")


async def get_task_attachments(task_id: str) -> str:
    return await _fetch(f"https://taskei.amazon.dev/tasks/{task_id}?get-attachments=true")


async def get_retro(retro_id: str) -> str:
    return await _fetch(f"https://taskei.amazon.dev/retrospectives/{retro_id}")


# --- Tiny ---

async def resolve_tiny(shortlink: str) -> str:
    return await _fetch(f"https://tiny.amazon.com/{shortlink}")
