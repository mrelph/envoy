"""Tests for the proactive activity feed."""

import time
from unittest.mock import patch, MagicMock

import pytest

from agents.feed import FeedItem, add_item, get_items, clear, on_new_item, _SEEN_KEYS, _items, _listeners


@pytest.fixture(autouse=True)
def clean_feed():
    """Reset feed state between tests."""
    clear()
    _listeners.clear()
    yield
    clear()
    _listeners.clear()


class TestFeedItem:
    """FeedItem data model."""

    def test_display_format(self):
        item = FeedItem(icon="📧", text="New from Alice", category="email", timestamp=time.time())
        assert "📧" in item.display
        assert "New from Alice" in item.display

    def test_dedup_key_auto_generated(self):
        item = FeedItem(icon="📧", text="Same email", category="email")
        assert item.dedup_key != ""
        assert len(item.dedup_key) == 12

    def test_same_content_same_dedup_key(self):
        a = FeedItem(icon="📧", text="Exact same", category="email")
        b = FeedItem(icon="📧", text="Exact same", category="email")
        assert a.dedup_key == b.dedup_key

    def test_different_content_different_key(self):
        a = FeedItem(icon="📧", text="Email A", category="email")
        b = FeedItem(icon="📧", text="Email B", category="email")
        assert a.dedup_key != b.dedup_key

    def test_action_hint_in_display(self):
        item = FeedItem(icon="🧩", text="Meeting in 1h", category="calendar", action_hint="prep?")
        assert "→ prep?" in item.display

    def test_priority_ordering(self):
        urgent = FeedItem(icon="📧", text="VP email", category="email", priority=0)
        normal = FeedItem(icon="💬", text="Slack msg", category="slack", priority=1)
        assert urgent.priority < normal.priority


class TestFeedManager:
    """Feed add/get/dedup/cap logic."""

    def test_add_and_get(self):
        item = FeedItem(icon="📧", text="Test", category="email")
        assert add_item(item) is True
        assert len(get_items()) == 1

    def test_deduplication(self):
        item = FeedItem(icon="📧", text="Duplicate", category="email")
        assert add_item(item) is True
        assert add_item(item) is False  # same dedup_key
        assert len(get_items()) == 1

    def test_max_cap(self):
        for i in range(25):
            add_item(FeedItem(icon="📧", text=f"Item {i}", category="email"))
        assert len(get_items()) == 20

    def test_newest_first(self):
        add_item(FeedItem(icon="📧", text="First", category="email", timestamp=100))
        add_item(FeedItem(icon="📧", text="Second", category="email", timestamp=200))
        items = get_items()
        assert "Second" in items[0].text
        assert "First" in items[1].text

    def test_listener_called_on_add(self):
        received = []
        on_new_item(lambda item: received.append(item))
        add_item(FeedItem(icon="💬", text="Ping", category="slack"))
        assert len(received) == 1
        assert received[0].text == "Ping"

    def test_listener_not_called_on_dedup(self):
        received = []
        on_new_item(lambda item: received.append(item))
        item = FeedItem(icon="💬", text="Once", category="slack")
        add_item(item)
        add_item(item)
        assert len(received) == 1

    def test_clear_resets_everything(self):
        add_item(FeedItem(icon="📧", text="X", category="email"))
        clear()
        assert len(get_items()) == 0
        # Same item can be added again after clear
        assert add_item(FeedItem(icon="📧", text="X", category="email")) is True


class TestInsightGenerators:
    """Individual generators produce correct FeedItems."""

    def test_vip_emails_empty_when_no_vips(self):
        import asyncio
        from agents.feed import _check_vip_emails
        with patch("agents.feed._get_vip_aliases", return_value=[]):
            items = asyncio.run(_check_vip_emails())
        assert items == []

    def test_stale_commitments_from_memory(self):
        import asyncio
        from agents.feed import _check_stale_commitments
        with patch("agents.memory2.recall", return_value="- overdue: Send doc to Alice by Friday"):
            items = asyncio.run(_check_stale_commitments())
        assert len(items) >= 1
        assert items[0].icon == "⏰"

    def test_generator_handles_exceptions(self):
        import asyncio
        from agents.feed import _check_vip_emails
        with patch("agents.feed._get_vip_aliases", side_effect=RuntimeError("boom")):
            items = asyncio.run(_check_vip_emails())
        assert items == []


class TestVipAliases:
    """VIP alias extraction from envoy.md."""

    def test_get_vip_aliases_callable(self):
        from agents.feed import _get_vip_aliases
        # Just verify it doesn't crash and returns a list
        result = _get_vip_aliases()
        assert isinstance(result, list)
