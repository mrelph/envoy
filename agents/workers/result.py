"""Structured worker result envelope.

Workers return WorkerResult instead of raw strings. The supervisor can
inspect status/items without regex parsing, while str() still produces
the human-readable text for the LLM.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class WorkerResult:
    """Envelope returned by worker tool functions."""
    status: str = "ok"          # ok, empty, error
    text: str = ""              # Human-readable output (what the LLM sees)
    items: List[Dict] = field(default_factory=list)  # Structured items for indexing
    error: str = ""             # Error message if status == "error"

    def __str__(self):
        if self.status == "error":
            return f"⚠️ {self.error}" if self.error else "⚠️ Unknown error"
        return self.text or "(no output)"

    @classmethod
    def ok(cls, text: str, items: List[Dict] = None) -> "WorkerResult":
        return cls(status="ok", text=text, items=items or [])

    @classmethod
    def empty(cls, text: str = "No results found.") -> "WorkerResult":
        return cls(status="empty", text=text)

    @classmethod
    def err(cls, error: str) -> "WorkerResult":
        return cls(status="error", error=error)
