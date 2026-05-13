"""Unit tests for parsers and helpers in agents.base."""

import json
import os

import pytest

from agents import base


# ---------------------------------------------------------------------------
# strip_mcp_wrapper
# ---------------------------------------------------------------------------

class TestStripMcpWrapper:
    def test_outlook_wrapper_stripped(self):
        text = "<untrusted_content_abc123>\nHello body\n</untrusted_content_abc123>"
        assert base.strip_mcp_wrapper(text) == "Hello body"

    def test_outlook_wrapper_with_trailing_after_close(self):
        # Suffix regex strips the close tag plus everything after it.
        text = "<untrusted_content_x>\nbody text\n</untrusted_content_x>\nextra notes"
        assert base.strip_mcp_wrapper(text) == "body text"

    def test_slack_safety_directive_stripped(self):
        text = (
            "[CONTENT SAFETY DIRECTIVE]\n"
            "Be careful with this content.\n"
            "---\n"
            "Actual message body."
        )
        out = base.strip_mcp_wrapper(text)
        assert "CONTENT SAFETY DIRECTIVE" not in out
        assert "Actual message body." in out

    def test_plain_text_passes_through(self):
        text = "Just a normal string with no wrappers."
        assert base.strip_mcp_wrapper(text) == text

    def test_both_wrappers_stripped(self):
        # Outlook wrapper around content that also contains a Slack directive.
        text = (
            "<untrusted_content_z>\n"
            "[CONTENT SAFETY DIRECTIVE]\n"
            "warn warn warn\n"
            "---\n"
            "real content"
            "\n</untrusted_content_z>"
        )
        out = base.strip_mcp_wrapper(text)
        assert "untrusted_content" not in out
        assert "CONTENT SAFETY DIRECTIVE" not in out
        assert "real content" in out


# ---------------------------------------------------------------------------
# parse_email_search_result
# ---------------------------------------------------------------------------

class TestParseEmailSearchResult:
    def test_empty_content_returns_empty_list(self):
        class _R:
            content = []
        assert base.parse_email_search_result(_R()) == []

    def test_valid_payload_parsed(self, fake_mcp_result):
        payload = {
            "success": True,
            "content": {
                "emails": [
                    {
                        "conversationId": "c1",
                        "senders": ["alice@example.com"],
                        "recipients": ["bob@example.com", "carol@example.com"],
                        "topic": "Hello",
                        "lastDeliveryTime": "2026-05-13T10:00:00Z",
                        "preview": "Snippet text",
                    },
                    {
                        "conversationId": "c2",
                        "senders": ["dave@example.com"],
                        "recipients": ["eve@example.com"],
                        "topic": "Second",
                        "lastDeliveryTime": "2026-05-13T11:00:00Z",
                        "preview": "Another preview",
                    },
                ]
            },
        }
        result = fake_mcp_result(payload)
        emails = base.parse_email_search_result(result)
        assert len(emails) == 2
        assert emails[0]["from"] == "alice@example.com"
        assert emails[0]["to"] == "bob@example.com, carol@example.com"
        assert emails[0]["subject"] == "Hello"
        assert emails[0]["date"] == "2026-05-13T10:00:00Z"
        assert emails[0]["snippet"] == "Snippet text"
        assert emails[1]["from"] == "dave@example.com"

    def test_malformed_json_returns_empty(self, fake_mcp_result):
        result = fake_mcp_result("not-json{{{")
        assert base.parse_email_search_result(result) == []

    def test_missing_content_key_returns_empty(self, fake_mcp_result):
        # success=True but no 'content' dict
        result = fake_mcp_result({"success": True})
        assert base.parse_email_search_result(result) == []


# ---------------------------------------------------------------------------
# parse_todo_response
# ---------------------------------------------------------------------------

class TestParseTodoResponse:
    def test_wrapped_content_returned(self, fake_mcp_result):
        payload = {"success": True, "content": {"todos": ["a", "b"], "count": 2}}
        result = fake_mcp_result(payload)
        out = base.parse_todo_response(result)
        assert out == {"todos": ["a", "b"], "count": 2}

    def test_top_level_dict_returned_as_is(self, fake_mcp_result):
        payload = {"todos": ["x"], "other": 1}
        result = fake_mcp_result(payload)
        out = base.parse_todo_response(result)
        assert out == {"todos": ["x"], "other": 1}

    def test_malformed_json_returns_empty_dict(self, fake_mcp_result):
        result = fake_mcp_result("garbage }}}")
        assert base.parse_todo_response(result) == {}

    def test_empty_content_returns_empty_dict(self):
        class _R:
            content = []
        assert base.parse_todo_response(_R()) == {}


# ---------------------------------------------------------------------------
# make_tag, log_sent, load_sent
# ---------------------------------------------------------------------------

class TestSentLog:
    def test_make_tag_prefix(self):
        tag = base.make_tag()
        assert isinstance(tag, str)
        assert tag.startswith("⚡att:")

    def test_make_tag_unique(self):
        # Two consecutive calls should produce different tags (time + pid hash).
        tags = {base.make_tag() for _ in range(5)}
        # At least 2 distinct values across 5 calls; in practice all 5.
        assert len(tags) >= 2

    def test_load_sent_missing_file_returns_empty(self, envoy_home, monkeypatch):
        sent_path = str(envoy_home / "sent.json")
        monkeypatch.setattr(base, "SENT_LOG", sent_path)
        assert not os.path.exists(sent_path)
        assert base.load_sent() == []

    def test_log_sent_then_load_round_trip(self, envoy_home, monkeypatch):
        sent_path = str(envoy_home / "sent.json")
        monkeypatch.setattr(base, "SENT_LOG", sent_path)

        base.log_sent(
            tag="⚡att:abc123",
            channel="#general",
            recipient="alice",
            medium="slack",
            summary="hello world",
        )
        entries = base.load_sent()
        assert len(entries) == 1
        e = entries[0]
        assert e["tag"] == "⚡att:abc123"
        assert e["channel"] == "#general"
        assert e["recipient"] == "alice"
        assert e["medium"] == "slack"
        assert e["summary"] == "hello world"
        assert "sent_at" in e

    def test_log_sent_caps_at_200(self, envoy_home, monkeypatch):
        sent_path = str(envoy_home / "sent.json")
        monkeypatch.setattr(base, "SENT_LOG", sent_path)

        for i in range(205):
            base.log_sent(
                tag=f"⚡att:{i:06d}",
                channel="c",
                recipient="r",
                medium="m",
                summary=f"summary {i}",
            )
        entries = base.load_sent()
        assert len(entries) == 200
        # Should be the most recent 200 (entries 5..204).
        assert entries[0]["summary"] == "summary 5"
        assert entries[-1]["summary"] == "summary 204"


# ---------------------------------------------------------------------------
# _SLACK_TOOL_MAP transforms
# ---------------------------------------------------------------------------

class TestSlackToolMap:
    def _xform(self, name):
        new_name, fn, is_batch = base._TimeoutSession._SLACK_TOOL_MAP[name]
        return new_name, fn, is_batch

    def test_create_draft_transform(self):
        _, fn, _ = self._xform("create_draft")
        out = fn({"channelId": "C1", "text": "hi", "threadTs": "123"})
        assert out == {"channel": "C1", "text": "hi", "replyTo": "123"}

    def test_download_file_content_uses_fileId(self):
        _, fn, _ = self._xform("download_file_content")
        out = fn({"file": "F123"})
        assert out == {"fileId": "F123"}

    def test_lists_items_list_renames_keys(self):
        _, fn, _ = self._xform("lists_items_list")
        out = fn({"list_id": "L1", "limit": 50})
        assert out == {"listId": "L1", "maxRecords": 50}

    def test_open_conversation_joins_users_list(self):
        _, fn, _ = self._xform("open_conversation")
        out = fn({"users": ["U1", "U2", "U3"]})
        assert out == {"userIds": "U1,U2,U3"}

    def test_reaction_tool_default_emoji(self):
        _, fn, _ = self._xform("reaction_tool")
        out = fn({"channelId": "C1", "timestamp": "1.2"})
        assert out["emoji"] == "eyes"
        assert out["channel"] == "C1"
        assert out["timestamp"] == "1.2"


# ---------------------------------------------------------------------------
# model_for / reload_models
# ---------------------------------------------------------------------------

class TestModelFor:
    def test_known_tier_returns_default(self, monkeypatch):
        # Force fresh load from defaults (no models.json present).
        monkeypatch.setattr(base, "MODELS_FILE", "/nonexistent/path/models.json")
        base.reload_models()
        assert base.model_for("heavy") == base.DEFAULT_MODELS["heavy"]
        assert base.model_for("light") == base.DEFAULT_MODELS["light"]

    def test_unknown_tier_falls_back_to_medium(self, monkeypatch):
        monkeypatch.setattr(base, "MODELS_FILE", "/nonexistent/path/models.json")
        base.reload_models()
        assert base.model_for("totally-unknown-tier") == base.DEFAULT_MODELS["medium"]

    def test_models_json_override(self, envoy_home, monkeypatch):
        models_path = envoy_home / "models.json"
        models_path.write_text(json.dumps({"heavy": "custom-heavy-model"}))
        monkeypatch.setattr(base, "MODELS_FILE", str(models_path))
        base.reload_models()
        try:
            assert base.model_for("heavy") == "custom-heavy-model"
            # Other tiers still use defaults.
            assert base.model_for("light") == base.DEFAULT_MODELS["light"]
        finally:
            base.reload_models()  # reset cache for isolation
