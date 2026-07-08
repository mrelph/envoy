"""Unit tests for agents/watcher.py — per-channel Slack dedup.

watcher.py's own "already seen" logic (_check_slack) previously hashed the
*entire* combined unread payload: any single new message anywhere caused
the whole blob — including channels already reported on a prior tick — to
be re-announced. This aligns it with heartbeat.py's stable-ID dedup
approach by keying on the Slack channel id instead.
"""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest


@pytest.fixture
def watcher():
    import agents.watcher as watcher
    return watcher


def _fake_result(text):
    return SimpleNamespace(content=[SimpleNamespace(text=text)])


def _make_fake_slack(dm_text_seq, mention_text_seq):
    """Build a fake `slack()` async-context-manager factory.

    dm_text_seq / mention_text_seq: lists of response bodies, one consumed
    per call (last one repeats if the list is exhausted).
    """
    state = {"dm_i": 0, "mention_i": 0}

    class FakeSession:
        async def call_tool(self, name, arguments=None):
            assert name == "list_channels"
            types = arguments.get("channelTypes", [])
            if "dm" in types or "group_dm" in types:
                i = min(state["dm_i"], len(dm_text_seq) - 1)
                state["dm_i"] += 1
                return _fake_result(dm_text_seq[i])
            else:
                i = min(state["mention_i"], len(mention_text_seq) - 1)
                state["mention_i"] += 1
                return _fake_result(mention_text_seq[i])

    @asynccontextmanager
    async def _fake_slack():
        yield FakeSession()

    return _fake_slack


# ---------------------------------------------------------------------------
# _slack_channel_lines — the pure per-channel dedup helper
# ---------------------------------------------------------------------------

class TestSlackChannelLines:
    def test_first_sight_reports_all_channels(self, watcher):
        payload = json.dumps({"channels": [
            {"id": "C1", "name": "general", "last_read": "100"},
            {"id": "C2", "name": "random", "last_read": "200"},
        ]})
        seen, state = {}, {}
        lines = watcher._slack_channel_lines(payload, seen, "digest", state)
        assert len(lines) == 2
        assert any("general" in l for l in lines)
        assert any("random" in l for l in lines)

    def test_unchanged_channel_not_repeated(self, watcher):
        payload = json.dumps({"channels": [
            {"id": "C1", "name": "general", "last_read": "100"},
        ]})
        seen, state = {}, {}
        watcher._slack_channel_lines(payload, seen, "digest", state)
        lines = watcher._slack_channel_lines(payload, seen, "digest", state)
        assert lines == []

    def test_only_changed_channel_is_reported(self, watcher):
        seen, state = {}, {}
        first = json.dumps({"channels": [
            {"id": "C1", "name": "general", "last_read": "100"},
            {"id": "C2", "name": "random", "last_read": "200"},
        ]})
        watcher._slack_channel_lines(first, seen, "digest", state)

        second = json.dumps({"channels": [
            {"id": "C1", "name": "general", "last_read": "150"},  # changed
            {"id": "C2", "name": "random", "last_read": "200"},   # unchanged
        ]})
        lines = watcher._slack_channel_lines(second, seen, "digest", state)
        assert len(lines) == 1
        assert "general" in lines[0]

    def test_non_json_payload_falls_back_to_whole_blob_digest(self, watcher):
        seen, state = {}, {}
        text = "some free-form unread summary"
        first = watcher._slack_channel_lines(text, seen, "digest", state)
        assert first == [text]
        # Unchanged text on next tick — nothing new.
        second = watcher._slack_channel_lines(text, seen, "digest", state)
        assert second == []
        # Changed text — reported again.
        third = watcher._slack_channel_lines("different summary", seen, "digest", state)
        assert third == ["different summary"]

    def test_empty_payload_reports_nothing(self, watcher):
        seen, state = {}, {}
        assert watcher._slack_channel_lines("", seen, "digest", state) == []


# ---------------------------------------------------------------------------
# _check_slack — end-to-end through the fake slack() session
# ---------------------------------------------------------------------------

class TestCheckSlack:
    def test_new_message_in_one_channel_does_not_reannounce_others(self, watcher, monkeypatch):
        """The bug being fixed: a change in one channel used to cause the
        whole unread blob (including already-reported channels) to resend."""
        dm_round1 = json.dumps({"channels": [
            {"id": "D1", "name": "alice-dm", "last_read": "100"},
            {"id": "D2", "name": "bob-dm", "last_read": "200"},
        ]})
        dm_round2 = json.dumps({"channels": [
            {"id": "D1", "name": "alice-dm", "last_read": "999"},  # new message
            {"id": "D2", "name": "bob-dm", "last_read": "200"},    # unchanged
        ]})
        mentions = json.dumps({"channels": []})

        fake_slack = _make_fake_slack([dm_round1, dm_round2], [mentions, mentions])
        monkeypatch.setattr(watcher, "slack", fake_slack)

        state = {}
        first = asyncio.run(watcher._check_slack(state))
        assert "alice-dm" in first
        assert "bob-dm" in first

        second = asyncio.run(watcher._check_slack(state))
        assert "alice-dm" in second
        assert "bob-dm" not in second  # not re-announced

    def test_no_changes_returns_empty_string(self, watcher, monkeypatch):
        dm = json.dumps({"channels": [{"id": "D1", "name": "alice-dm", "last_read": "100"}]})
        mentions = json.dumps({"channels": []})
        fake_slack = _make_fake_slack([dm, dm], [mentions, mentions])
        monkeypatch.setattr(watcher, "slack", fake_slack)

        state = {}
        asyncio.run(watcher._check_slack(state))
        second = asyncio.run(watcher._check_slack(state))
        assert second == ""

    def test_slack_failure_returns_warning_string(self, watcher, monkeypatch):
        @asynccontextmanager
        async def _boom():
            raise RuntimeError("connection refused")
            yield  # pragma: no cover — never reached, makes this an async generator

        monkeypatch.setattr(watcher, "slack", _boom)
        result = asyncio.run(watcher._check_slack({}))
        assert "Slack check failed" in result

    def test_seen_channels_state_is_bounded(self, watcher, monkeypatch):
        channels = [{"id": f"C{i}", "name": f"chan{i}", "last_read": "1"} for i in range(600)]
        payload = json.dumps({"channels": channels})
        empty = json.dumps({"channels": []})
        fake_slack = _make_fake_slack([payload], [empty])
        monkeypatch.setattr(watcher, "slack", fake_slack)

        state = {}
        asyncio.run(watcher._check_slack(state))
        assert len(state["seen_channels"]) <= 500
