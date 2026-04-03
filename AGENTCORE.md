# Running Envoy on AgentCore

Envoy can run as a hosted agent on Amazon's AgentCore platform.

## Quick Deploy

```bash
cd envoy
zip -r envoy-agent.zip . -x "*.git*" -x "venv/*" -x "__pycache__/*" -x ".env"

agentcore deploy --package envoy-agent.zip
```

## Agent Configuration

The agent exposes tools for:
- Team email digest generation (reads full thread bodies)
- Inbox cleanup classification (reads full bodies for accurate triage)
- Customer email scanning
- PTO catch-up reports
- Slack scanning (with user resolution and thread context)
- Calendar management (recurring meetings, shared calendars)
- To-do management (full CRUD with due dates and importance)

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

## Scheduled Jobs

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

## Runtime Requirements

The AgentCore runtime needs:
- `builder-mcp` (Phonetool)
- `aws-outlook-mcp` (Email, calendar, to-do)
- `ai-community-slack-mcp` (Slack — optional)
- `amazon-sharepoint-mcp` (SharePoint — optional)
- AWS Bedrock permissions (Claude models)
- Python 3.7+ runtime

## Testing Locally

```bash
envoy digest --days 7
```

This runs a digest locally to verify MCP connections and Bedrock access.
