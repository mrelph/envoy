"""Worker agents — domain-specific Strands agents with focused toolsets.

The supervisor routes natural language requests to these workers.
Each worker has 5-8 tools and runs on an appropriate model tier.
Workers have session persistence and share context via a bus.
"""

import os
import threading
from pathlib import Path

from agents.base import current_user as _USER  # call-time alias resolution
_SESSIONS_DIR = Path.home() / ".envoy" / "sessions" / "workers"


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

WORKER_NAMES = ["email", "comms", "calendar", "productivity", "research", "sharepoint", "coding"]


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
    """Get or create a worker agent by name."""
    if name not in _workers:
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
        _workers[name] = factory()
    return _workers[name]


def _import_create(module_name: str, worker_name: str):
    """Import a worker module and call its create() with session manager."""
    import importlib
    mod = importlib.import_module(f"agents.workers.{module_name}")
    agent = mod.create(session_mgr=_session_manager(worker_name))
    # Inject relevant process.md rules into the worker's system prompt
    rules = _load_process_rules(mod)
    if rules and hasattr(agent, 'system_prompt') and isinstance(agent.system_prompt, str):
        agent.system_prompt = agent.system_prompt + rules
    return agent
