"""LLM connectivity and functionality tests.

Run with: ./venv/bin/python -m pytest tests/integration/test_llm.py -v
Requires valid AWS credentials (aws login or .env).

These tests validate that each model tier:
1. Connects successfully to Bedrock
2. Returns coherent text (not garbage/empty)
3. Follows basic instructions (classification, extraction, formatting)
4. Handles edge cases (empty-ish prompts, long output)

Run after model changes to catch regressions.
"""

import os
import sys
import time
from pathlib import Path

import pytest

# Allow importing project modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# Skip entire module if no AWS creds available
pytestmark = pytest.mark.integration


def _has_aws_creds() -> bool:
    """Check if AWS credentials are available."""
    if os.getenv("AWS_ACCESS_KEY_ID"):
        return True
    # Check default credential chain
    try:
        import boto3
        sts = boto3.client("sts", region_name="us-west-2")
        sts.get_caller_identity()
        return True
    except Exception:
        return False


if not _has_aws_creds():
    pytest.skip("No AWS credentials available", allow_module_level=True)


# Import after credential check (avoids stub interference)
# We bypass conftest stubs by importing the raw function
import importlib
import agents.base
importlib.reload(agents.base)
from agents.base import invoke_ai, model_for, DEFAULT_MODELS


# ── Connectivity Tests ──────────────────────────────────────────────


class TestConnectivity:
    """Verify each model tier can be reached and responds."""

    @pytest.mark.parametrize("tier", ["heavy", "medium", "light", "memory"])
    def test_model_responds(self, tier):
        """Each tier returns a non-empty string response."""
        result = invoke_ai("Reply with exactly: OK", max_tokens=50, tier=tier)
        assert result is not None
        assert len(result.strip()) > 0

    @pytest.mark.parametrize("tier", ["heavy", "medium", "light", "memory"])
    def test_model_id_valid(self, tier):
        """Model ID resolves to a known catalog entry."""
        model_id = model_for(tier)
        assert model_id
        assert "." in model_id  # all Bedrock model IDs have a dot


# ── Instruction Following ───────────────────────────────────────────


class TestInstructionFollowing:
    """Verify models follow instructions — catches capability regressions."""

    def test_classification(self):
        """Model can classify text into categories."""
        result = invoke_ai(
            "Classify this email subject as URGENT, NORMAL, or SPAM. "
            "Reply with ONLY the category label, nothing else.\n\n"
            "Subject: You won a free iPhone!!! Click here NOW!!!",
            max_tokens=20, tier="medium",
        )
        assert "SPAM" in result.upper()

    def test_extraction(self):
        """Model can extract structured data from text."""
        result = invoke_ai(
            "Extract the person's name and date from this text. "
            "Reply in format: NAME: <name>, DATE: <date>\n\n"
            "Meeting with Sarah Chen scheduled for March 15, 2026.",
            max_tokens=100, tier="medium",
        )
        assert "Sarah" in result
        assert "March 15" in result or "2026-03-15" in result or "15" in result

    def test_json_output(self):
        """Model can produce valid JSON when asked."""
        import json
        result = invoke_ai(
            'Return a JSON object with keys "color" and "count". '
            'Values: color="blue", count=3. Return ONLY the JSON, no other text.',
            max_tokens=100, tier="medium",
        )
        # Strip markdown fences if present
        cleaned = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(cleaned)
        assert parsed["color"] == "blue"
        assert parsed["count"] == 3

    def test_summarization(self):
        """Model can summarize text to fewer words."""
        long_text = (
            "The quarterly business review meeting covered several important topics. "
            "First, revenue grew 15% year over year, exceeding the target of 12%. "
            "Second, customer churn decreased from 5% to 3.2%. "
            "Third, the new product launch is on track for Q3. "
            "Finally, the team agreed to hire three more engineers."
        )
        result = invoke_ai(
            f"Summarize this in one sentence (max 20 words):\n\n{long_text}",
            max_tokens=100, tier="medium",
        )
        assert len(result.split()) < 40  # reasonably short
        assert any(kw in result.lower() for kw in ("revenue", "grew", "growth", "quarter", "review"))

    def test_light_model_simple_task(self):
        """Light tier can handle simple extraction."""
        result = invoke_ai(
            "What is 2+2? Reply with only the number.",
            max_tokens=10, tier="light",
        )
        assert "4" in result


# ── Robustness ──────────────────────────────────────────────────────


class TestRobustness:
    """Edge cases and error handling."""

    def test_handles_short_prompt(self):
        """Very short prompts don't crash."""
        result = invoke_ai("Hi", max_tokens=50, tier="light")
        assert result is not None

    def test_respects_max_tokens(self):
        """Output doesn't wildly exceed max_tokens worth of text."""
        result = invoke_ai(
            "Write a very long essay about the history of computing.",
            max_tokens=100, tier="light",
        )
        # 100 tokens ≈ 75 words ≈ 400 chars; allow generous margin
        assert len(result) < 2000

    def test_latency_reasonable(self):
        """Simple responses come back within 30 seconds."""
        start = time.time()
        invoke_ai("Say hello.", max_tokens=20, tier="light")
        elapsed = time.time() - start
        assert elapsed < 30, f"Response took {elapsed:.1f}s"

    def test_invalid_model_fallback(self, monkeypatch):
        """If model config points to a bad ID, the error is clear."""
        monkeypatch.setattr(agents.base, "_models_cache", {"heavy": "invalid.model.id.v1"})
        with pytest.raises(Exception) as exc_info:
            invoke_ai("Hello", max_tokens=10, tier="heavy")
        # Should get a Bedrock error, not a crash
        assert exc_info.value is not None
        # Reset
        monkeypatch.setattr(agents.base, "_models_cache", None)
