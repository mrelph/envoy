"""Shared infrastructure: MCP connections, AI invocation, config, logging."""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Dict

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from envoy_logger import get_logger

load_dotenv()

# Suppress MCP server stderr noise (Node warnings, internal errors)
_devnull = open(os.devnull, "w")


class MCPConnectionError(Exception):
    """Raised when an optional MCP server is unreachable."""
    pass


# --- MCP server params (singletons) ---

OUTLOOK_PARAMS = StdioServerParameters(command="aws-outlook-mcp", args=[])
BUILDER_PARAMS = StdioServerParameters(command="builder-mcp", args=[])
SLACK_PARAMS = StdioServerParameters(command="ai-community-slack-mcp", args=[])

_teamsnap_dir = os.path.join(os.path.expanduser("~"), "TeamSnapMCP")
_teamsnap_env = {**os.environ}
_teamsnap_dotenv = os.path.join(_teamsnap_dir, ".env")
if os.path.exists(_teamsnap_dotenv):
    with open(_teamsnap_dotenv) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                _teamsnap_env[k.strip()] = v.strip()
TEAMSNAP_PARAMS = StdioServerParameters(
    command="node",
    args=[os.path.join(_teamsnap_dir, "dist", "wrapper.js")],
    env=_teamsnap_env,
)

_node_quiet_env = {**os.environ, "NODE_NO_WARNINGS": "1"}

SHAREPOINT_PARAMS = StdioServerParameters(command="amazon-sharepoint-mcp", args=[], env=_node_quiet_env)

MCP_SERVERS = {
    "Outlook": OUTLOOK_PARAMS,
    "Phonetool": BUILDER_PARAMS,
    "Slack": SLACK_PARAMS,
    "TeamSnap": TEAMSNAP_PARAMS,
    "SharePoint": SHAREPOINT_PARAMS,
}


# --- MCP context managers ---

def _mcp_session(params, name):
    """Generic MCP session context manager with logging and connection caching.
    
    First call opens the connection. Subsequent calls within the same async context
    reuse it. Falls back to a fresh connection if the cached one is stale.
    """
    _cache = {"session": None, "stdio": None}

    @asynccontextmanager
    async def _ctx():
        logger = get_logger()
        try:
            logger.log("DEBUG", "mcp_request", f"MCP connect to {name}: initialize",
                        server_name=name, tool_name="initialize", argument_keys=[])
        except Exception:
            pass
        try:
            async with stdio_client(params, errlog=_devnull) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    try:
                        logger.log("DEBUG", "mcp_response", f"MCP connected to {name}",
                                    server_name=name, tool_name="initialize", response_size_bytes=0)
                    except Exception:
                        pass
                    yield s
        except Exception as e:
            try:
                logger.log("ERROR", "mcp_error", f"MCP error connecting to {name}: {e}",
                            server_name=name, tool_name="initialize", error_description=str(e))
            except Exception:
                pass
            if name == "Slack":
                raise MCPConnectionError(f"Slack MCP unavailable: {e}") from e
            raise
    return _ctx


def _mcp_batch_session(params, name):
    """Long-lived MCP session for batch operations within a single event loop.
    
    Usage:
        session = await mcp_pool.acquire("Outlook")
        result = await session.call_tool(...)
        # session stays open for reuse
        await mcp_pool.release_all()
    """
    pass  # Placeholder for multi-agent phase


outlook = _mcp_session(OUTLOOK_PARAMS, "Outlook")
builder = _mcp_session(BUILDER_PARAMS, "Phonetool")
slack = _mcp_session(SLACK_PARAMS, "Slack")
teamsnap = _mcp_session(TEAMSNAP_PARAMS, "TeamSnap")
sharepoint = _mcp_session(SHAREPOINT_PARAMS, "SharePoint")


# --- Shared MCP batch runner ---

async def mcp_batch(server_name: str, calls: list) -> list:
    """Run multiple MCP tool calls in a single session. Avoids reconnecting per call.
    
    Args:
        server_name: Key from MCP_SERVERS ("Outlook", "Phonetool", "Slack", "TeamSnap")
        calls: List of (tool_name, arguments) tuples
    
    Returns:
        List of result strings, one per call.
    """
    sessions = {"Outlook": outlook, "Phonetool": builder, "Slack": slack, "TeamSnap": teamsnap}
    session_fn = sessions.get(server_name)
    if not session_fn:
        return [f"Unknown server: {server_name}"] * len(calls)
    
    results = []
    async with session_fn() as session:
        for tool_name, arguments in calls:
            try:
                result = await session.call_tool(tool_name, arguments)
                results.append(result.content[0].text if result.content else "No result.")
            except Exception as e:
                results.append(f"Error: {e}")
    return results


# --- Connection testing ---

def check_mcp_connections() -> Dict[str, bool]:
    async def _test_one(name, params):
        try:
            async with stdio_client(params, errlog=_devnull) as (r, w):
                async with ClientSession(r, w) as s:
                    await asyncio.wait_for(s.initialize(), timeout=10)
                    return name, True
        except Exception:
            return name, False

    async def _test_bedrock():
        try:
            import boto3
            client = boto3.client('bedrock-runtime', region_name='us-west-2')
            client.meta.endpoint_url
            return "Bedrock", True
        except Exception:
            return "Bedrock", False

    async def _test_all():
        tasks = [_test_one(n, p) for n, p in MCP_SERVERS.items()]
        tasks.append(_test_bedrock())
        return dict(await asyncio.gather(*tasks))

    return asyncio.run(_test_all())


# --- AI / Bedrock ---

MODELS_FILE = os.path.expanduser("~/.envoy/models.json")
DEFAULT_MODELS = {
    "agent":  "us.anthropic.claude-opus-4-6-v1",
    "heavy":  "us.anthropic.claude-opus-4-6-v1",
    "medium": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "light":  "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    "memory": "us.amazon.nova-micro-v1:0",
}
MODEL_CATALOG = [
    ("us.anthropic.claude-opus-4-6-v1",              "Claude Opus 4.6",   "Best reasoning, highest cost"),
    ("us.anthropic.claude-sonnet-4-20250514-v1:0",   "Claude Sonnet 4",   "Strong balance of speed & quality"),
    ("us.anthropic.claude-3-5-haiku-20241022-v1:0",  "Claude 3.5 Haiku",  "Fast & cheap, good for simple tasks"),
    ("us.amazon.nova-pro-v1:0",                      "Nova Pro",          "Best Nova quality, multimodal"),
    ("us.amazon.nova-lite-v1:0",                     "Nova Lite",         "Fast & low-cost multimodal"),
    ("us.amazon.nova-micro-v1:0",                    "Nova Micro",        "Text-only, fastest & cheapest Nova"),
    ("us.amazon.nova-premier-v1:0",                  "Nova Premier",      "Most capable Nova, complex tasks"),
    ("moonshot.kimi-k2-thinking",                    "Kimi K2 Thinking",  "Strong coding & reasoning"),
    ("moonshotai.kimi-k2.5",                         "Kimi K2.5",         "Latest Kimi, multimodal"),
    ("deepseek.r1-v1:0",                             "DeepSeek R1",       "Strong reasoning, thinking model"),
]


def _load_models() -> dict:
    models = dict(DEFAULT_MODELS)
    try:
        with open(MODELS_FILE) as f:
            models.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return models

_models_cache = None

def model_for(tier: str) -> str:
    global _models_cache
    if _models_cache is None:
        _models_cache = _load_models()
    return _models_cache.get(tier, DEFAULT_MODELS["medium"])


def reload_models():
    """Force reload models config from disk (call after editing models.json)."""
    global _models_cache
    _models_cache = None


_bedrock_client = None

def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is not None:
        return _bedrock_client
    import boto3
    aws_config = {'region_name': os.getenv('AWS_REGION', 'us-west-2')}
    if os.getenv('AWS_ACCESS_KEY_ID'):
        aws_config['aws_access_key_id'] = os.getenv('AWS_ACCESS_KEY_ID')
        aws_config['aws_secret_access_key'] = os.getenv('AWS_SECRET_ACCESS_KEY')
        if os.getenv('AWS_SESSION_TOKEN'):
            aws_config['aws_session_token'] = os.getenv('AWS_SESSION_TOKEN')
    _bedrock_client = boto3.client('bedrock-runtime', **aws_config)
    return _bedrock_client


_token_usage = {'input': 0, 'output': 0, 'calls': 0, 'by_tier': {}}


def get_token_usage() -> dict:
    return dict(_token_usage)


def reset_token_usage():
    _token_usage.update({'input': 0, 'output': 0, 'calls': 0, 'by_tier': {}})


def format_token_usage() -> str:
    u = _token_usage
    if not u['calls']:
        return "No AI calls this session."
    def _fmt(n): return f"{n:,}" if n < 10000 else f"{n/1000:.0f}K"
    lines = [f"Session tokens: {_fmt(u['input'])} in / {_fmt(u['output'])} out ({u['calls']} calls)"]
    if u['by_tier']:
        parts = [f"{t}: {_fmt(d['input'])}/{_fmt(d['output'])} ({d['calls']})" for t, d in u['by_tier'].items()]
        lines.append(f"By tier: {', '.join(parts)}")
    return "\n".join(lines)


def invoke_ai(prompt: str, max_tokens: int = 10000, tier: str = "heavy") -> str:
    """Call Bedrock with the given prompt. Handles thinking models."""
    bedrock = _get_bedrock_client()
    model_id = model_for(tier)
    logger = get_logger()
    try:
        logger.log("INFO", "ai_invocation_start", f"Invoking {model_id}",
                    model_id=model_id, tier=tier, prompt_length=len(prompt))
    except Exception:
        pass

    start = time.monotonic()
    try:
        response = bedrock.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        result_text = None
        for block in response['output']['message']['content']:
            if 'text' in block:
                result_text = block['text']
                break
        if result_text is None:
            raise ValueError(f"No text block in {model_id} response")
        try:
            elapsed_ms = (time.monotonic() - start) * 1000
            usage = response.get('usage', {})
            in_tok = usage.get('inputTokens', 0)
            out_tok = usage.get('outputTokens', 0)
            _token_usage['input'] += in_tok
            _token_usage['output'] += out_tok
            _token_usage['calls'] += 1
            tier_entry = _token_usage['by_tier'].setdefault(tier, {'input': 0, 'output': 0, 'calls': 0})
            tier_entry['input'] += in_tok
            tier_entry['output'] += out_tok
            tier_entry['calls'] += 1
            logger.log("INFO", "ai_invocation_end", f"{model_id} responded",
                        model_id=model_id, response_length=len(result_text),
                        duration_ms=round(elapsed_ms, 1),
                        input_tokens=in_tok, output_tokens=out_tok)
        except Exception:
            pass
        return result_text
    except Exception as e:
        try:
            logger.log("ERROR", "ai_invocation_error", f"{model_id} failed: {e}",
                        model_id=model_id, error_message=str(e))
        except Exception:
            pass
        raise


# --- Agent identity ---

def agent_name() -> str:
    p = os.path.expanduser("~/.envoy/soul.md")
    if os.path.exists(p):
        for line in open(p):
            if line.strip().startswith("- Agent name:"):
                val = line.split(":", 1)[1].strip()
                if val:
                    return val
    return "Envoy"


# --- Sent message tracking ---

SENT_LOG = os.path.expanduser("~/.envoy/sent.json")
TAG_PREFIX = "⚡att:"


def make_tag() -> str:
    import hashlib
    h = hashlib.sha1(f"{time.time()}{os.getpid()}".encode()).hexdigest()[:6]
    return f"{TAG_PREFIX}{h}"


def log_sent(tag: str, channel: str, recipient: str, medium: str, summary: str):
    entries = []
    if os.path.exists(SENT_LOG):
        try:
            entries = json.loads(open(SENT_LOG).read())
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    entries.append({
        "tag": tag, "channel": channel, "recipient": recipient,
        "medium": medium, "summary": summary[:200],
        "sent_at": datetime.now().isoformat(),
    })
    entries = entries[-200:]
    os.makedirs(os.path.dirname(SENT_LOG), exist_ok=True)
    with open(SENT_LOG, "w") as f:
        json.dump(entries, f, indent=2)


def load_sent() -> list:
    if os.path.exists(SENT_LOG):
        try:
            return json.loads(open(SENT_LOG).read())
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return []


# --- Email parsing helper ---

def parse_email_search_result(result, extra_fields=None) -> List[Dict]:
    emails = []
    if not result.content:
        return emails
    content = str(result.content[0].text)
    try:
        outer = json.loads(content)
        if 'content' in outer and len(outer['content']) > 0:
            inner_text = outer['content'][0].get('text', '{}')
            data = json.loads(inner_text)
            if data.get('success') and 'content' in data:
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


# --- Todo response parser ---

def parse_todo_response(result) -> dict:
    if not result.content:
        return {}
    raw = str(result.content[0].text)
    try:
        outer = json.loads(raw)
        if 'content' in outer and outer['content']:
            inner = json.loads(outer['content'][0].get('text', '{}'))
            return inner.get('content', inner)
        return outer
    except (json.JSONDecodeError, KeyError, IndexError):
        return {}
