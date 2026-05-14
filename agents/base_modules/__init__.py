"""Base modules — focused sub-modules extracted from agents/base.py.

agents/base.py remains the canonical import path for backward compatibility.
New code can import directly from these focused modules:

    agents.base_modules.parsers  — email/todo response parsing
    agents.budget               — per-request latency/cost tracking
    agents.fetch                — shared data-fetch functions (single source of truth)
    agents.workers.result       — structured worker return envelope
"""
