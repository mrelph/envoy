"""Worker agents — domain-specific Strands agents with focused toolsets.

The supervisor routes natural language requests to these workers.
Each worker has 5-8 tools and runs on an appropriate model tier.
"""

import os

_USER = os.environ.get('USER', '')


def _model(tier: str):
    """Lazy-construct a BedrockModel — avoids importing strands at module load."""
    from strands.models import BedrockModel
    from agents.base import model_for
    return BedrockModel(
        model_id=model_for(tier),
        region_name=os.environ.get("AWS_REGION", "us-west-2"),
    )


# --- Factory — lazy creation, cached instances ---

_workers = {}

WORKER_NAMES = ["email", "comms", "calendar", "productivity", "research", "sharepoint"]


def get_worker(name: str):
    """Get or create a worker agent by name."""
    if name not in _workers:
        from agents.workers.email_worker import create as _email
        from agents.workers.comms_worker import create as _comms
        from agents.workers.calendar_worker import create as _calendar
        from agents.workers.productivity_worker import create as _productivity
        from agents.workers.research_worker import create as _research
        from agents.workers.sharepoint_worker import create as _sharepoint
        factories = {
            "email": _email,
            "comms": _comms,
            "calendar": _calendar,
            "productivity": _productivity,
            "research": _research,
            "sharepoint": _sharepoint,
        }
        factory = factories.get(name)
        if not factory:
            raise ValueError(f"Unknown worker: {name}. Available: {list(factories.keys())}")
        _workers[name] = factory()
    return _workers[name]
