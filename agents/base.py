"""Shared infrastructure: MCP connections, AI invocation, config, logging."""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import List, Dict

from dotenv import load_dotenv
from envoy_logger import get_logger

# Lazy-loaded heavy modules (mcp ~2s, boto3 ~0.7s)
ClientSession = None
StdioServerParameters = None
stdio_client = None

def _ensure_mcp():
    global ClientSession, StdioServerParameters, stdio_client
    if ClientSession is None:
        from mcp import ClientSession as _CS, StdioServerParameters as _SP
        from mcp.client.stdio import stdio_client as _sc
        ClientSession = _CS
        StdioServerParameters = _SP
        stdio_client = _sc

load_dotenv(os.path.expanduser("~/.envoy/.env"))
load_dotenv()  # fallback to project-dir .env

# Suppress MCP server stderr noise (Node warnings, internal errors)
_devnull = None

def _get_devnull():
    global _devnull
    if _devnull is None or _devnull.closed:
        import atexit
        _devnull = open(os.devnull, "w")
        atexit.register(_devnull.close)
    return _devnull


class MCPConnectionError(Exception):
    """Raised when an optional MCP server is unreachable."""
    pass


# --- MCP server params (lazy — constructed on first use to avoid importing mcp at module load) ---

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

_node_quiet_env = {**os.environ, "NODE_NO_WARNINGS": "1"}
_outlook_env = {**os.environ, "OUTLOOK_MCP_ENABLE_WRITES": "true"}

# Raw param dicts — converted to StdioServerParameters on first access
_MCP_PARAM_DEFS = {
    "Outlook":    {"command": "aws-outlook-mcp", "args": [], "env": _outlook_env},
    "Phonetool":  {"command": "builder-mcp", "args": []},
    "Slack":      {"command": "ai-community-slack-mcp", "args": []},
    "TeamSnap":   {"command": "node", "args": [os.path.join(_teamsnap_dir, "dist", "wrapper.js")], "env": _teamsnap_env},
    "SharePoint": {"command": "amazon-sharepoint-mcp", "args": [], "env": _node_quiet_env},
    "Kingpin":    {"command": "kingpin-mcp", "args": []},
}

# Optional user overrides: ~/.envoy/mcp.json
# Format matches standard mcpServers convention:
#   { "MyServer": { "command": "my-mcp", "args": ["--flag"], "env": {"KEY": "val"} } }
# Entries override built-ins by name; new names are added.
_user_mcp_path = os.path.join(os.path.expanduser("~"), ".envoy", "mcp.json")
if os.path.exists(_user_mcp_path):
    try:
        import json as _json
        with open(_user_mcp_path) as _f:
            for _name, _def in _json.load(_f).items():
                if "env" in _def:
                    _def["env"] = {**os.environ, **_def["env"]}
                _MCP_PARAM_DEFS[_name] = _def
    except Exception as _e:
        import sys
        print(f"⚠ Failed to load {_user_mcp_path}: {_e}", file=sys.stderr)

_mcp_params_cache = {}

def _get_params(name):
    if name not in _mcp_params_cache:
        _ensure_mcp()
        _mcp_params_cache[name] = StdioServerParameters(**_MCP_PARAM_DEFS[name])
    return _mcp_params_cache[name]

# Legacy aliases for external code that references these directly
def __getattr__(name):
    _aliases = {
        "OUTLOOK_PARAMS": "Outlook", "BUILDER_PARAMS": "Phonetool",
        "SLACK_PARAMS": "Slack", "TEAMSNAP_PARAMS": "TeamSnap",
        "SHAREPOINT_PARAMS": "SharePoint", "KINGPIN_PARAMS": "Kingpin",
        "MCP_SERVERS": None,
    }
    if name in _aliases:
        if name == "MCP_SERVERS":
            return {k: _get_params(k) for k in _MCP_PARAM_DEFS}
        return _get_params(_aliases[name])
    raise AttributeError(f"module 'agents.base' has no attribute {name!r}")


# --- MCP context managers ---

MCP_CALL_TIMEOUT = 30  # seconds per MCP tool call


class _TimeoutSession:
    """Wraps an MCP ClientSession to add a timeout to every call_tool invocation.
    
    Also tracks transport health — on connection errors, marks the session as dead
    so _mcp_session can reopen it on the next call.
    """
    def __init__(self, session, name, timeout=MCP_CALL_TIMEOUT):
        self._session = session
        self._name = name
        self._timeout = timeout
        self.dead = False

    async def call_tool(self, tool_name, arguments=None, **kwargs):
        try:
            return await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments, **kwargs),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"{self._name}/{tool_name} timed out after {self._timeout}s")
        except (BrokenPipeError, ConnectionError, EOFError) as e:
            self.dead = True
            raise
        except Exception as e:
            # anyio/mcp sometimes wraps transport errors — heuristic
            msg = str(e).lower()
            if any(k in msg for k in ("closed", "broken pipe", "transport", "eof")):
                self.dead = True
            raise

    def __getattr__(self, name):
        return getattr(self._session, name)


import threading


# Single persistent event loop for all MCP operations.
# This lets subprocess transports survive across multiple run() calls.
_loop = None
_loop_thread = None
_loop_lock = threading.Lock()


def _get_loop():
    global _loop, _loop_thread
    if _loop is not None and _loop.is_running():
        return _loop
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
        _loop_thread.start()
        return _loop


def run(coro):
    """Run an async coroutine on the shared event loop.
    
    Uses a persistent background loop so MCP subprocess connections
    survive across calls (~0.9s saved per reused connection).
    """
    future = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    return future.result(timeout=120)


# --- Persistent MCP sessions ---
# Instead of opening/closing a subprocess per call (~0.9s overhead each),
# keep sessions alive and reuse them. Closed on process exit.

_persistent = {}  # server_name → (stdio_cm, session_cm, session)


def _cleanup_persistent():
    """Close all persistent MCP sessions on process exit."""
    loop = _loop
    if not loop or not loop.is_running():
        return
    entries = [_persistent.pop(name) for name in list(_persistent) if name in _persistent]
    if not entries:
        return
    async def _close_all():
        await asyncio.gather(*[_close_persistent(e) for e in entries], return_exceptions=True)
    try:
        future = asyncio.run_coroutine_threadsafe(_close_all(), loop)
        future.result(timeout=8)
    except Exception:
        pass


import atexit
atexit.register(_cleanup_persistent)


async def _open_persistent(server_name):
    """Open a persistent MCP session (subprocess stays running)."""
    _ensure_mcp()
    params = _get_params(server_name)
    # We need to keep the context managers alive, so we drive them manually
    stdio_cm = stdio_client(params, errlog=_get_devnull())
    r, w = await stdio_cm.__aenter__()
    session_cm = ClientSession(r, w)
    session = await session_cm.__aenter__()
    await session.initialize()
    return stdio_cm, session_cm, _TimeoutSession(session, server_name)


async def _close_persistent(entry):
    """Close a persistent MCP session."""
    stdio_cm, session_cm, _ = entry
    try:
        await session_cm.__aexit__(None, None, None)
    except Exception:
        pass
    try:
        await stdio_cm.__aexit__(None, None, None)
    except Exception:
        pass


def _mcp_session(server_name):
    """MCP session context manager with persistent connection reuse.
    
    First call opens the subprocess. Subsequent calls reuse it.
    If the connection is dead, it's reopened automatically.
    """
    @asynccontextmanager
    async def _ctx():
        # Try cached session first — evict if flagged dead
        if server_name in _persistent:
            _, _, cached = _persistent[server_name]
            if getattr(cached, "dead", False):
                entry = _persistent.pop(server_name, None)
                if entry:
                    try:
                        await _close_persistent(entry)
                    except Exception:
                        pass
            else:
                try:
                    yield cached
                    # Post-yield: if caller's call_tool marked it dead, evict now
                    if getattr(cached, "dead", False):
                        entry = _persistent.pop(server_name, None)
                        if entry:
                            try:
                                await _close_persistent(entry)
                            except Exception:
                                pass
                    return
                except Exception:
                    # Caller raised — if transport is dead, evict for next call
                    if getattr(cached, "dead", False):
                        entry = _persistent.pop(server_name, None)
                        if entry:
                            try:
                                await _close_persistent(entry)
                            except Exception:
                                pass
                    raise

        # Open new persistent session
        logger = get_logger()
        try:
            logger.log("DEBUG", "mcp_request", f"MCP connect to {server_name}: initialize",
                        server_name=server_name, tool_name="initialize", argument_keys=[])
        except Exception:
            pass
        try:
            stdio_cm, session_cm, session = await _open_persistent(server_name)
            _persistent[server_name] = (stdio_cm, session_cm, session)
            try:
                logger.log("DEBUG", "mcp_response", f"MCP connected to {server_name}",
                            server_name=server_name, tool_name="initialize", response_size_bytes=0)
            except Exception:
                pass
            yield session
        except Exception as e:
            _persistent.pop(server_name, None)
            try:
                logger.log("ERROR", "mcp_error", f"MCP error connecting to {server_name}: {e}",
                            server_name=server_name, tool_name="initialize", error_description=str(e))
            except Exception:
                pass
            if server_name == "Slack":
                raise MCPConnectionError(f"Slack MCP unavailable: {e}") from e
            raise
    return _ctx


outlook = _mcp_session("Outlook")
builder = _mcp_session("Phonetool")
slack = _mcp_session("Slack")
teamsnap = _mcp_session("TeamSnap")
sharepoint = _mcp_session("SharePoint")
kingpin = _mcp_session("Kingpin")


# --- Shared MCP batch runner ---

async def mcp_batch(server_name: str, calls: list) -> list:
    """Run multiple MCP tool calls in a single session.
    
    Convenience wrapper for making several calls to the same server.
    Connections are persistent and reused automatically.
    
    Args:
        server_name: "Outlook", "Phonetool", "Slack", "TeamSnap", or "SharePoint"
        calls: List of (tool_name, arguments) tuples
    
    Returns:
        List of result strings, one per call.
    """
    sessions = {"Outlook": outlook, "Phonetool": builder, "Slack": slack, "TeamSnap": teamsnap, "Kingpin": kingpin}
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

_session_fns = {"Outlook": None, "Phonetool": None, "Slack": None, "TeamSnap": None, "SharePoint": None, "Kingpin": None}

def check_mcp_connections() -> Dict[str, bool]:
    """Test MCP server connectivity using persistent sessions.
    
    This warms up the connection pool — subsequent calls reuse these sessions.
    """
    # Lazy-bind session functions (avoids circular import at module level)
    if _session_fns["Outlook"] is None:
        _session_fns.update({"Outlook": outlook, "Phonetool": builder, "Slack": slack,
                             "TeamSnap": teamsnap, "SharePoint": sharepoint, "Kingpin": kingpin})

    async def _test_one(name, session_fn):
        try:
            async with session_fn() as s:
                # Session opened successfully — connection is alive and cached
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
        tasks = [_test_one(n, fn) for n, fn in _session_fns.items()]
        tasks.append(_test_bedrock())
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = {}
        for r in results:
            if isinstance(r, tuple) and len(r) == 2:
                out[r[0]] = r[1]
        return out

    return run(_test_all())


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
_bedrock_client_ts = 0
_BEDROCK_TTL = 3000  # 50 minutes — refresh before 1hr token expiry

def _get_bedrock_client():
    global _bedrock_client, _bedrock_client_ts
    if _bedrock_client is not None and (time.monotonic() - _bedrock_client_ts) < _BEDROCK_TTL:
        return _bedrock_client
    import boto3
    aws_config = {'region_name': os.getenv('AWS_REGION', 'us-west-2')}
    if os.getenv('AWS_ACCESS_KEY_ID'):
        aws_config['aws_access_key_id'] = os.getenv('AWS_ACCESS_KEY_ID')
        aws_config['aws_secret_access_key'] = os.getenv('AWS_SECRET_ACCESS_KEY')
        if os.getenv('AWS_SESSION_TOKEN'):
            aws_config['aws_session_token'] = os.getenv('AWS_SESSION_TOKEN')
    _bedrock_client = boto3.client('bedrock-runtime', **aws_config)
    _bedrock_client_ts = time.monotonic()
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
            if 'text' in block and isinstance(block['text'], str):
                result_text = block['text']
                break
        if result_text is None:
            # Thinking models may only return reasoningContent blocks
            for block in response['output']['message']['content']:
                rc = block.get('reasoningContent') or {}
                rt = rc.get('reasoningText')
                if isinstance(rt, str):
                    result_text = rt
                    break
                elif isinstance(rt, dict) and isinstance(rt.get('text'), str):
                    result_text = rt['text']
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
        with open(p) as f:
            for line in f:
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
            with open(SENT_LOG) as f:
                entries = json.loads(f.read())
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
            with open(SENT_LOG) as f:
                return json.loads(f.read())
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
