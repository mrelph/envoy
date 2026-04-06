"""Research worker — internal websites, people lookup, web search."""

from strands import Agent, tool
from agents.base import run
from agents.workers import _model


def create():
    from agents import internal

    @tool
    def lookup_person(alias: str) -> str:
        """Look up someone's Phonetool profile.
        Args:
            alias: Amazon login alias
        """
        async def _fetch():
            from agents.base import builder
            async with builder() as session:
                result = await session.call_tool("ReadInternalWebsites",
                    {"inputs": [f"https://phonetool.amazon.com/users/{alias}"]})
                return result.content[0].text if result.content else f"No profile for {alias}"
        return run(_fetch())

    @tool
    def kingpin(goal_id: str, children: bool = False) -> str:
        """Look up a Kingpin goal/project/milestone by ID. Set children=True to see relationships.
        Args:
            goal_id: Kingpin goal ID (GUID or KPID number)
            children: Also fetch child relationships
        """
        result = run(internal.get_goal(goal_id))
        if children:
            result += "\n\n## Relationships\n" + run(internal.get_goal_children(goal_id))
        return result

    @tool
    def kingpin_list(item_type: str = "goals", owner: str = "", team_id: str = "",
                     year: int = 0, status: str = "", limit: int = 50) -> str:
        """List Kingpin items by type with optional filters.
        Args:
            item_type: "goals", "projects", or "milestones"
            owner: Filter by owner alias (e.g. "markrelp")
            team_id: Filter by team GUID
            year: Filter by target year (e.g. 2026)
            status: Filter by status (Green, Yellow, Red, Completed, etc.)
            limit: Max results (default 50)
        """
        fn = {"goals": internal.list_goals, "projects": internal.list_projects,
              "milestones": internal.list_milestones}.get(item_type, internal.list_goals)
        kwargs = {}
        if owner: kwargs["owner"] = owner
        if team_id: kwargs["team_id"] = team_id
        if year: kwargs["year"] = year
        if status: kwargs["status"] = status
        if limit != 50: kwargs["limit"] = limit
        return run(fn(**kwargs))

    @tool
    def kingpin_update(goal_id: str, status: str = "", status_comments: str = "",
                       progress: int = -1) -> str:
        """Update a Kingpin goal's status, comments, or progress.
        Args:
            goal_id: Kingpin goal ID
            status: New status (Green, Yellow, Red, Completed, etc.)
            status_comments: Status update text
            progress: Percentage complete 0-100 (-1 to skip)
        """
        kwargs = {}
        if status: kwargs["status"] = status
        if status_comments: kwargs["status_comments"] = status_comments
        if progress >= 0: kwargs["progress"] = progress
        if not kwargs:
            return "No updates specified. Provide status, status_comments, or progress."
        return run(internal.update_goal(goal_id, **kwargs))

    @tool
    def kingpin_comment(goal_id: str, message: str) -> str:
        """Add a comment to a Kingpin goal.
        Args:
            goal_id: Kingpin goal ID
            message: Comment text
        """
        return run(internal.add_comment(goal_id, message))

    @tool
    def kingpin_teams() -> str:
        """List your active Kingpin teams. Returns team names and UUIDs."""
        return run(internal.list_teams())

    @tool
    def wiki(path: str) -> str:
        """Read an internal Wiki page.
        Args:
            path: Wiki path after /bin/view/
        """
        return run(internal.get_wiki(path))

    @tool
    def taskei(task_id: str) -> str:
        """Look up a Taskei/SIM task.
        Args:
            task_id: Task ID like XYZ-1234
        """
        return run(internal.get_task(task_id))

    @tool
    def broadcast(query: str) -> str:
        """Search internal Broadcast videos.
        Args:
            query: Search terms
        """
        return run(internal.search_broadcast(query))

    @tool
    def tiny(shortlink: str) -> str:
        """Resolve a tiny.amazon.com shortlink.
        Args:
            shortlink: The shortlink code
        """
        return run(internal.resolve_tiny(shortlink))

    @tool
    def web_search(query: str, count: int = 5) -> str:
        """Search the web using Brave Search. Use for external/public information.
        Args:
            query: Search query
            count: Number of results (default 5, max 20)
        """
        import os, requests as req
        api_key = os.environ.get("BRAVE_API_KEY", "")
        if not api_key:
            return "BRAVE_API_KEY not set. Add it to ~/.envoy/.env or your environment."
        resp = req.get("https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": min(count, 20)}, timeout=10)
        resp.raise_for_status()
        results = resp.json().get("web", {}).get("results", [])
        if not results:
            return f"No results for: {query}"
        return "\n\n".join(
            f"**{r['title']}**\n{r.get('description', '')}\n{r['url']}"
            for r in results
        )

    return Agent(
        model=_model("medium"),
        system_prompt="You are a research specialist. You look up people, Kingpin goals/projects/milestones (list, view, update, comment), wiki pages, Taskei tasks, Broadcast videos, resolve links, and search the web. Return data concisely.",
        tools=[lookup_person, kingpin, kingpin_list, kingpin_update, kingpin_comment, kingpin_teams,
               wiki, taskei, broadcast, tiny, web_search],
        callback_handler=None,
    )
