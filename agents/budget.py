"""Request budget — tracks wall time and AI token spend per user request.

Usage:
    budget = RequestBudget()
    budget.start()
    ...  # do work
    budget.record_ai_call(input_tokens=500, output_tokens=200, tier="medium")
    if budget.exceeded:
        return budget.warning_message()
"""

import time
from dataclasses import dataclass, field

# Defaults — can be overridden via config
MAX_WALL_SECONDS = 120      # 2 minutes per user request
MAX_AI_CALLS = 15           # max Bedrock invocations per request
WARN_WALL_SECONDS = 90      # warn at 75%
WARN_AI_CALLS = 10          # warn at 67%

# Approximate cost per 1K tokens (USD) by tier for awareness only
_COST_PER_1K = {
    "agent": 0.015, "heavy": 0.015,
    "medium": 0.003, "light": 0.001, "memory": 0.0002,
}


@dataclass
class RequestBudget:
    """Per-request budget tracker."""
    max_wall: float = MAX_WALL_SECONDS
    max_calls: int = MAX_AI_CALLS
    _start: float = 0.0
    _ai_calls: int = 0
    _input_tokens: int = 0
    _output_tokens: int = 0
    _est_cost_usd: float = 0.0
    _warned: bool = False

    def start(self):
        self._start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start if self._start else 0.0

    @property
    def exceeded(self) -> bool:
        return self.elapsed > self.max_wall or self._ai_calls > self.max_calls

    @property
    def should_warn(self) -> bool:
        if self._warned:
            return False
        return self.elapsed > WARN_WALL_SECONDS or self._ai_calls > WARN_AI_CALLS

    def record_ai_call(self, input_tokens: int = 0, output_tokens: int = 0, tier: str = "medium"):
        self._ai_calls += 1
        self._input_tokens += input_tokens
        self._output_tokens += output_tokens
        rate = _COST_PER_1K.get(tier, 0.003)
        self._est_cost_usd += (input_tokens + output_tokens) / 1000 * rate

    def warning_message(self) -> str:
        self._warned = True
        parts = []
        if self.elapsed > WARN_WALL_SECONDS:
            parts.append(f"{self.elapsed:.0f}s elapsed")
        if self._ai_calls > WARN_AI_CALLS:
            parts.append(f"{self._ai_calls} AI calls")
        return f"⚠️ Budget warning: {', '.join(parts)}. Wrapping up."

    def summary(self) -> str:
        if not self._ai_calls:
            return ""
        return (f"{self._ai_calls} AI calls, {self.elapsed:.1f}s, "
                f"~${self._est_cost_usd:.4f}")


# Per-request singleton (reset each turn)
_current: RequestBudget = None


def start_request() -> RequestBudget:
    global _current
    _current = RequestBudget()
    _current.start()
    return _current


def get_budget() -> RequestBudget:
    global _current
    if _current is None:
        _current = RequestBudget()
        _current.start()
    return _current
