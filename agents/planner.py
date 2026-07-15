"""Planning agent — decomposes complex requests into structured execution plans.

The planner is a lightweight LLM call (Haiku/Nova) that:
1. Analyzes the user request
2. Determines which workers/tools are needed
3. Identifies dependencies between steps
4. Outputs a JSON plan

The plan executor then runs steps in parallel where possible,
sequential where dependencies exist.
"""

import json
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from agents.base import invoke_ai, run
from agents.workers import WORKER_DESCRIPTIONS, get_worker


def _emit(label: str):
    """Emit progress step to TUI."""
    try:
        from agent import emit_step
        emit_step(label)
    except Exception:
        pass

# Workers available for planning
_AVAILABLE_WORKERS = {k: v for k, v in WORKER_DESCRIPTIONS.items() if k != "coding"}

# Tools that run on the supervisor (not workers)
_SUPERVISOR_TOOLS = {
    "gather": "Parallel multi-source data fetch (email, slack, calendar, todos, team, bosses)",
    "commitment_tracker": "Scan sent emails/Slack for promises and commitments you made",
    "follow_up_tracker": "Find sent emails that haven't received replies",
    "calendar_audit": "Analyze meeting load and focus time",
    "response_time_tracker": "Analyze email response patterns",
    "meeting_prep": "Prep brief for an upcoming meeting",
    "one_on_one_prep": "Prep brief for a 1:1 with a specific person",
    "lookup_person": "Phonetool profile lookup",
    "search_emails": "Targeted email search by query",
}

_PLAN_TIMEOUT = 10  # seconds — planner should be fast (Haiku/Nova)
_STEP_TIMEOUT = 60  # seconds per step execution


def needs_planning(query: str) -> bool:
    """Heuristic: does this query need multi-step planning, or is it simple enough to route directly?
    
    Returns True for complex multi-domain requests, False for simple ones.
    """
    query_lower = query.lower()
    
    # Simple queries — single domain, direct tool match
    simple_patterns = [
        # Direct commands
        query_lower.startswith("/"),
        # Single-source lookups
        "who is" in query_lower and len(query_lower) < 50,
        "look up" in query_lower and len(query_lower) < 50,
        # Simple greetings / acknowledgements
        len(query_lower.split()) <= 4 and not any(w in query_lower for w in ("plan", "prep", "brief", "catch", "week", "commit")),
        # Explicit tool triggers
        any(query_lower.startswith(p) for p in ("send ", "reply ", "book ", "schedule ", "search ")),
    ]
    if any(simple_patterns):
        return False
    
    # Complex indicators — multiple domains or synthesis needed
    complex_indicators = [
        "what to work on",
        "what should i focus",
        "priorities",
        "catch up",
        "catch-up",
        "brief me",
        "briefing",
        "week ahead",
        "this week",
        "commitments",
        "what did i promise",
        "prepare for",
        "prep for",
        "status update",
        "what's happening",
        "what happened",
        "summary",
        "digest",
    ]
    
    if any(ind in query_lower for ind in complex_indicators):
        return True
    
    # Word count heuristic — long questions often need planning
    if len(query_lower.split()) > 15:
        return True
    
    return False


def generate_plan(query: str) -> Optional[list]:
    """Generate an execution plan for a complex query.
    
    Returns a list of steps:
    [
        {"id": "1", "tool": "gather", "request": "...", "depends_on": []},
        {"id": "2", "tool": "email_worker", "request": "...", "depends_on": ["1"]},
    ]
    
    Returns None if planning fails (caller should fall back to direct execution).
    """
    available = "\n".join(f"- {k}: {v}" for k, v in {**_SUPERVISOR_TOOLS, **_AVAILABLE_WORKERS}.items())
    
    prompt = f"""You are a planning agent. Decompose this request into 2-5 execution steps.

Available tools:
{available}

Rules:
- Use "gather" for multi-source fetches (fastest — parallel internally)
- Use specific workers only when gather won't suffice (e.g., sending, searching specific terms)
- Steps with no depends_on run in parallel
- Keep it minimal — fewer steps is better
- Each step's "request" should be a clear, self-contained instruction

User request: "{query}"

Respond with ONLY valid JSON — an array of step objects:
[{{"id": "1", "tool": "gather", "request": "fetch calendar, todos, email for this week", "depends_on": []}}, ...]"""

    try:
        result = invoke_ai(prompt, max_tokens=1000, tier="light")
        # Extract JSON from response (handle markdown code blocks)
        text = result.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        plan = json.loads(text)
        if isinstance(plan, list) and len(plan) > 0:
            return plan
    except (json.JSONDecodeError, Exception):
        pass
    return None


def execute_plan(plan: list) -> dict:
    """Execute a plan — parallel where no deps, sequential where deps exist.
    
    Returns {step_id: result_string} for all steps.
    """
    results = {}
    completed = set()
    
    def _run_step(step):
        """Execute a single plan step."""
        tool = step["tool"]
        request = step["request"]
        
        # Emit progress
        _TOOL_LABELS = {
            "gather": "📊 Gathering data", "email": "📧 Email", "comms": "💬 Slack",
            "calendar": "📅 Calendar", "productivity": "✅ Tasks",
            "research": "🔎 Research", "sharepoint": "📁 SharePoint",
            "commitment_tracker": "📬 Commitments", "follow_up_tracker": "📬 Follow-ups",
            "calendar_audit": "📊 Calendar audit", "meeting_prep": "🧩 Meeting prep",
        }
        _emit(_TOOL_LABELS.get(tool, f"⚙️ {tool}"))
        
        try:
            if tool == "gather":
                from supervisor import gather_data
                # Parse sources from request
                sources = _infer_gather_sources(request)
                return gather_data(sources=sources, days=7)
            elif tool in _SUPERVISOR_TOOLS:
                # Call supervisor tool directly
                return _call_supervisor_tool(tool, request)
            elif tool in _AVAILABLE_WORKERS:
                # Delegate to worker
                worker = get_worker(tool)
                result = worker(request)
                response = str(result.message) if hasattr(result, 'message') else str(result)
                return response[:5000]
            else:
                return f"Unknown tool: {tool}"
        except Exception as e:
            return f"⚠️ Step failed: {e}"
    
    # Group steps by dependency level
    remaining = list(plan)
    
    while remaining:
        # Find steps whose dependencies are all satisfied
        ready = [s for s in remaining if all(d in completed for d in s.get("depends_on", []))]
        
        if not ready:
            # Deadlock — deps can't be satisfied
            for s in remaining:
                results[s["id"]] = "⚠️ Skipped — dependency not met"
            break
        
        # Execute ready steps in parallel
        if len(ready) == 1:
            step = ready[0]
            results[step["id"]] = _run_step(step)
            completed.add(step["id"])
        else:
            with ThreadPoolExecutor(max_workers=min(len(ready), 4)) as pool:
                futures = {pool.submit(_run_step, s): s for s in ready}
                for future in futures:
                    step = futures[future]
                    try:
                        results[step["id"]] = future.result(timeout=_STEP_TIMEOUT)
                    except Exception as e:
                        results[step["id"]] = f"⚠️ Step timed out: {e}"
                    completed.add(step["id"])
        
        remaining = [s for s in remaining if s["id"] not in completed]
    
    return results


def plan_and_execute(query: str) -> Optional[str]:
    """Full pipeline: plan → create workspace → execute → synthesize.
    
    Returns formatted results string, or None if planning failed.
    """
    from agents.workspace import create as create_workspace, get as get_workspace, synthesize, clear as clear_workspace

    _emit("📋 Planning…")
    plan = generate_plan(query)
    if not plan:
        return None

    _emit(f"📋 Plan: {len(plan)} steps")

    # Create a workspace for this request — workers can post structured findings
    create_workspace(query)

    results = execute_plan(plan)

    # Check if workers populated the workspace
    ws = get_workspace()
    if ws and not ws.is_empty:
        # Workers posted structured data — use synthesizer
        _emit("✨ Synthesizing…")
        output = synthesize(ws)
        clear_workspace()
        if output:
            _emit("💬 Composing response…")
            return output

    _emit("💬 Composing response…")

    # Fallback — format raw results (workers didn't use workspace)
    sections = []
    for step in plan:
        step_id = step["id"]
        result = results.get(step_id, "No result")
        if result and not result.startswith("⚠️ Skipped"):
            sections.append(f"### Step {step_id}: {step['tool']} — {step['request'][:100]}\n{result[:4000]}")

    clear_workspace()

    if not sections:
        return None

    return "\n\n---\n\n".join(sections)


# --- Helpers ---

def _infer_gather_sources(request: str) -> str:
    """Infer gather sources from a natural language request."""
    request_lower = request.lower()
    sources = []
    mapping = {
        "email": ["email", "inbox", "mail"],
        "slack": ["slack", "message", "dm", "channel"],
        "calendar": ["calendar", "meeting", "schedule", "event"],
        "todos": ["todo", "task", "to-do", "action"],
    }
    for source, keywords in mapping.items():
        if any(k in request_lower for k in keywords):
            sources.append(source)
    # Default to common sources if nothing matched
    return ",".join(sources) if sources else "email,slack,calendar,todos"


def _call_supervisor_tool(tool_name: str, request: str) -> str:
    """Call a supervisor-level tool by name."""
    import tools as _tools
    
    tool_map = {
        "commitment_tracker": lambda: _tools._with_timeout(_tools.wf.commitment_tracker, _tools._USER(), 7),
        "follow_up_tracker": lambda: _tools._with_timeout(_tools.wf.follow_up_tracker, _tools._USER(), 7),
        "calendar_audit": lambda: _tools._with_timeout(_tools.wf.calendar_audit, _tools._USER(), 5),
        "response_time_tracker": lambda: _tools._with_timeout(_tools.wf.response_time_tracker, _tools._USER(), 7),
        "meeting_prep": lambda: _tools._with_timeout(_tools.wf.meeting_prep, request, _tools._USER()),
        "one_on_one_prep": lambda: _tools._with_timeout(_tools.wf.one_on_one_prep, request, _tools._USER()),
        "lookup_person": lambda: _lookup_person(request),
        "search_emails": lambda: _search_emails(request),
    }
    
    fn = tool_map.get(tool_name)
    if fn:
        return fn()
    return f"Tool {tool_name} not mapped"


def _lookup_person(request: str) -> str:
    """Extract alias from request and look up."""
    # Simple extraction — take the last word as alias
    words = request.strip().split()
    alias = words[-1] if words else request
    from supervisor import lookup_person as _lp
    return _lp(alias)


def _search_emails(request: str) -> str:
    """Search emails with the request as query."""
    from supervisor import search_emails as _se
    return _se(request, days=7)
