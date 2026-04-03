"""Envoy — shared UI utilities (MCP checks, model catalog)."""

import os
import json


def _check_mcp_servers():
    """Check which MCP servers are actually reachable (live connection test)."""
    from agents.base import check_mcp_connections
    try:
        return check_mcp_connections()
    except Exception:
        return {}


def _fetch_model_catalog():
    """Fetch available models from Bedrock API, fall back to static list."""
    import boto3
    try:
        aws_config = {'region_name': os.getenv('AWS_REGION', 'us-west-2')}
        if os.getenv('AWS_ACCESS_KEY_ID'):
            aws_config['aws_access_key_id'] = os.getenv('AWS_ACCESS_KEY_ID')
            aws_config['aws_secret_access_key'] = os.getenv('AWS_SECRET_ACCESS_KEY')
            if os.getenv('AWS_SESSION_TOKEN'):
                aws_config['aws_session_token'] = os.getenv('AWS_SESSION_TOKEN')
        client = boto3.client('bedrock', **aws_config)
        models = client.list_foundation_models()['modelSummaries']
        results = []
        for m in sorted(models, key=lambda x: (x.get('providerName', ''), x['modelId'])):
            if 'ON_DEMAND' not in m.get('inferenceTypesSupported', []):
                continue
            results.append((m['modelId'], m.get('modelName', ''), m.get('providerName', '')))
        return results if results else []
    except Exception:
        return []
