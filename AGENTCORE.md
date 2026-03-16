# Running DirectsDigest on AgentCore

This tool can run as an agent on Amazon's AgentCore platform.

## Quick Deploy

```bash
# Package the agent
cd directs-digest
zip -r directs-digest-agent.zip . -x "*.git*" -x "venv/*" -x "__pycache__/*"

# Deploy to AgentCore
agentcore deploy --config agent_config.json --package directs-digest-agent.zip
```

## Agent Configuration

The agent exposes one tool: `generate_digest`

### Parameters

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `manager_alias` | string | yes | — | Manager's Amazon alias |
| `days` | integer | no | 14 | Days to look back |
| `include_ai_summary` | boolean | no | true | Include AI analysis |
| `email_result` | boolean | no | false | Email the digest |

### Example Request

```json
{
  "tool": "generate_digest",
  "parameters": {
    "manager_alias": "yourlogin",
    "days": 7,
    "include_ai_summary": true,
    "email_result": true
  }
}
```

### Example Response

```json
{
  "success": true,
  "digest": "# Highest Priority Items\n...",
  "email_sent": true,
  "manager": "yourlogin",
  "days": 7,
  "ai_summary_included": true
}
```

## Use Cases on AgentCore

### 1. Scheduled Weekly Digests

```json
{
  "schedule": "0 8 * * MON",
  "tool": "generate_digest",
  "parameters": {
    "manager_alias": "yourlogin",
    "days": 7,
    "email_result": true
  }
}
```

### 2. On-Demand via Chat

Integrate with chat platforms — the agent receives the user's alias from context and generates a digest on request.

### 3. Dashboard Integration

Embed in management dashboards for real-time team insights.

## Requirements

The agent runtime needs:
- Access to `builder-mcp` (Phonetool)
- Access to `aws-outlook-mcp` (Email)
- AWS Bedrock permissions (for AI summaries)
- Python 3.9+ runtime

## Testing Locally

```bash
python3 agent_handler.py
```

This runs a test request against the handler and prints the result.

## MCP Server Configuration

The agent uses two MCP servers defined in `agent_config.json`:

| Server | Purpose |
|---|---|
| `builder-mcp` | Phonetool access |
| `aws-outlook-mcp` | Email operations |

These must be available in the AgentCore runtime environment.
