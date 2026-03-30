"""TeamSnap agent — auth, schedule, roster, availability."""

from agents.base import teamsnap


async def auth() -> str:
    try:
        async with teamsnap() as session:
            result = await session.call_tool("teamsnap_auth", {})
            return result.content[0].text if result.content else "Auth failed."
    except FileNotFoundError:
        return "TeamSnap MCP wrapper not found at ~/TeamSnapMCP/dist/wrapper.js"


async def get_schedule(team_id: str = "", start_date: str = "", end_date: str = "") -> str:
    try:
        async with teamsnap() as session:
            if not team_id:
                result = await session.call_tool("teamsnap_list_teams", {})
                return f"Available teams:\n{result.content[0].text}" if result.content else "No teams found."
            params = {"team_id": team_id}
            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date
            result = await session.call_tool("teamsnap_get_events", params)
            return result.content[0].text if result.content else "No events found."
    except FileNotFoundError:
        return "TeamSnap MCP server not installed."


async def get_roster(team_id: str) -> str:
    try:
        async with teamsnap() as session:
            result = await session.call_tool("teamsnap_get_roster", {"team_id": team_id})
            return result.content[0].text if result.content else "No roster found."
    except FileNotFoundError:
        return "TeamSnap MCP server not installed."


async def get_availability(event_id: str) -> str:
    try:
        async with teamsnap() as session:
            result = await session.call_tool("teamsnap_get_availability", {"event_id": event_id})
            return result.content[0].text if result.content else "No availability data."
    except FileNotFoundError:
        return "TeamSnap MCP server not installed."
