"""Unit tests for agents/confirm.py — the code-level confirmation gate for
destructive worker actions (send/forward/delete email, Slack sends, ...).
"""

import pytest

from agents import confirm as confirm_mod
from agents.confirm import require_confirmation, set_user_turn, clear_pending


@pytest.fixture(autouse=True)
def _reset_confirm_state():
    """Module-level state persists across tests unless reset."""
    clear_pending()
    confirm_mod._state["user_turn"] = ""
    confirm_mod._state["user_turn_ts"] = 0.0
    yield
    clear_pending()


def test_first_call_returns_preview_not_none():
    result = require_confirmation("send email", "To: bob@example.com — Subject: Hi")
    assert result is not None
    assert "Confirmation required before send email" in result
    assert "To: bob@example.com — Subject: Hi" in result


def test_affirmative_short_turn_then_retry_allows():
    preview = require_confirmation("send email", "To: bob@example.com — Subject: Hi")
    assert preview is not None

    set_user_turn("yes")

    result = require_confirmation("send email", "To: bob@example.com — Subject: Hi")
    assert result is None


@pytest.mark.parametrize("affirmative", ["y", "Yes", "confirm", "confirmed", "go ahead",
                                          "do it", "send it", "proceed", "approve",
                                          "ok", "okay", "Yes!", "\"ok\"", " ok. "])
def test_various_affirmative_phrasings_allow(affirmative):
    require_confirmation("delete", "conversation 123")
    set_user_turn(affirmative)
    assert require_confirmation("delete", "conversation 123") is None


def test_long_message_containing_ok_does_not_confirm():
    require_confirmation("send email", "To: bob@example.com — Subject: Hi")

    long_msg = ("ok, that email thread has been resolved, please continue "
                "with the other tasks on my list for today")
    assert len(long_msg) > 60
    set_user_turn(long_msg)

    result = require_confirmation("send email", "To: bob@example.com — Subject: Hi")
    assert result is not None  # still requires confirmation — not fooled by "ok"


def test_non_affirmative_new_turn_clears_pending():
    require_confirmation("delete", "conversation 123")

    # User moves on to something unrelated instead of confirming.
    set_user_turn("actually, what's on my calendar tomorrow?")

    # A later "yes" no longer confirms the old, now-cleared pending action.
    set_user_turn("yes")
    result = require_confirmation("delete", "conversation 123")
    # Because the pending action was dropped, this call re-registers it
    # (a fresh preview) rather than allowing — the stale "yes" doesn't apply
    # to an action that was never re-requested after the user moved on.
    assert result is not None


def test_pending_expires_after_ttl(monkeypatch):
    require_confirmation("send email", "To: bob@example.com — Subject: Hi")

    t0 = confirm_mod._now()
    monkeypatch.setattr(confirm_mod, "_now", lambda: t0 + confirm_mod._PENDING_TTL_SECONDS + 1)

    set_user_turn("yes")  # arrives after expiry
    result = require_confirmation("send email", "To: bob@example.com — Subject: Hi")
    assert result is not None  # expired — requires confirmation again


def test_different_kind_does_not_confirm():
    require_confirmation("send email", "To: bob@example.com — Subject: Hi")
    set_user_turn("yes")
    # A different kind of destructive action was never previewed/confirmed.
    result = require_confirmation("delete", "conversation 123")
    assert result is not None


def test_clear_pending_resets_state():
    require_confirmation("send email", "To: bob@example.com — Subject: Hi")
    clear_pending()
    set_user_turn("yes")
    result = require_confirmation("send email", "To: bob@example.com — Subject: Hi")
    assert result is not None
