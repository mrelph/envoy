"""Response parsers — extract structured data from MCP tool responses.

Extracted from agents/base.py. The original functions are still importable
from agents.base for backward compatibility.
"""

import json
from typing import List, Dict
from envoy_logger import get_logger

# Import the canonical wrapper stripper so both parser copies stay in sync.
from agents.base import strip_mcp_wrapper


def parse_email_search_result(result, extra_fields=None) -> List[Dict]:
    """Parse email search MCP response into list of email dicts."""
    emails = []
    if not result.content:
        return emails
    # Strip the MCP untrusted-content wrapper before json.loads (see
    # agents/base.py parse_email_search_result for the full rationale).
    content = strip_mcp_wrapper(str(result.content[0].text))
    try:
        data = json.loads(content)
        if data.get('success') and isinstance(data.get('content'), dict):
            for email in data['content'].get('emails', []):
                entry = {
                    'conversationId': email.get('conversationId', ''),
                    'from': ', '.join(email.get('senders', [])),
                    'to': ', '.join(email.get('recipients', [])),
                    'subject': email.get('topic', ''),
                    'date': email.get('lastDeliveryTime', ''),
                    'snippet': email.get('preview', ''),
                }
                emails.append(entry)
    except Exception as e:
        get_logger().log_error(f"Error parsing email data: {e}")
    return emails


def parse_todo_response(result) -> dict:
    """Parse to-do MCP response into dict."""
    if not result.content:
        return {}
    raw = strip_mcp_wrapper(str(result.content[0].text))
    try:
        data = json.loads(raw)
        if isinstance(data.get('content'), dict):
            return data['content']
        return data
    except (json.JSONDecodeError, KeyError, IndexError):
        return {}
