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
from agents.paths import SESSIONS_DIR as _ENVOY_SESSIONS_DIR, process_file
_SESSIONS_DIR = _ENVOY_SESSIONS_DIR / "workers"

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

# Set by _model() each time it constructs a BedrockModel, so _import_create
# can learn which model_id a worker's create() picked (every worker calls
# _model() exactly once) without threading it through create()'s signature
# or introspecting the (possibly mocked) Agent/model objects afterward.
# threading.local so concurrent worker construction on different threads
# can't stomp on each other.
_last_model_id = threading.local()


def _model(tier: str):
    """Lazy-construct a BedrockModel — avoids importing strands at module load."""
    from strands.models import BedrockModel
    from agents.base import model_for
    model_id = model_for(tier)
    _last_model_id.value = model_id
    return BedrockModel(
        model_id=model_id,
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
    )


def _supports_prompt_caching(model_id: str) -> bool:
    """Bedrock prompt caching is only supported on Claude and Nova model families.

    Mirrors agent.py's `_supports_prompt_caching` (agent.py:298-300). Kept as a
    local copy rather than imported: agent.py imports tools.py, which imports
    agents.workers, so agents.workers -> agent.py would be a circular import.
    """
    return "anthropic.claude" in model_id or "amazon.nova" in model_id


def _system_prompt_for_model(text: str, model_id: str):
    """Wrap the system prompt in a cachePoint block when the model supports caching.

    Mirrors agent.py's `_system_prompt_for_model` (agent.py:303-319) — same
    eligibility check, same block structure. Returns either a plain string (no
    caching) or a list of SystemContentBlock items with a trailing cachePoint
    marker, telling Bedrock to cache everything before it.
    """
    if not _supports_prompt_caching(model_id):
        return text
    try:
        from strands.types.content import SystemContentBlock
    except ImportError:
        return text
    return [
        SystemContentBlock(text=text),
        SystemContentBlock(cachePoint={"type": "default"}),
    ]


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
        # Always evict entries older than 30 min, then hard-cap at 50 entries
        # (oldest-first) so a burst of fresh posts can't grow the bus forever.
        cutoff = time.monotonic() - 1800
        stale = [k for k, v in _bus.items() if v["ts"] < cutoff]
        for k in stale:
            del _bus[k]
        if len(_bus) > 50:
            overflow = len(_bus) - 50
            oldest = sorted(_bus.items(), key=lambda kv: kv[1]["ts"])[:overflow]
            for k, _ in oldest:
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

WORKER_NAMES = ["email", "comms", "calendar", "productivity", "research", "sharepoint"]


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
    path = process_file()
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
    """
    factories = {
        "email": lambda: _import_create("email_worker", name),
        "comms": lambda: _import_create("comms_worker", name),
        "calendar": lambda: _import_create("calendar_worker", name),
        "productivity": lambda: _import_create("productivity_worker", name),
        "research": lambda: _import_create("research_worker", name),
        "sharepoint": lambda: _import_create("sharepoint_worker", name),
    }
    factory = factories.get(name)
    if not factory:
        raise ValueError(f"Unknown worker: {name}. Available: {list(factories.keys())}")

    # Pre-flight: if the on-disk session is bloated, reset before constructing
    if name not in _workers and _session_is_bloated(name):
        reset_worker_session(name)

    if name not in _workers:
        _workers[name] = factory()
    return _workers[name]


def _import_create(module_name: str, worker_name: str):
    """Import a worker module and call its create() with session manager.

    The final prompt is assembled in two ordered steps:
    1. Build the full prompt *text* — base prompt + any appended process.md
       sections — via plain string concatenation.
    2. Only once that's final, wrap it in cachePoint block form (a list of
       SystemContentBlock items) if the worker's model supports prompt
       caching. Wrapping has to be the last step: block form is a list, not
       a str, so appending more text after wrapping would break.
    """
    import importlib
    mod = importlib.import_module(f"agents.workers.{module_name}")
    agent = mod.create(session_mgr=_session_manager(worker_name))

    if hasattr(agent, 'system_prompt') and isinstance(agent.system_prompt, str):
        # Inject relevant process.md rules into the worker's system prompt
        rules = _load_process_rules(mod)
        full_prompt = agent.system_prompt + rules if rules else agent.system_prompt

        # _model() (called inside mod.create() above) recorded which model_id
        # this worker was built with — use it to decide cache eligibility.
        model_id = getattr(_last_model_id, "value", None)
        if model_id:
            agent.system_prompt = _system_prompt_for_model(full_prompt, model_id)
        else:
            agent.system_prompt = full_prompt

    return agent
