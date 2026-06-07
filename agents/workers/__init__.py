"""Worker agents — domain-specific Strands agents with focused toolsets.

The supervisor routes natural language requests to these workers.
Each worker has 5-8 tools and runs on an appropriate model tier.
Workers have session persistence and share context via a bus.
"""

import os
import shutil
import threading
import time as _time
from pathlib import Path

from agents.base import current_user as _USER  # call-time alias resolution
_SESSIONS_DIR = Path.home() / ".envoy" / "sessions" / "workers"

# Worker sessions get unbounded — every supervisor call appends. We cap to keep
# replay latency sane: in production we saw email worker hit 74 messages and
# spend 80s replaying before answering. The supervisor passes the full request
# fresh each turn, so cross-day worker memory isn't load-bearing.
_MAX_SESSION_MESSAGES = 30
_MAX_SESSION_AGE_HOURS = 6

# Strands' FileSessionManager writes under base_dir, but in practice the SDK
# also uses /tmp/strands/sessions. Both are checked when resetting a worker.
_SESSION_DIRS = [
    str(_SESSIONS_DIR),
    "/tmp/strands/sessions",
]


def _model(tier: str):
    """Lazy-construct a BedrockModel — avoids importing strands at module load."""
    from strands.models import BedrockModel
    from agents.base import model_for
    return BedrockModel(
        model_id=model_for(tier),
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
    )


def _session_manager(worker_name: str):
    """Create a FileSessionManager for a worker so it retains conversation history."""
    from strands.session.file_session_manager import FileSessionManager
    _SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return FileSessionManager(
        session_id=f"worker-{worker_name}",
        base_dir=str(_SESSIONS_DIR),
    )


# ── Shared context bus — inter-agent communication ──────────────

_bus = {}           # key → {value, source, ts}
_bus_lock = threading.RLock()


def post_context(key: str, value: str, source: str = ""):
    """Post a piece of context that other workers can read.

    Args:
        key: Topic key (e.g. "urgent_emails", "calendar_conflicts", "person:alias")
        value: The context data
        source: Which worker posted it
    """
    import time
    with _bus_lock:
        _bus[key] = {"value": value, "source": source, "ts": time.monotonic()}
        # Evict entries older than 30 min or if bus exceeds 50 entries
        cutoff = time.monotonic() - 1800
        if len(_bus) > 50:
            stale = [k for k, v in _bus.items() if v["ts"] < cutoff]
            for k in stale:
                del _bus[k]


def read_context(key: str = "") -> str:
    """Read context from the bus.

    Args:
        key: Specific key to read, or empty to get all keys + summaries.
    """
    with _bus_lock:
        if key:
            entry = _bus.get(key)
            if not entry:
                return ""
            return entry["value"]
        if not _bus:
            return ""
        lines = []
        for k, v in _bus.items():
            preview = v["value"][:200].replace("\n", " ")
            lines.append(f"- **{k}** (from {v['source']}): {preview}")
        return "\n".join(lines)


def clear_bus():
    """Clear all shared context."""
    with _bus_lock:
        _bus.clear()


# ── Factory — lazy creation, cached instances ───────────────────

_workers = {}
_worker_locks = {}  # per-worker locks to serialize concurrent calls

WORKER_NAMES = ["email", "comms", "calendar", "productivity", "research", "sharepoint", "coding"]


def _session_message_dirs(worker_name: str) -> list:
    """Find every messages/ dir on disk for this worker, across both base dirs."""
    found = []
    for base in _SESSION_DIRS:
        sess_root = Path(base) / f"session_worker-{worker_name}"
        if sess_root.is_dir():
            for msgs in sess_root.rglob("messages"):
                if msgs.is_dir():
                    found.append(msgs)
    return found


def _session_is_bloated(worker_name: str) -> bool:
    """True if a worker's session has too many messages or is stale."""
    msg_dirs = _session_message_dirs(worker_name)
    if not msg_dirs:
        return False
    total = 0
    newest_mtime = 0.0
    for d in msg_dirs:
        for m in d.iterdir():
            if m.is_file():
                total += 1
                mt = m.stat().st_mtime
                if mt > newest_mtime:
                    newest_mtime = mt
    if total >= _MAX_SESSION_MESSAGES:
        return True
    if newest_mtime and (_time.time() - newest_mtime) > _MAX_SESSION_AGE_HOURS * 3600:
        return True
    return False


def reset_worker_session(worker_name: str) -> None:
    """Wipe a worker's on-disk session and drop the cached agent instance."""
    for base in _SESSION_DIRS:
        sess_dir = Path(base) / f"session_worker-{worker_name}"
        if sess_dir.is_dir():
            shutil.rmtree(sess_dir, ignore_errors=True)
    _workers.pop(worker_name, None)


def _worker_sections(module) -> list:
    """Pull RELEVANT_SECTIONS off a worker module, with a safe fallback."""
    sections = getattr(module, "RELEVANT_SECTIONS", None)
    return list(sections) if isinstance(sections, (list, tuple)) else []


def _load_process_rules(worker_module) -> str:
    """Load relevant process.md sections for a worker's system prompt.

    Section list is declared on each worker module as RELEVANT_SECTIONS so
    new workers only need to edit their own file.
    """
    path = Path.home() / ".envoy" / "process.md"
    if not path.exists():
        return ""
    sections = _worker_sections(worker_module)
    if not sections:
        return ""
    content = path.read_text()
    rules = []
    for section_name in sections:
        header = f"## {section_name}"
        if header not in content:
            continue
        # Extract lines between this header and the next ## header
        start = content.index(header) + len(header)
        rest = content[start:]
        end = rest.find("\n## ")
        block = rest[:end] if end != -1 else rest
        # Collect non-empty, non-comment lines
        for line in block.splitlines():
            line = line.strip()
            if line and line.startswith("- ") and not line.startswith("<!-- "):
                rules.append(line)
    if not rules:
        return ""
    return "\n\nProcess rules (learned from user corrections):\n" + "\n".join(rules)


def get_worker(name: str):
    """Get or create a worker agent by name.

    If the on-disk session has accumulated past _MAX_SESSION_MESSAGES or sat
    idle past _MAX_SESSION_AGE_HOURS, wipe it before constructing the worker
    so we don't replay a giant prior conversation on every supervisor call.

    Returns a callable that serializes access via a per-worker lock to prevent
    "Agent is already processing a request" errors from concurrent tool calls.
    """
    factories = {
        "email": lambda: _import_create("email_worker", name),
        "comms": lambda: _import_create("comms_worker", name),
        "calendar": lambda: _import_create("calendar_worker", name),
        "productivity": lambda: _import_create("productivity_worker", name),
        "research": lambda: _import_create("research_worker", name),
        "sharepoint": lambda: _import_create("sharepoint_worker", name),
        "coding": lambda: _import_create("coding_worker", name),
    }
    factory = factories.get(name)
    if not factory:
        raise ValueError(f"Unknown worker: {name}. Available: {list(factories.keys())}")

    # Pre-flight: if the on-disk session is bloated, reset before constructing
    if name not in _workers and _session_is_bloated(name):
        reset_worker_session(name)

    if name not in _workers:
        _workers[name] = factory()

    if name not in _worker_locks:
        _worker_locks[name] = threading.Lock()

    agent = _workers[name]
    lock = _worker_locks[name]

    class _LockedWorker:
        """Serializes calls to a Strands worker agent."""
        def __call__(self, prompt):
            with lock:
                return agent(prompt)
        def __getattr__(self, attr):
            return getattr(agent, attr)

    return _LockedWorker()


def _import_create(module_name: str, worker_name: str):
    """Import a worker module and call its create() with session manager."""
    import importlib
    mod = importlib.import_module(f"agents.workers.{module_name}")
    agent = mod.create(session_mgr=_session_manager(worker_name))
    # Inject relevant process.md rules into the worker's system prompt
    rules = _load_process_rules(mod)
    if rules and hasattr(agent, 'system_prompt') and isinstance(agent.system_prompt, str):
        agent.system_prompt = agent.system_prompt + rules
    # Universal fail-fast rule for all workers
    if hasattr(agent, 'system_prompt') and isinstance(agent.system_prompt, str):
        agent.system_prompt += "\n\nCRITICAL: If a tool call times out or returns a connection error, do NOT retry it. Report what happened and return immediately. The user prefers a fast partial answer over waiting for retries that will also fail."
    # Inject delegate_to_worker tool for cross-worker collaboration
    if worker_name != "coding":  # coding worker runs in subprocess, delegation not useful
        try:
            delegate_tool = make_delegate_tool()
            agent.tool_registry.process_tools([delegate_tool])
            # Tell this worker about its siblings
            siblings = {k: v for k, v in WORKER_DESCRIPTIONS.items() if k != worker_name}
            sibling_list = "\n".join(f"  - {k}: {v}" for k, v in siblings.items())
            agent.system_prompt += f"\n\nYou can delegate to sibling workers via delegate_to_worker when you need data from another domain:\n{sibling_list}\nUse sparingly — only when the info would materially improve your answer."
        except Exception:
            pass
    return agent


# ── Worker-to-Worker Delegation ─────────────────────────────────

WORKER_DESCRIPTIONS = {
    "email": "Email specialist — inbox scan, search, send, reply, draft, cleanup, customer scan, team digest",
    "comms": "Slack & messaging — scan channels/DMs, send messages, search, reactions, EA delegation",
    "calendar": "Calendar management — view events, create meetings, find times, book rooms",
    "productivity": "Tasks & memory — to-do lists, tickets, persistent memory, cron jobs, briefings",
    "research": "Lookups — Phonetool profiles, Kingpin goals, Wiki, web search, InstructAI, QuickSight",
    "sharepoint": "Documents — SharePoint/OneDrive search, read, write, lists",
    "coding": "Development — write code, fix bugs, run tests, refactor, scripts",
}

# Thread-local depth counter prevents infinite delegation chains
_delegation_depth = threading.local()
_MAX_DELEGATION_DEPTH = 1  # workers can delegate once, but the callee cannot delegate further


def _get_depth() -> int:
    return getattr(_delegation_depth, 'depth', 0)


def _delegate_to_sibling(worker_name: str, request: str) -> str:
    """Internal delegation — called by the delegate_to_worker tool."""
    if worker_name not in WORKER_NAMES:
        return f"Unknown worker '{worker_name}'. Available: {', '.join(WORKER_NAMES)}"

    current_depth = _get_depth()
    if current_depth >= _MAX_DELEGATION_DEPTH:
        return f"Cannot delegate — max depth ({_MAX_DELEGATION_DEPTH}) reached. Answer with what you have."

    _delegation_depth.depth = current_depth + 1
    try:
        worker = get_worker(worker_name)
        result = worker(request)
        response = str(result.message) if hasattr(result, 'message') else str(result)
        return response[:3000]  # cap response size to avoid context bloat
    except Exception as e:
        return f"⚠️ {worker_name} unavailable: {e}"
    finally:
        _delegation_depth.depth = current_depth


def make_delegate_tool():
    """Create the delegate_to_worker @tool instance for injection into workers."""
    from strands import tool

    @tool
    def delegate_to_worker(worker_name: str, request: str) -> str:
        """Ask a sibling worker for help. Use when you need data from another domain.

        Available workers:
        - email: inbox, search, send, reply, classify
        - comms: Slack scan, send messages, search
        - calendar: view events, find times, create meetings
        - productivity: to-do lists, tickets, memory
        - research: Phonetool profiles, Kingpin goals, Wiki, web search
        - sharepoint: documents, files, lists

        Args:
            worker_name: Which worker to ask (email, comms, calendar, productivity, research, sharepoint)
            request: Natural language request for that worker
        """
        return _delegate_to_sibling(worker_name, request)

    return delegate_to_worker
