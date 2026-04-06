"""Internal websites agent — Kingpin, Broadcast, Meetings, Wiki, Taskei, Tiny via builder-mcp + kingpin-mcp."""

import asyncio
from agents.base import builder, kingpin as kingpin_session


async def _fetch(url: str) -> str:
    async with builder() as session:
        result = await session.call_tool("ReadInternalWebsites", {"inputs": [url]})
        return result.content[0].text if result.content else "No result."


async def _fetch_many(urls: list) -> str:
    async with builder() as session:
        result = await session.call_tool("ReadInternalWebsites", {"inputs": urls})
        return result.content[0].text if result.content else "No result."


# --- Kingpin (direct MCP) ---

def _kp_text(result) -> str:
    return result.content[0].text if result.content else "No result."


async def get_goal(goal_id: str) -> str:
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("get_goal", {"goal_id": goal_id}))


async def get_goal_children(goal_id: str) -> str:
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("get_relationships", {"goal_id": goal_id}))


async def list_goals(owner: str = None, team_id: str = None, year: int = None,
                     status: str = None, tags_any: list = None, limit: int = 100) -> str:
    args = {}
    if owner: args["owner"] = owner
    if team_id: args["team_id"] = team_id
    if year: args["year"] = year
    if status: args["status"] = status
    if tags_any: args["tags_any"] = tags_any
    if limit != 100: args["limit"] = limit
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("list_goals", args))


async def list_projects(owner: str = None, team_id: str = None, year: int = None,
                        status: str = None, limit: int = 100) -> str:
    args = {}
    if owner: args["owner"] = owner
    if team_id: args["team_id"] = team_id
    if year: args["year"] = year
    if status: args["status"] = status
    if limit != 100: args["limit"] = limit
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("list_projects", args))


async def list_milestones(owner: str = None, team_id: str = None, year: int = None,
                          status: str = None, limit: int = 100) -> str:
    args = {}
    if owner: args["owner"] = owner
    if team_id: args["team_id"] = team_id
    if year: args["year"] = year
    if status: args["status"] = status
    if limit != 100: args["limit"] = limit
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("list_milestones", args))


async def update_goal(goal_id: str, **kwargs) -> str:
    args = {"goal_id": goal_id, **kwargs}
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("update_goal", args))


async def add_comment(goal_id: str, message: str) -> str:
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("add_comment", {"goal_id": goal_id, "message": message}))


async def list_teams() -> str:
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("list_teams", {}))


async def get_goal_history(goal_id: str, fields: list = None) -> str:
    args = {"goal_id": goal_id}
    if fields: args["fields"] = fields
    async with kingpin_session() as s:
        return _kp_text(await s.call_tool("get_goal_history", args))


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
