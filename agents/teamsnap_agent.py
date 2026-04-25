"""TeamSnap agent — schedule, roster, availability, event details, contacts, announcements, RSVP."""

from agents.base import teamsnap


async def _call(tool: str, params: dict = {}) -> str:
    """Call a TeamSnap MCP tool and return the text result."""
    try:
        async with teamsnap() as session:
            result = await session.call_tool(tool, params)
            return result.content[0].text if result.content else ""
    except FileNotFoundError:
        return "TeamSnap MCP server not installed."


async def get_schedule(team_id: str = "", start_date: str = "", end_date: str = "") -> str:
    if not team_id:
        text = await _call("teamsnap_list_teams")
        return f"Available teams:\n{text}" if text and not text.startswith("TeamSnap MCP") else text or "No teams found."
    params = {"team_id": team_id}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return await _call("teamsnap_get_events", params) or "No events found."


async def get_roster(team_id: str) -> str:
    return await _call("teamsnap_get_roster", {"team_id": team_id}) or "No roster found."


async def get_availability(event_id: str) -> str:
    return await _call("teamsnap_get_availability", {"event_id": event_id}) or "No availability data."


async def get_event_detail(event_id: str) -> str:
    return await _call("teamsnap_get_event", {"event_id": event_id}) or "No event details."


async def get_location(event_id: str) -> str:
    return await _call("teamsnap_get_location", {"event_id": event_id}) or "No location data."


async def get_contacts(team_id: str = "", member_id: str = "") -> str:
    params = {}
    if member_id:
        params["member_id"] = member_id
    elif team_id:
        params["team_id"] = team_id
    return await _call("teamsnap_get_contacts", params) or "No contacts found."


async def get_announcements(team_id: str, limit: int = 10) -> str:
    return await _call("teamsnap_get_announcements", {"team_id": team_id, "limit": limit}) or "No announcements."


async def set_availability(event_id: str, member_id: str, status: str) -> str:
    return await _call("teamsnap_set_availability", {
        "event_id": event_id, "member_id": member_id,
        "status": status, "preview": False,
    }) or "RSVP updated."


async def get_assignments(team_id: str = "", event_id: str = "") -> str:
    params = {}
    if event_id:
        params["event_id"] = event_id
    elif team_id:
        params["team_id"] = team_id
    return await _call("teamsnap_get_assignments", params) or "No assignments found."


async def get_standings(team_id: str) -> str:
    return await _call("teamsnap_get_results_and_standings", {"team_id": team_id}) or "No standings data."
