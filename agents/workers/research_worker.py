"""Research worker — internal websites, people lookup, web search."""

from strands import Agent, tool
from agents.base import run
from agents.workers import _model


def create(session_mgr=None):
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

    @tool
    def shared_context(operation: str = "read", key: str = "", value: str = "") -> str:
        """Read or post shared context visible to all workers.
        Args:
            operation: 'read' to get context, 'post' to share
            key: Context key
            value: Context value (for post)
        """
        from agents.workers import read_context, post_context
        if operation == "post" and key:
            post_context(key, value, source="research")
            return f"Posted to shared context: {key}"
        return read_context(key)

    @tool
    def instructai_query(question: str, agent: str = "") -> str:
        """Ask InstructAI a business question. ALWAYS specify an agent for faster, more reliable results.

        Available agents (REQUIRED — pick the best match):
        - partner_goals: Partner Attached Launched ARR, GenAI/ML partner attach, goal attainment
        - par_intelliagent: Partner Attributed Revenue (PAR) — Sell-With/Through/To models
        - business_context: Partner xBR/WBR talk tracks, 10-Blocker, 6-Blocker frameworks
        - prtnr_pipeline_agent: Partner pipeline KPI — AO/PO Launched ARR by sales hierarchy
        - pipeline_agent_spec: Current open/created/closed pipeline (ad-hoc, real-time)
        - pipeline_snapshot: Weekly pipeline changes (Sunday snapshots, WoW movement)
        - pipeline_narrative: Weekly leadership pipeline report (auto-generated prose)
        - asp_revenue_agent: GAAP sales revenue — product/sales hierarchy, YoY/QoQ/MoM
        - wwso_output_goals: WWSO specialist revenue & pipeline goal attainment (20+ domains)
        - mp_gss_revenue_agent: Marketplace GSS & listing fee revenue
        - mp_renewals_agent: Marketplace renewals & retention rates
        - mppo_agent: Marketplace Private Offers — TCV, GSS, NFR
        - funding_agent: Partner fund requests (APFP, SFDC, Approvals)
        - alfred: Pipeline risk — at-risk opportunities likely to stall/close lost
        - marco: Migration acceleration — stalled migrations, accelerator recommendations
        - postsales_migrations: Post-sales migration metrics (realized revenue, velocity)
        - sift: SIFT (Sales Inputs & Field Trends) analysis
        - apotech_psa_cont_arr: PSA Contributed ARR (launched + pipeline)
        - apotech_deswins_arr: PSA Design Wins ARR
        - apotech_deswins_tcv: PSA Design Wins Marketplace TCV

        Args:
            question: Business question (e.g. "What is GenAI partner attached LARR YTD?")
            agent: Agent ID from list above. ALWAYS specify one — auto-routing is slow and unreliable.
        """
        async def _fetch():
            from agents.base import instructai, MCP_CALL_TIMEOUT
            async with instructai() as session:
                # Override timeout for InstructAI — backend queries are slow
                session._timeout = max(session._timeout, 90)
                tool_name = f"InstructAI___{agent}" if agent else "InstructAI___question"
                result = await session.call_tool(tool_name, {"question": question})
                return result.content[0].text if result.content else "No response from InstructAI"
        return run(_fetch())

    @tool
    def instructai_agents() -> str:
        """List all available InstructAI agents and check your data access permissions."""
        async def _fetch():
            from agents.base import instructai
            async with instructai() as session:
                session._timeout = max(session._timeout, 90)
                # Get permissions first
                perms = ""
                try:
                    perm_result = await session.call_tool("InstructAI___get_permissions", {})
                    perms = perm_result.content[0].text if perm_result.content else ""
                except Exception:
                    pass
                # Then list agents
                result = await session.call_tool("InstructAI___list_agents", {})
                agents_text = result.content[0].text if result.content else "No agents found"
                if perms:
                    return f"## Your Permissions\n{perms}\n\n## Available Agents\n{agents_text}"
                return agents_text
        return run(_fetch())

    @tool
    def quicksight_query(question: str, topic_id: str = "") -> str:
        """Query Amazon QuickSight dashboards and topics using natural language.
        Use without topic_id to chat with the default assistant, or provide a topic_id for structured data queries.
        Args:
            question: Natural language question about data/dashboards
            topic_id: Optional Q Topic ID for structured queries (use quicksight_topics to find IDs)
        """
        async def _fetch():
            from agents.base import quicksight
            async with quicksight() as session:
                if topic_id:
                    result = await session.call_tool("query_topic", {"topicId": topic_id, "question": question})
                else:
                    result = await session.call_tool("chat", {"message": question})
                return result.content[0].text if result.content else "No response from QuickSight"
        return run(_fetch())

    @tool
    def quicksight_topics(search: str = "") -> str:
        """List available QuickSight Q Topics (queryable datasets). Use to find topic IDs for quicksight_query.
        Args:
            search: Optional filter by name/description
        """
        async def _fetch():
            from agents.base import quicksight
            async with quicksight() as session:
                args = {"search": search} if search else {}
                result = await session.call_tool("list_topics", args)
                return result.content[0].text if result.content else "No topics found"
        return run(_fetch())

    return Agent(
        model=_model("medium"),
        system_prompt="You are a research specialist. You look up people, Kingpin goals/projects/milestones (list, view, update, comment), wiki pages, Taskei tasks, Broadcast videos, resolve links, search the web, query business data via InstructAI, and query QuickSight dashboards/topics. Return data concisely. Use shared_context to post important findings for other workers.\n\nFor InstructAI, ALWAYS specify the agent parameter — never omit it. The auto-router is slow and unreliable. Pick the best match:\n- Revenue questions → asp_revenue_agent\n- Partner attach/goals → partner_goals\n- Partner revenue (PAR) → par_intelliagent\n- Partner pipeline → prtnr_pipeline_agent\n- Partner xBR/WBR prep → business_context\n- Current pipeline → pipeline_agent_spec\n- Pipeline week-over-week → pipeline_snapshot\n- Pipeline narrative report → pipeline_narrative\n- WWSO goals → wwso_output_goals\n- Marketplace GSS → mp_gss_revenue_agent\n- Marketplace renewals → mp_renewals_agent\n- Marketplace private offers → mppo_agent\n- Fund requests → funding_agent\n- Pipeline risk → alfred\n- Migrations → marco or postsales_migrations\n- SIFT field trends → sift\n- PSA/APOTech → apotech_psa_cont_arr, apotech_deswins_arr, apotech_deswins_tcv\nIf the question spans multiple domains, make separate calls to each relevant agent.",
        tools=[lookup_person, kingpin, kingpin_list, kingpin_update, kingpin_comment, kingpin_teams,
               wiki, taskei, broadcast, tiny, web_search, shared_context,
               instructai_query, instructai_agents, quicksight_query, quicksight_topics],
        callback_handler=None,
        **({"session_manager": session_mgr} if session_mgr else {}),
    )
