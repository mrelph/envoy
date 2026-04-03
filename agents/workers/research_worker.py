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
        """Look up a Kingpin goal. Set children=True to see child goals.
        Args:
            goal_id: Kingpin goal ID
            children: Also fetch child goals/milestones
        """
        result = run(internal.get_goal(goal_id))
        if children:
            result += "\n\n## Children\n" + run(internal.get_goal_children(goal_id))
        return result

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
        system_prompt="You are a research specialist. You look up people, Kingpin goals, wiki pages, Taskei tasks, Broadcast videos, resolve links, and search the web. Return data concisely.",
        tools=[lookup_person, kingpin, wiki, taskei, broadcast, tiny, web_search],
        callback_handler=None,
    )
