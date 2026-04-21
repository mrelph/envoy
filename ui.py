"""Envoy — shared UI utilities (MCP checks, model catalog)."""

import os
import json
import time

CATALOG_CACHE = os.path.expanduser("~/.envoy/models_catalog.json")
_CATALOG_TTL = 3600  # 1h


def _check_mcp_servers():
    """Check which MCP servers are actually reachable (live connection test)."""
    from agents.base import check_mcp_connections
    try:
        return check_mcp_connections()
    except Exception:
        return {}


def _aws_cfg():
    cfg = {'region_name': os.getenv('AWS_REGION', 'us-west-2')}
    if os.getenv('AWS_ACCESS_KEY_ID'):
        cfg['aws_access_key_id'] = os.getenv('AWS_ACCESS_KEY_ID')
        cfg['aws_secret_access_key'] = os.getenv('AWS_SECRET_ACCESS_KEY')
        if os.getenv('AWS_SESSION_TOKEN'):
            cfg['aws_session_token'] = os.getenv('AWS_SESSION_TOKEN')
    return cfg


def _fetch_model_catalog(refresh: bool = False) -> list:
    """Return a merged list of (model_id, name, provider_or_desc).

    Combines on-demand foundation models AND cross-region inference profiles
    (which are what DEFAULT_MODELS actually uses). Cached for 1h unless refresh=True.
    """
    if not refresh and os.path.exists(CATALOG_CACHE):
        try:
            with open(CATALOG_CACHE) as f:
                data = json.load(f)
            if (time.time() - data.get("ts", 0)) < _CATALOG_TTL:
                return [tuple(x) for x in data.get("items", [])]
        except (json.JSONDecodeError, OSError):
            pass

    import boto3
    items = []
    seen = set()
    try:
        client = boto3.client('bedrock', **_aws_cfg())
        # Inference profiles (us.anthropic.*, etc.) — what we actually invoke
        try:
            profiles = client.list_inference_profiles().get('inferenceProfileSummaries', [])
            for p in profiles:
                pid = p.get('inferenceProfileId') or p.get('inferenceProfileArn', '').split('/')[-1]
                if pid and pid not in seen:
                    seen.add(pid)
                    items.append((pid, p.get('inferenceProfileName', pid), p.get('description', '')))
        except Exception:
            pass
        # On-demand foundation models
        try:
            models = client.list_foundation_models().get('modelSummaries', [])
            for m in models:
                if 'ON_DEMAND' not in m.get('inferenceTypesSupported', []):
                    continue
                mid = m['modelId']
                if mid in seen:
                    continue
                seen.add(mid)
                items.append((mid, m.get('modelName', mid), m.get('providerName', '')))
        except Exception:
            pass
    except Exception:
        return []

    items.sort(key=lambda x: (x[2] or '', x[1] or '', x[0]))

    if items:
        try:
            os.makedirs(os.path.dirname(CATALOG_CACHE), exist_ok=True)
            with open(CATALOG_CACHE, "w") as f:
                json.dump({"ts": time.time(), "items": items}, f)
        except OSError:
            pass
    return items
