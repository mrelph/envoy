import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from datetime import datetime, timedelta
from typing import List, Dict
import json
import os
from dotenv import load_dotenv

load_dotenv()


class AttacheService:
    def __init__(self):
        self.builder_mcp_params = StdioServerParameters(
            command="builder-mcp",
            args=[]
        )
        self.outlook_mcp_params = StdioServerParameters(
            command="aws-outlook-mcp",
            args=[]
        )
        self.slack_mcp_params = StdioServerParameters(
            command="ai-community-slack-mcp",
            args=[]
        )
        self.todo_mcp_params = self.outlook_mcp_params

    # --- Session helpers (reuse one connection per server within an async context) ---

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _outlook(self):
        async with stdio_client(self.outlook_mcp_params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                yield s

    @asynccontextmanager
    async def _builder(self):
        async with stdio_client(self.builder_mcp_params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                yield s

    @asynccontextmanager
    async def _slack(self):
        async with stdio_client(self.slack_mcp_params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                yield s

    # --- Model config ---

    @staticmethod
    def agent_name() -> str:
        """Return configured agent name or default 'Attaché'."""
        p = os.path.expanduser("~/.attache/personality.md")
        if os.path.exists(p):
            for line in open(p):
                if line.strip().startswith("- Agent name:"):
                    val = line.split(":", 1)[1].strip()
                    if val:
                        return val
        return "Attaché"

    # --- Sent message tracking ---

    SENT_LOG = os.path.expanduser("~/.attache/sent.json")
    TAG_PREFIX = "⚡att:"

    @classmethod
    def _make_tag(cls) -> str:
        import hashlib, time
        h = hashlib.sha1(f"{time.time()}{os.getpid()}".encode()).hexdigest()[:6]
        return f"{cls.TAG_PREFIX}{h}"

    @classmethod
    def _log_sent(cls, tag: str, channel: str, recipient: str, medium: str, summary: str):
        entries = []
        if os.path.exists(cls.SENT_LOG):
            try:
                entries = json.loads(open(cls.SENT_LOG).read())
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        entries.append({
            "tag": tag, "channel": channel, "recipient": recipient,
            "medium": medium, "summary": summary[:200],
            "sent_at": datetime.now().isoformat(),
        })
        # Keep last 200 entries
        entries = entries[-200:]
        os.makedirs(os.path.dirname(cls.SENT_LOG), exist_ok=True)
        with open(cls.SENT_LOG, "w") as f:
            json.dump(entries, f, indent=2)

    @classmethod
    def _load_sent(cls) -> list:
        if os.path.exists(cls.SENT_LOG):
            try:
                return json.loads(open(cls.SENT_LOG).read())
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        return []

    MODELS_FILE = os.path.expanduser("~/.attache/models.json")
    DEFAULT_MODELS = {
        "agent":  "us.anthropic.claude-opus-4-6-v1",
        "heavy":  "us.anthropic.claude-opus-4-6-v1",
        "medium": "us.anthropic.claude-sonnet-4-20250514-v1:0",
        "light":  "us.anthropic.claude-3-5-haiku-20241022-v1:0",
        "memory": "us.amazon.nova-micro-v1:0",
    }
    MODEL_CATALOG = [
        # Anthropic Claude
        ("us.anthropic.claude-opus-4-6-v1",              "Claude Opus 4.6",   "Best reasoning, highest cost"),
        ("us.anthropic.claude-sonnet-4-20250514-v1:0",   "Claude Sonnet 4",   "Strong balance of speed & quality"),
        ("us.anthropic.claude-3-5-haiku-20241022-v1:0",    "Claude 3.5 Haiku",  "Fast & cheap, good for simple tasks"),
        # Amazon Nova
        ("us.amazon.nova-pro-v1:0",                      "Nova Pro",          "Best Nova quality, multimodal"),
        ("us.amazon.nova-lite-v1:0",                     "Nova Lite",         "Fast & low-cost multimodal"),
        ("us.amazon.nova-micro-v1:0",                    "Nova Micro",        "Text-only, fastest & cheapest Nova"),
        ("us.amazon.nova-premier-v1:0",                  "Nova Premier",      "Most capable Nova, complex tasks"),
        # Moonshot Kimi
        ("moonshot.kimi-k2-thinking",                    "Kimi K2 Thinking",  "Strong coding & reasoning"),
        ("moonshotai.kimi-k2.5",                         "Kimi K2.5",         "Latest Kimi, multimodal"),
    ]

    @classmethod
    def _load_models(cls) -> dict:
        models = dict(cls.DEFAULT_MODELS)
        try:
            with open(cls.MODELS_FILE) as f:
                models.update(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return models

    def _model_for(self, tier: str) -> str:
        return self._load_models().get(tier, self.DEFAULT_MODELS["medium"])

    # --- Bedrock helper ---

    def _get_bedrock_client(self):
        import boto3
        aws_config = {'region_name': os.getenv('AWS_REGION', 'us-west-2')}
        if os.getenv('AWS_ACCESS_KEY_ID'):
            aws_config['aws_access_key_id'] = os.getenv('AWS_ACCESS_KEY_ID')
            aws_config['aws_secret_access_key'] = os.getenv('AWS_SECRET_ACCESS_KEY')
            if os.getenv('AWS_SESSION_TOKEN'):
                aws_config['aws_session_token'] = os.getenv('AWS_SESSION_TOKEN')
        return boto3.client('bedrock-runtime', **aws_config)

    def _invoke_ai(self, prompt: str, max_tokens: int = 10000, tier: str = "heavy") -> str:
        bedrock = self._get_bedrock_client()
        model_id = self._model_for(tier)
        response = bedrock.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        return response['output']['message']['content'][0]['text']

    # --- Email parsing helper ---

    def _parse_email_search_result(self, result, extra_fields=None) -> List[Dict]:
        """Parse MCP email search result into list of dicts."""
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
            print(f"Error parsing email data: {e}")
        return emails

    # --- Phonetool ---

    async def get_direct_reports(self, manager_alias: str) -> List[Dict[str, str]]:
        """Fetch direct reports from Phonetool — single call, no N+1."""
        async with self._builder() as session:
            result = await session.call_tool(
                "ReadInternalWebsites",
                arguments={"inputs": [f"https://phonetool.amazon.com/users/{manager_alias}"]}
            )
            directs = []
            content = str(result.content[0].text) if result.content else ''
            try:
                data = json.loads(content)
                if 'content' in data and 'content' in data['content']:
                    for dr in data['content']['content'].get('direct_reports', []):
                        alias = dr.get('login')
                        if alias:
                            directs.append({
                                'alias': alias,
                                'name': dr.get('name', alias)
                            })
            except Exception as e:
                print(f"Error parsing phonetool data: {e}")
            return directs

    async def get_management_chain(self, alias: str, levels: int = 3) -> List[Dict[str, str]]:
        """Fetch management chain (bosses) from Phonetool"""
        async with self._builder() as session:
            managers = []
            current_alias = alias

            for level in range(levels):
                try:
                    result = await session.call_tool(
                        "ReadInternalWebsites",
                        arguments={"inputs": [f"https://phonetool.amazon.com/users/{current_alias}"]}
                    )

                    content = str(result.content[0].text) if result.content else ''
                    data = json.loads(content)

                    if 'content' not in data or 'content' not in data['content']:
                        break

                    phonetool_data = data['content']['content']
                    manager = phonetool_data.get('manager')

                    if not manager:
                        break

                    manager_login = manager.get('login') if isinstance(manager, dict) else manager
                    if not manager_login:
                        break

                    mgr_result = await session.call_tool(
                        "ReadInternalWebsites",
                        arguments={"inputs": [f"https://phonetool.amazon.com/users/{manager_login}"]}
                    )
                    mgr_content = str(mgr_result.content[0].text) if mgr_result.content else ''
                    mgr_data = json.loads(mgr_content)

                    if 'content' not in mgr_data or 'content' not in mgr_data['content']:
                        break

                    mgr_info = mgr_data['content']['content']
                    managers.append({
                        'alias': manager_login,
                        'name': mgr_info.get('name', manager_login)
                    })
                    current_alias = manager_login

                except Exception as e:
                    print(f"Level {level+1}: Error fetching manager chain: {e}")
                    break

            return managers

    # --- Email fetching ---

    async def get_recent_emails(self, alias: str, days: int = 14, session=None) -> List[Dict]:
        """Fetch recent emails from a user. Accepts optional existing session."""
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        async def _fetch(s):
            result = await s.call_tool("email_search", arguments={
                "query": f"from:{alias}@amazon.com",
                "startDate": start_date, "endDate": end_date, "limit": 50
            })
            return self._parse_email_search_result(result)

        if session:
            return await _fetch(session)
        async with self._outlook() as s:
            return await _fetch(s)

    # --- Team Digest ---

    def generate_digest(self, manager_alias: str, days: int = 14, selected_aliases: List[str] = None, vip_mode: bool = False) -> str:
        return asyncio.run(self._generate_digest_async(manager_alias, days, selected_aliases, vip_mode))

    async def _generate_digest_async(self, manager_alias: str, days: int = 14, selected_aliases: List[str] = None, vip_mode: bool = False) -> str:
        if vip_mode:
            print(f"Fetching management chain for {manager_alias}...")
            directs = await self.get_management_chain(manager_alias, levels=3)
            mode_label = "VIP Management Chain"
        else:
            print(f"Fetching direct reports for {manager_alias}...")
            directs = await self.get_direct_reports(manager_alias)
            mode_label = "Direct Reports"

        if selected_aliases:
            directs = [d for d in directs if d['alias'] in selected_aliases]

        if not directs:
            return f"No {'managers' if vip_mode else 'direct reports'} found for {manager_alias}"

        print(f"Found {len(directs)} {'managers' if vip_mode else 'direct reports'}. Fetching emails...")

        digest = f"# {mode_label} Email Digest\n\n"
        digest += f"**Period:** Last {days} days | **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        digest += "---\n\n"

        async with self._outlook() as session:
            for direct in directs:
                print(f"Processing emails from {direct['alias']}...")
                try:
                    emails = await self.get_recent_emails(direct['alias'], days, session=session)
                    digest += f"## {direct['name']} ({direct['alias']})\n\n"
                    if not emails:
                        digest += f"*No emails sent*\n\n"
                    else:
                        digest += f"**{len(emails)} emails sent**\n\n"
                        for email in emails:
                            digest += f"- **{email['subject']}** _{email['date']}_\n"
                            if email['snippet']:
                                snippet = email['snippet'][:120] + "..." if len(email['snippet']) > 120 else email['snippet']
                                digest += f"  {snippet}\n"
                            digest += "\n"
                    digest += "---\n\n"
                except Exception as e:
                    digest += f"Error fetching emails: {e}\n\n---\n\n"

        return digest

    # --- AI Summary ---

    def generate_ai_summary(self, digest: str, manager_alias: str, days: int) -> str:
        try:
            prompt = f"""Analyze this direct reports email digest and provide analysis in this EXACT format:

# Highest Priority Items

[List ONLY the 3-5 most critical items requiring immediate manager attention across ALL directs. Focus on urgent decisions, blockers, or high-impact items.]

---

# Team Member Details

## [Person Name] ([alias])

### Summary
[2-3 sentence summary of their recent email activity and focus areas]

### Recent Emails
- [Subject] - [Date]
[List up to 5 most recent/important emails]

### Actions & High Priority
- [Action item or high priority information]
[Only include if there are actual action items]

---

[Repeat for EACH team member]

IMPORTANT:
- Highest Priority section = cross-team critical items only
- Analyze EACH person separately
- Skip "Actions & High Priority" section if nothing actionable
- Keep email list concise (subject + date only)
- STRICT: Only include items from the last {days} days. Ignore anything older.

Digest to analyze:
{digest}"""
            return self._invoke_ai(prompt)
        except Exception as e:
            return f"# AI Summary\n\n**Error generating summary:** {e}\n"

    def extract_action_items(self, ai_summary: str) -> List[Dict[str, str]]:
        actions = []
        lines = ai_summary.split('\n')
        current_person = None
        in_actions = False

        for line in lines:
            if line.startswith('## '):
                current_person = line[3:].split('(')[0].strip()
                in_actions = False
            elif '### Actions & High Priority' in line:
                in_actions = True
            elif in_actions and line.startswith('- '):
                actions.append({
                    'title': line[2:].strip(),
                    'owner': current_person or 'Team'
                })
            elif in_actions and line.startswith('##'):
                in_actions = False

        return actions

    # --- Email sending ---

    def email_digest(self, digest: str, manager_alias: str, days: int, include_summary: bool = False) -> bool:
        return asyncio.run(self._email_digest_async(digest, manager_alias, days, include_summary))

    async def _email_digest_async(self, digest: str, manager_alias: str, days: int, include_summary: bool = False) -> bool:
        async with self._outlook() as session:
            html_body = self._markdown_to_html(digest)
            subject = f"{self.agent_name()}: {'AI ' if include_summary else ''}Team Digest - Last {days} Days"
            result = await session.call_tool(
                "email_send",
                arguments={
                    "to": [f"{manager_alias}@amazon.com"],
                    "subject": subject,
                    "body": html_body
                }
            )
            return not result.isError

    def _markdown_to_html(self, md_text: str) -> str:
        import markdown as md_lib
        CSS = """<style>
body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 900px; margin: 0 auto; padding: 20px; }
h1 { color: #232f3e; border-bottom: 3px solid #ff9900; padding-bottom: 10px; }
h2 { color: #232f3e; border-bottom: 2px solid #ddd; padding-bottom: 8px; margin-top: 30px; }
h3 { color: #555; }
table { border-collapse: collapse; width: 100%; margin: 20px 0; }
th, td { border: 1px solid #ddd; padding: 12px; text-align: left; }
th { background-color: #232f3e; color: white; }
tr:nth-child(even) { background-color: #f9f9f9; }
ul, ol { margin: 10px 0; padding-left: 30px; }
li { margin: 5px 0; }
hr { border: none; border-top: 2px solid #ddd; margin: 30px 0; }
strong { color: #232f3e; }
</style>"""
        body = md_lib.markdown(md_text, extensions=['tables', 'fenced_code'])
        return f"<html><head>{CSS}</head><body>{body}</body></html>"

    # --- To-Do ---

    def add_to_todo(self, action_items: List[Dict[str, str]], list_name: str = None) -> bool:
        list_name = list_name or f"{self.agent_name()} Actions"
        return asyncio.run(self._add_to_todo_async(action_items, list_name))

    async def _add_to_todo_async(self, action_items: List[Dict[str, str]], list_name: str = None) -> bool:
        list_name = list_name or f"{self.agent_name()} Actions"
        try:
            async with self._outlook() as session:
                lists_result = await session.call_tool("todo_lists", arguments={"operation": "list"})
                lists_data = self._parse_todo_response(lists_result)

                list_id = None
                for lst in lists_data.get('value', []):
                    if lst['displayName'] == list_name:
                        list_id = lst['id']
                        break

                if not list_id:
                    create_result = await session.call_tool("todo_lists", arguments={
                        "operation": "create", "displayName": list_name
                    })
                    list_data = self._parse_todo_response(create_result)
                    list_id = list_data['id']

                for item in action_items:
                    await session.call_tool("todo_tasks", arguments={
                        "operation": "create", "listId": list_id,
                        "title": f"[{item['owner']}] {item['title']}"
                    })

                return True
        except Exception as e:
            print(f"Error adding to To-Do: {e}")
            return False

    # --- Inbox Cleanup ---

    def fetch_inbox_emails(self, days: int = 14, limit: int = 100) -> List[Dict]:
        return asyncio.run(self._fetch_inbox_emails(days, limit))

    async def _fetch_inbox_emails(self, days: int = 14, limit: int = 100) -> List[Dict]:
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')
        async with self._outlook() as session:
            result = await session.call_tool("email_search", arguments={
                "query": "*", "folder": "inbox",
                "startDate": start_date, "endDate": end_date, "limit": limit
            })
            return self._parse_email_search_result(result)

    def classify_emails(self, emails: List[Dict], user_alias: str) -> List[Dict]:
        if not emails:
            return []
        try:
            email_list = ""
            for i, e in enumerate(emails):
                snippet = e.get('snippet', '')[:150]
                email_list += (
                    f"[{i}] From: {e['from']} | To: {e['to']} | Subject: {e['subject']} | Date: {e['date']}\n"
                    f"    Preview: {snippet}\n\n"
                )

            prompt = f"""You are a conservative email triage assistant. The user is {user_alias}@amazon.com.

Classify each email based on the sender, subject, and preview. When in doubt, KEEP.

Classify each email as exactly one of:

- DELETE — ONLY for truly junk email. All of these must be true:
  * Mass-produced content not written for the user or their team specifically
  * No information the user would find professionally useful
  * Examples: external marketing blasts, vendor newsletters, automated spam, event promotions from unknown orgs, mass surveys from external companies
  * NOT DELETE if: it's from a colleague, mentions the user's team/projects, contains org announcements, is a discussion thread the user might learn from, or has any work-relevant content

- REVIEW — Genuinely low-value to this specific user:
  * Automated notifications that are routine (build alerts, wiki edit notifications, ticket auto-updates)
  * Very large distribution list emails where content is generic and not in user's domain
  * Old resolved threads with no new information

- KEEP — When in doubt, KEEP. Specifically keep:
  * Anything from a person (not a bot/system) that discusses work topics
  * Emails where user is CC'd on team discussions, project updates, decisions
  * Org announcements, leadership communications, team-wide updates
  * Anything mentioning the user, their team, their projects, or their domain
  * Emails that could be useful context even if no action is required
  * Any email where you're unsure — default to KEEP

CRITICAL: Be very conservative. Most work email has value even if not directly addressed to the user. Only flag truly worthless email as DELETE.

For each email, output EXACTLY one line:
[index] CLASSIFICATION reason

Emails:
{email_list}"""

            ai_text = self._invoke_ai(prompt, max_tokens=8000, tier="medium")
            for line in ai_text.strip().split('\n'):
                line = line.strip()
                if not line or not line.startswith('['):
                    continue
                try:
                    bracket_end = line.index(']')
                    idx = int(line[1:bracket_end])
                    rest = line[bracket_end+1:].strip()
                    parts = rest.split(' ', 1)
                    classification = parts[0].upper()
                    reason = parts[1] if len(parts) > 1 else ''
                    if 0 <= idx < len(emails) and classification in ('DELETE', 'REVIEW', 'KEEP'):
                        emails[idx]['classification'] = classification
                        emails[idx]['reason'] = reason
                except (ValueError, IndexError):
                    continue

            for e in emails:
                if 'classification' not in e:
                    e['classification'] = 'KEEP'
                    e['reason'] = 'Could not classify'

            return emails
        except Exception as e:
            print(f"Error classifying emails: {e}")
            for em in emails:
                em['classification'] = 'KEEP'
                em['reason'] = f'Classification error: {e}'
            return emails

    def delete_emails(self, conversation_ids: List[str]) -> Dict[str, int]:
        return asyncio.run(self._delete_emails_async(conversation_ids))

    async def _delete_emails_async(self, conversation_ids: List[str]) -> Dict[str, int]:
        results = {'deleted': 0, 'failed': 0}
        async with self._outlook() as session:
            for cid in conversation_ids:
                try:
                    await session.call_tool("email_move", arguments={"conversationId": cid, "targetFolder": "deleteditems"})
                    results['deleted'] += 1
                except Exception:
                    results['failed'] += 1
        return results

    # --- Customer Email Scan ---

    def scan_customer_emails(self, alias: str, days: int = 14, team_aliases: List[str] = None) -> str:
        """Scan for external customer emails with action items."""
        return asyncio.run(self._scan_customer_emails_async(alias, days, team_aliases))

    async def _scan_customer_emails_async(self, alias: str, days: int = 14, team_aliases: List[str] = None) -> str:
        """Fetch external emails to user and team, then AI-extract action items."""
        all_aliases = [alias] + (team_aliases or [])
        all_emails = []

        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        end_date = datetime.now().strftime('%Y-%m-%d')

        async with self._outlook() as session:
            for person in all_aliases:
                print(f"Scanning external emails for {person}...")
                result = await session.call_tool(
                    "email_search",
                    arguments={
                        "query": f"to:{person}@amazon.com",
                        "startDate": start_date,
                        "endDate": end_date,
                        "limit": 50
                    }
                )
                emails = self._parse_email_search_result(result)
                for e in emails:
                    if 'amazon.com' not in e['from'].lower():
                        e['recipient'] = person
                        all_emails.append(e)

        if not all_emails:
            return "No external customer emails found."

        # AI analysis
        email_list = ""
        for i, e in enumerate(all_emails):
            email_list += f"[{i}] To: {e['recipient']} | From: {e['from']} | Subject: {e['subject']} | Date: {e['date']} | Preview: {e['snippet'][:200]}\n"

        prompt = f"""You are analyzing external customer emails sent to an Amazon team.
The manager is {alias}@amazon.com. Team members: {', '.join(all_aliases)}.

Analyze these external (non-Amazon) emails and produce a report in this EXACT format:

# Customer Email Report

**Period:** Last {days} days | **Scanned:** {len(all_emails)} external emails

## 🔴 Action Required

[List emails that clearly need a response or action, with owner and deadline if apparent]
- **[Subject]** from [sender] → [recipient] ([date]) — [what action is needed]

## ⚠️ Follow-Up Recommended

[Emails that may need attention but aren't urgent]
- **[Subject]** from [sender] → [recipient] ([date]) — [why follow-up recommended]

## 📋 FYI / No Action

[External emails that are informational only]
- **[Subject]** from [sender] → [recipient] ([date]) — [brief note]

## Summary

[2-3 sentences: overall customer engagement picture, any patterns, any risks]

IMPORTANT:
- Focus on identifying ACTION ITEMS — who needs to do what
- Flag anything that looks time-sensitive or overdue
- Group by urgency, not by person
- If an email is clearly automated/marketing, put it in FYI
- Skip the section entirely if empty
- STRICT: Only include emails dated within the last {days} days. Discard anything older.

Emails:
{email_list}"""

        try:
            return self._invoke_ai(prompt, tier="medium")
        except Exception as e:
            return f"# Customer Email Report\n\n**Error:** {e}\n"

    # --- Slack Scan ---

    def scan_slack(self, channels: List[str] = None, days: int = 7) -> str:
        """Scan Slack channels for critical information and action items."""
        return asyncio.run(self._scan_slack_async(channels, days))

    async def _scan_slack_async(self, channels: List[str] = None, days: int = 7) -> str:
        """Fetch recent Slack messages and AI-extract critical info and actions."""
        raw = await self._scan_slack_raw(channels, days)
        if raw.startswith("No "):
            return raw

        prompt = f"""You are analyzing Slack messages from an Amazon employee's workspace.

Messages are pre-sorted by priority:
- 🔴 DM = direct messages TO the user (highest priority — treat as personal/actionable)
- 🟡 GroupDM = group DMs involving the user (high priority)
- #channel = public/private channels (lower priority unless someone @-mentioned the user)

Analyze these messages and produce a report in this EXACT format:

# Slack Scan Report

## 🔴 Direct Messages (Action Required)
- **DM from @user** — [what they need / what action is required]

## ⚠️ Important Updates
- **#channel** or **GroupDM** — [summary]

## 🔑 Key Discussions
- **#channel** — [topic and status]

## 📋 FYI
- **#channel** — [brief note]

## Summary
[2-3 sentences: what's most critical, recommended priorities]

Skip empty sections. Skip bot messages and small talk. DMs always outrank channel noise.
STRICT: Only include messages from the last {days} days. Ignore anything older.

Messages:
{raw[:8000]}"""

        try:
            return self._invoke_ai(prompt, max_tokens=8000, tier="medium")
        except Exception as e:
            return f"# Slack Scan Report\n\n**Error:** {e}\n"

    async def _scan_slack_raw(self, channels: List[str] = None, days: int = 7) -> str:
        """Fetch raw Slack messages — DMs first (priority), then channels."""
        from datetime import timezone
        oldest = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        async with self._slack() as session:
            if channels:
                channel_ids = [(c, c, "channel") for c in channels]
            else:
                channel_ids = []

                # 1) DMs first — highest priority
                for ch_type in ["dm", "group_dm"]:
                    try:
                        result = await session.call_tool(
                            "list_channels",
                            arguments={"channelTypes": [ch_type], "unreadOnly": True, "limit": 20}
                        )
                        ch_data = json.loads(result.content[0].text) if result.content else {}
                        for c in ch_data.get('channels', []):
                            channel_ids.append((c['id'], c.get('name', c['id']), ch_type))
                    except Exception:
                        pass

                # 2) Channels second
                try:
                    result = await session.call_tool(
                        "list_channels",
                        arguments={"channelTypes": ["public_and_private"], "unreadOnly": True, "limit": 20}
                    )
                    ch_data = json.loads(result.content[0].text) if result.content else {}
                    for c in ch_data.get('channels', []):
                        channel_ids.append((c['id'], c.get('name', c['id']), "channel"))
                except Exception:
                    pass

            if not channel_ids:
                return "No Slack channels or DMs found to scan."

            # Resolve names for channels (DMs already have user info)
            ch_only = [cid for cid, _, kind in channel_ids if kind == "channel"]
            name_map = {}
            if ch_only:
                info_result = await session.call_tool("batch_get_channel_info", arguments={"channelIds": ch_only})
                for item in (json.loads(info_result.content[0].text) if info_result.content else []):
                    if 'result' in item:
                        name_map[item['channelId']] = item['result'].get('name', item['channelId'])

            # Fetch messages
            batch = [{"channelId": cid, "oldest": oldest, "limit": 30} for cid, _, _ in channel_ids]
            result = await session.call_tool("batch_get_conversation_history", arguments={"channels": batch})
            raw = json.loads(result.content[0].text) if result.content else []

        # Build lookup: cid → (display_name, kind)
        lookup = {}
        for cid, name, kind in channel_ids:
            display = name_map.get(cid, name)
            lookup[cid] = (display, kind)

        lines = []
        for item in raw:
            ch_id = item.get('channelId', '')
            display, kind = lookup.get(ch_id, (ch_id, "channel"))
            prefix = "🔴 DM" if kind == "dm" else ("🟡 GroupDM" if kind == "group_dm" else f"#{display}")
            for msg in item.get('result', {}).get('messages', []):
                text = msg.get('text', '')[:500]
                if text:
                    lines.append(f"[{prefix}] {msg.get('user', '?')}: {text}")

        return "\n".join(lines[:200]) if lines else "No Slack messages found in the specified period."

    # --- Morning Briefing ---

    def morning_briefing(self, alias: str = "") -> str:
        """Quick sweep of calendar, inbox, Slack, and to-dos for a proactive status snapshot."""
        alias = alias or os.getenv("USER", "")
        sections = []

        # Today's calendar
        try:
            cal = self.review_calendar(view="day")
            if "No calendar" not in cal:
                sections.append(f"## Calendar\n{cal}")
        except Exception as e:
            sections.append(f"## Calendar\nUnable to fetch: {e}")

        # To-do items
        try:
            todos = self._fetch_todos()
            if todos:
                sections.append(todos)
        except Exception as e:
            sections.append(f"## To-Do\nUnable to fetch: {e}")

        # Unread inbox count + recent highlights
        try:
            emails = self.fetch_inbox_emails(days=1, limit=30)
            if emails:
                lines = [f"- {e['from']}: {e['subject']}" for e in emails[:10]]
                sections.append(f"## Inbox ({len(emails)} emails in last 24h)\n" + "\n".join(lines))
        except Exception as e:
            sections.append(f"## Inbox\nUnable to fetch: {e}")

        # Slack unread summary
        try:
            report = self.scan_slack(days=1)
            if "No Slack" not in report:
                sections.append(f"## Slack\n{report}")
        except Exception as e:
            sections.append(f"## Slack\nUnable to fetch: {e}")

        # Open tickets
        try:
            tickets = self.scan_tickets(alias)
            if tickets and "No tickets" not in tickets and "Error" not in tickets:
                sections.append(f"## 🎫 Tickets\n{tickets}")
        except Exception:
            pass

        # Pending replies to agent-sent messages
        try:
            replies = self.check_replies()
            if replies and "no replies" not in replies.lower() and "No sent" not in replies:
                sections.append(replies)
        except Exception:
            pass

        return "\n\n".join(sections) if sections else "All clear — nothing urgent found."

    def _fetch_todos(self) -> str:
        """Fetch open to-do items across all lists."""
        return asyncio.run(self._fetch_todos_async())

    @staticmethod
    def _parse_todo_response(result) -> dict:
        """Parse MCP to-do response, handling both flat and nested content wrappers."""
        if not result or not result.content:
            return {}
        try:
            text = result.content[0].text
            data = json.loads(text)
            # Handle nested wrapper: {"content": [{"text": "..."}]}
            if "content" in data and isinstance(data["content"], list) and not "value" in data:
                inner = data["content"][0].get("text", "{}")
                data = json.loads(inner)
            return data
        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
            return {}

    async def _fetch_todos_async(self) -> str:
        try:
            async with self._outlook() as session:
                lists_result = await session.call_tool("todo_lists", arguments={"operation": "list"})
                lists_data = self._parse_todo_response(lists_result)
                all_lists = lists_data.get("value", [])
                if not all_lists:
                    return ""

                lines = []
                total = 0
                for lst in all_lists:
                    tasks_result = await session.call_tool("todo_tasks", arguments={
                        "operation": "list", "listId": lst["id"], "showCompleted": False
                    })
                    tasks_data = self._parse_todo_response(tasks_result)
                    open_tasks = tasks_data.get("value", [])
                    if open_tasks:
                        lines.append(f"**{lst['displayName']}** ({len(open_tasks)})")
                        for t in open_tasks[:5]:
                            due = ""
                            if t.get("dueDateTime"):
                                due = f" (due {t['dueDateTime'].get('dateTime', '')[:10]})"
                            imp = " 🔴" if t.get("importance") == "high" else ""
                            lines.append(f"  - {t.get('title', 'Untitled')}{due}{imp}")
                        if len(open_tasks) > 5:
                            lines.append(f"  - ...and {len(open_tasks) - 5} more")
                        total += len(open_tasks)

                if not lines:
                    return ""
                return f"## ✅ To-Do ({total} open)\n" + "\n".join(lines)
        except Exception:
            return ""

    # --- Calendar Review ---

    def review_calendar(self, view: str = "day", start_date: str = "", days_ahead: int = 1) -> str:
        """Fetch calendar events and AI-analyze for prep needs, cross-referencing email/Slack."""
        return asyncio.run(self._review_calendar_async(view, start_date, days_ahead))

    async def _review_calendar_async(self, view: str = "day", start_date: str = "", days_ahead: int = 1) -> str:
        raw, xref = await self._review_calendar_raw(view, start_date, days_ahead)
        if raw.startswith("No calendar"):
            return raw

        now_str = datetime.now().strftime('%I:%M %p').lstrip('0')
        period = "today" if view == "day" else f"next {days_ahead} days"

        prompt = f"""You are an executive assistant reviewing a calendar for {period}.
The current time is {now_str}. Events before this time have ALREADY HAPPENED — skip them unless ongoing. Focus on what's AHEAD.

Produce a briefing:
# Calendar Briefing — {period.title()}

## 🔴 Prep Required
[Meetings needing preparation — external calls, presentations, 1:1s with leadership]

## 📅 Today's Flow
[Chronological schedule with gaps noted, mark ongoing as "(NOW)"]

## ⚠️ Heads Up
[Conflicts, back-to-backs, tentative RSVPs, anything unusual]

## 📋 Context from Email/Slack
[Relevant email threads related to meetings]

Skip canceled events. Skip empty sections. Flag tentative RSVPs and external meetings.

Events:
{raw}

{f"Cross-reference from email:{xref}" if xref else ""}"""

        try:
            return self._invoke_ai(prompt, max_tokens=8000, tier="medium")
        except Exception as e:
            return f"# Calendar Briefing\n\n**Error:** {e}\n"

    async def _review_calendar_raw(self, view: str = "day", start_date: str = "", days_ahead: int = 1) -> tuple:
        """Return (event_block, xref_context) without AI call."""
        if not start_date:
            start_date = datetime.now().strftime('%m-%d-%Y')

        async with self._outlook() as session:
            args = {"view": view, "start_date": start_date}
            if view == "week":
                args["end_date"] = (datetime.now() + timedelta(days=days_ahead)).strftime('%m-%d-%Y')
            result = await session.call_tool("calendar_view", arguments=args)

            raw_text = result.content[0].text if result.content else "[]"
            try:
                outer = json.loads(raw_text)
                if isinstance(outer, dict) and "content" in outer:
                    events = json.loads(outer["content"][0]["text"])
                elif isinstance(outer, list):
                    events = outer
                else:
                    events = []
            except (json.JSONDecodeError, KeyError, IndexError):
                events = []

            if not events:
                return "No calendar events found for this period.", ""

            event_lines = []
            topics = []
            for e in events:
                subj = e.get('subject', 'No subject')
                start = e.get('start', '')
                end = e.get('end', '')
                canceled = e.get('isCanceled', False)
                flag = " [CANCELED]" if canceled else ""
                event_lines.append(
                    f"- {subj}{flag} | {start} → {end} | Location: {e.get('location', '')} | "
                    f"Organizer: {e.get('organizer', {}).get('name', '')} | Status: {e.get('status', '')} | "
                    f"RSVP: {e.get('response', '')} | AllDay: {e.get('isAllDay', False)}"
                )
                if not canceled and not e.get('isAllDay') and e.get('status') != 'Free':
                    topics.append(subj)

            # Cross-reference email for meeting topics (same session)
            xref = ""
            for term in topics[:5]:
                try:
                    r = await session.call_tool("email_search", arguments={"query": term[:60], "limit": 3})
                    found = self._parse_email_search_result(r)
                    if found:
                        xref += f"\nEmails matching '{term[:60]}':\n"
                        for em in found:
                            xref += f"  - {em['from']}: {em['subject']} ({em['date']})\n"
                except Exception:
                    pass

        return "\n".join(event_lines), xref

    # --- EA Communication ---

    def send_to_ea(self, message: str, ea_alias: str = None, category: str = "task") -> str:
        """Send a message to the user's EA via Slack (email fallback)."""
        return asyncio.run(self._send_to_ea_async(message, ea_alias, category))

    async def _send_to_ea_async(self, message: str, ea_alias: str = None, category: str = "task") -> str:
        ea_name = None
        if not ea_alias:
            # Try to read from attache.md
            attache_path = os.path.expanduser("~/.attache/attache.md")
            if os.path.exists(attache_path):
                for line in open(attache_path):
                    low = line.lower()
                    if "ea_alias" in low:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            ea_alias = parts[1].strip().strip("`").strip()
                    elif "ea_name" in low:
                        parts = line.split(":", 1)
                        if len(parts) == 2:
                            ea_name = parts[1].strip().strip("`").strip()
            if not ea_alias:
                return "ERROR: No EA alias configured. Run `attache init` or tell me your EA's name and login — I'll remember it."

        if not ea_name:
            ea_name = ea_alias.capitalize()

        cat_label = {
            "task": "📋 Task",
            "reminder": "⏰ Reminder",
            "request": "🙏 Request",
            "question": "❓ Question",
            "note": "📝 Note",
        }.get(category.lower(), "📋 Task")

        user = os.environ.get("USER", "unknown")
        agent_name = self.agent_name()
        track_tag = self._make_tag()

        formatted = f"Hey {ea_name}! 🔏 *From {user.capitalize()}'s {agent_name}* — {cat_label}\n\n{message}\n\n`{track_tag}`"

        # Try Slack first
        try:
            async with self._slack() as session:
                dm_result = await session.call_tool("open_conversation", arguments={"users": [ea_alias]})
                dm_data = json.loads(dm_result.content[0].text) if dm_result.content else {}
                channel_id = dm_data.get("channelId") or dm_data.get("channel", {}).get("id")
                if not channel_id:
                    raise Exception("Could not open DM channel")
                await session.call_tool("post_message", arguments={"channelId": channel_id, "text": formatted})
                self._log_sent(track_tag, channel_id, ea_alias, "slack", message)
                return f"✅ Sent to {ea_name} via Slack DM ({track_tag}):\n\n> {cat_label}: {message}"
        except Exception as slack_err:
            # Fallback to email
            try:
                async with self._outlook() as session:
                    subject = f"[{agent_name}] {cat_label}: {message[:80]}"
                    body = f"<html><body><p>Hey {ea_name}!</p><p><b>🔏 From {user.capitalize()}'s {agent_name}</b> — {cat_label}</p><p>{message}</p><p style='color:#999;font-size:11px'>{track_tag}</p></body></html>"
                    await session.call_tool("email_send", arguments={"to": [f"{ea_alias}@amazon.com"], "subject": subject, "body": body})
                    self._log_sent(track_tag, "", ea_alias, "email", message)
                    return f"✅ Sent to {ea_name} via email ({track_tag}, Slack failed: {slack_err}):\n\n> {cat_label}: {message}"
            except Exception as email_err:
                return f"❌ Failed to reach {ea_name}. Slack: {slack_err} | Email: {email_err}"

    # --- Check for replies to agent-sent messages ---

    def check_replies(self) -> str:
        """Check Slack and email for replies to messages the agent sent."""
        return asyncio.run(self._check_replies_async())

    async def _check_replies_async(self) -> str:
        entries = self._load_sent()
        if not entries:
            return "No sent messages to check. I haven't sent anything yet."

        results = []
        slack_entries = [e for e in entries if e["medium"] == "slack" and e.get("channel")]
        email_entries = [e for e in entries if e["medium"] in ("email", "email_draft")]

        # Check Slack threads for replies
        if slack_entries:
            try:
                async with self._slack() as session:
                    for entry in slack_entries[-20:]:  # check last 20
                        try:
                            # Search for the tag in the channel to find the original message
                            search_result = await session.call_tool("search", arguments={
                                "query": entry["tag"]
                            })
                            search_text = str(search_result.content[0].text) if search_result.content else ""
                            if "thread_ts" in search_text or "reply" in search_text.lower():
                                results.append(f"💬 **Reply found** to message for {entry['recipient']} ({entry['tag']}): {entry['summary'][:80]}")
                            elif entry["tag"] in search_text:
                                # Found the message but check for thread replies
                                results.append(f"⏳ **No reply yet** from {entry['recipient']} — sent {entry['sent_at'][:10]}: {entry['summary'][:80]}")
                        except Exception:
                            pass
            except Exception:
                pass

        # Check email for replies
        if email_entries:
            try:
                async with self._outlook() as session:
                    for entry in email_entries[-20:]:
                        try:
                            search_result = await session.call_tool("email_search", arguments={
                                "query": entry["tag"], "limit": 5
                            })
                            found = self._parse_email_search_result(search_result)
                            if len(found) > 1:  # original + reply
                                results.append(f"📧 **Reply found** to email for {entry['recipient']} ({entry['tag']}): {entry['summary'][:80]}")
                            else:
                                results.append(f"⏳ **No reply yet** from {entry['recipient']} — sent {entry['sent_at'][:10]}: {entry['summary'][:80]}")
                        except Exception:
                            pass
            except Exception:
                pass

        if not results:
            return "Checked sent messages — no replies detected yet."
        return "## Reply Status\n" + "\n".join(results)

    # --- Find Available Times ---

    # --- Slack DM ---

    def send_slack_dm(self, recipient: str, message: str) -> str:
        """Send a Slack DM to anyone by their login/alias."""
        return asyncio.run(self._send_slack_dm_async(recipient, message))

    async def _send_slack_dm_async(self, recipient: str, message: str) -> str:
        track_tag = self._make_tag()
        tagged_msg = f"{message}\n\n`{track_tag}`"
        try:
            async with self._slack() as session:
                dm_result = await session.call_tool("open_conversation", arguments={"users": [recipient]})
                dm_data = json.loads(dm_result.content[0].text) if dm_result.content else {}
                channel_id = dm_data.get("channelId") or dm_data.get("channel", {}).get("id")
                if not channel_id:
                    raise Exception("Could not open DM channel")
                await session.call_tool("post_message", arguments={"channelId": channel_id, "text": tagged_msg})
                self._log_sent(track_tag, channel_id, recipient, "slack", message)
                return f"✅ Sent DM to {recipient} ({track_tag}):\n\n> {message}"
        except Exception as e:
            return f"❌ Failed to DM {recipient}: {e}"

    def find_available_times(self, attendees: List[str], duration_minutes: int = 30, days_ahead: int = 5) -> str:
        return asyncio.run(self._find_available_times_async(attendees, duration_minutes, days_ahead))

    async def _find_available_times_async(self, attendees: List[str], duration_minutes: int = 30, days_ahead: int = 5) -> str:
        start = datetime.now().strftime('%Y-%m-%d')
        end = (datetime.now() + timedelta(days=days_ahead)).strftime('%Y-%m-%d')
        try:
            async with self._outlook() as session:
                result = await session.call_tool("calendar_availability", arguments={
                    "users": attendees, "startDate": start, "endDate": end
                })
                return str(result.content[0].text) if result.content else "No availability data returned."
        except Exception as e:
            return f"Error checking availability: {e}"

    # --- Book Room ---

    def book_room(self, building: str, start_time: str, end_time: str) -> str:
        return asyncio.run(self._book_room_async(building, start_time, end_time))

    async def _book_room_async(self, building: str, start_time: str, end_time: str) -> str:
        try:
            async with self._outlook() as session:
                result = await session.call_tool("calendar_room_booking", arguments={
                    "building": building, "startTime": start_time, "endTime": end_time
                })
                return str(result.content[0].text) if result.content else "No rooms found."
        except Exception as e:
            return f"Error finding rooms: {e}"

    # --- Create Meeting ---

    def create_meeting(self, subject: str, start: str, end: str, attendees: List[str] = None, location: str = "", body: str = "") -> str:
        return asyncio.run(self._create_meeting_async(subject, start, end, attendees, location, body))

    async def _create_meeting_async(self, subject: str, start: str, end: str, attendees: List[str] = None, location: str = "", body: str = "") -> str:
        try:
            args = {"operation": "create", "subject": subject, "start": start, "end": end}
            if attendees:
                args["attendees"] = attendees
            if location:
                args["location"] = location
            if body:
                args["body"] = body
            async with self._outlook() as session:
                result = await session.call_tool("calendar_meeting", arguments=args)
                return str(result.content[0].text) if result.content else "Meeting created."
        except Exception as e:
            return f"Error creating meeting: {e}"

    # --- Mark Slack Read ---

    def mark_slack_read(self, channel_ids: List[str] = None) -> str:
        return asyncio.run(self._mark_slack_read_async(channel_ids))

    async def _mark_slack_read_async(self, channel_ids: List[str] = None) -> str:
        from datetime import timezone
        try:
            async with self._slack() as session:
                if not channel_ids:
                    result = await session.call_tool("list_channels", arguments={
                        "channelTypes": ["public_and_private"], "unreadOnly": True, "limit": 50
                    })
                    data = json.loads(result.content[0].text) if result.content else {}
                    channel_ids = [c['id'] for c in data.get('channels', [])]
                if not channel_ids:
                    return "No unread channels to mark."
                now_iso = datetime.now(timezone.utc).isoformat()
                channels = [{"channelId": cid, "tsIso": now_iso} for cid in channel_ids]
                await session.call_tool("batch_set_last_read", arguments={"channels": channels})
                return f"✅ Marked {len(channel_ids)} channels as read."
        except Exception as e:
            return f"Error marking channels read: {e}"

    # --- Search Slack ---

    def search_slack(self, query: str) -> str:
        return asyncio.run(self._search_slack_async(query))

    async def _search_slack_async(self, query: str) -> str:
        try:
            async with self._slack() as session:
                result = await session.call_tool("search", arguments={"query": query})
                return str(result.content[0].text) if result.content else "No results found."
        except Exception as e:
            return f"Error searching Slack: {e}"

    # --- Reply to Email ---

    def reply_to_email(self, conversation_id: str, body: str, reply_all: bool = False) -> str:
        return asyncio.run(self._reply_to_email_async(conversation_id, body, reply_all))

    async def _reply_to_email_async(self, conversation_id: str, body: str, reply_all: bool = False) -> str:
        track_tag = self._make_tag()
        tagged_body = f"{body}<p style='color:#999;font-size:11px'>{track_tag}</p>"
        try:
            async with self._outlook() as session:
                read_result = await session.call_tool("email_read", arguments={
                    "conversationId": conversation_id, "format": "text"
                })
                read_data = json.loads(read_result.content[0].text) if read_result.content else {}
                items = []
                if isinstance(read_data, dict):
                    content = read_data.get("content", read_data)
                    if isinstance(content, dict):
                        items = content.get("items", content.get("emails", []))
                        if not items and "itemId" in content:
                            items = [content]
                if not items:
                    return "Could not find email to reply to."
                latest = items[-1] if isinstance(items, list) else items
                item_id = latest.get("itemId", latest.get("id", ""))
                change_key = latest.get("itemChangeKey", latest.get("changeKey", ""))
                if not item_id:
                    return "Could not extract email item ID."
                await session.call_tool("email_reply", arguments={
                    "itemId": item_id, "itemChangeKey": change_key,
                    "body": tagged_body, "replyAll": reply_all
                })
                self._log_sent(track_tag, conversation_id, "", "email", body[:200])
                return f"✅ Reply sent ({track_tag})."
        except Exception as e:
            return f"Error replying: {e}"

    # --- Draft Email ---

    def draft_email(self, to: List[str], subject: str, body: str) -> str:
        return asyncio.run(self._draft_email_async(to, subject, body))

    async def _draft_email_async(self, to: List[str], subject: str, body: str) -> str:
        track_tag = self._make_tag()
        tagged_body = f"{body}<p style='color:#999;font-size:11px'>{track_tag}</p>"
        try:
            async with self._outlook() as session:
                await session.call_tool("email_draft", arguments={
                    "operation": "create", "to": to, "subject": subject, "body": tagged_body
                })
                self._log_sent(track_tag, "", ", ".join(to), "email_draft", subject)
                return f"✅ Draft created ({track_tag}): {subject}"
        except Exception as e:
            return f"Error creating draft: {e}"

    # --- Todo Subtasks ---

    def add_todo_subtasks(self, list_name: str, task_title: str, subtasks: List[str]) -> str:
        return asyncio.run(self._add_todo_subtasks_async(list_name, task_title, subtasks))

    async def _add_todo_subtasks_async(self, list_name: str, task_title: str, subtasks: List[str]) -> str:
        try:
            async with self._outlook() as session:
                lists_result = await session.call_tool("todo_lists", arguments={"operation": "list"})
                lists_data = json.loads(lists_result.content[0].text) if lists_result.content else {}
                list_id = None
                for lst in lists_data.get("value", []):
                    if lst["displayName"].lower() == list_name.lower():
                        list_id = lst["id"]
                        break
                if not list_id:
                    return f"List '{list_name}' not found."
                tasks_result = await session.call_tool("todo_tasks", arguments={"operation": "list", "listId": list_id})
                tasks_data = json.loads(tasks_result.content[0].text) if tasks_result.content else {}
                task_id = None
                for t in tasks_data.get("value", []):
                    if task_title.lower() in t.get("title", "").lower():
                        task_id = t["id"]
                        break
                if not task_id:
                    return f"Task '{task_title}' not found in '{list_name}'."
                for sub in subtasks:
                    await session.call_tool("todo_checklist", arguments={
                        "operation": "create", "listId": list_id, "taskId": task_id, "displayName": sub
                    })
                return f"✅ Added {len(subtasks)} subtasks to '{task_title}'."
        except Exception as e:
            return f"Error adding subtasks: {e}"

    # --- Ticket Scan ---

    def scan_tickets(self, alias: str = "") -> str:
        return asyncio.run(self._scan_tickets_async(alias))

    async def _scan_tickets_async(self, alias: str = "") -> str:
        alias = alias or os.getenv("USER", "")
        try:
            async with self._builder() as session:
                result = await session.call_tool("TicketingReadActions", arguments={
                    "action": "search-tickets",
                    "input": {
                        "status": ["Assigned", "Researching", "Work In Progress"],
                        "sort": "lastUpdatedDate desc",
                        "rows": 20,
                        "responseFields": ["id", "title", "status", "extensions.tt.assignedGroup",
                                           "extensions.tt.impact", "createDate", "lastUpdatedDate"]
                    }
                })
                raw = str(result.content[0].text) if result.content else "No tickets found."
                if len(raw) < 50:
                    return raw
                prompt = f"""Summarize these open tickets for {alias}. Group by severity/impact.
Flag anything sev-2 or higher. Note stale tickets (no update in 7+ days).
Format as a brief report with action items.

Tickets:
{raw[:8000]}"""
                return self._invoke_ai(prompt, max_tokens=6000, tier="light")
        except Exception as e:
            return f"Error scanning tickets: {e}"

    # --- EOD Summary ---

    def eod_summary(self, alias: str = "") -> str:
        alias = alias or os.getenv("USER", "")
        sections = []
        try:
            raw_cal, _ = asyncio.run(self._review_calendar_raw(view="day"))
            if not raw_cal.startswith("No calendar"):
                sections.append(f"Calendar:\n{raw_cal}")
        except Exception:
            pass
        try:
            emails = self.fetch_inbox_emails(days=1, limit=50)
            if emails:
                sections.append(f"Emails today: {len(emails)}\n" + "\n".join(
                    f"- {e['from']}: {e['subject']}" for e in emails[:15]))
        except Exception:
            pass
        try:
            sections.append(self._fetch_todos())
        except Exception:
            pass
        combined = "\n\n".join(s for s in sections if s)
        if not combined:
            return "No activity data found for today."
        prompt = f"""Generate an end-of-day summary for {alias}. Current time: {datetime.now().strftime('%I:%M %p')}.

Produce:
# End of Day Summary
## ✅ What Got Done
## 🔄 Still In Progress
## 📋 Tomorrow's Prep
## 💡 Notes

Data:
{combined[:10000]}"""
        try:
            return self._invoke_ai(prompt, max_tokens=8000)
        except Exception as e:
            return f"Error generating EOD summary: {e}"

    # --- Weekly Review ---

    def todo_review(self, alias: str = "") -> str:
        """Pull all open to-dos, cross-reference with email/Slack/calendar, and suggest a burndown plan."""
        alias = alias or os.getenv("USER", "")
        sections = []

        # 1. Fetch full to-do details
        todos_raw = asyncio.run(self._fetch_todos_full())
        if not todos_raw:
            return "No open to-do items found."
        sections.append(f"To-Do Items:\n{todos_raw}")

        # 2. Cross-reference: recent emails
        try:
            emails = self.fetch_inbox_emails(days=7, limit=50)
            if emails:
                sections.append("Recent Emails:\n" + "\n".join(
                    f"- {e['from']}: {e['subject']}" for e in emails[:20]))
        except Exception:
            pass

        # 3. Cross-reference: Slack
        try:
            slack_data = self.scan_slack(days=3)
            if slack_data:
                sections.append(f"Recent Slack:\n{slack_data[:3000]}")
        except Exception:
            pass

        # 4. Cross-reference: upcoming calendar
        try:
            raw_cal, _ = asyncio.run(self._review_calendar_raw(view="week", days_ahead=5))
            if not raw_cal.startswith("No calendar"):
                sections.append(f"Upcoming Calendar:\n{raw_cal}")
        except Exception:
            pass

        combined = "\n\n".join(s for s in sections if s)
        prompt = f"""Review the to-do list for {alias} and create an actionable burndown plan.

Cross-reference each to-do item with the email, Slack, and calendar data to find related context.

Produce:
# To-Do Burndown Plan

## 🔥 Do Now (has related email/Slack waiting or meeting coming up)
For each item: the to-do, why it's urgent (cite the email/Slack/meeting), and a concrete next action.

## 📅 Schedule This Week
Items that map to upcoming meetings or deadlines.

## 🧹 Quick Wins (< 15 min)
Small items that can be knocked out fast.

## 🗑️ Consider Closing
Stale items with no recent activity in email/Slack/calendar — suggest closing or deferring.

## 📊 Summary
Total open items, how many are actionable now, estimated time to clear the list.

Data:
{combined[:12000]}"""
        try:
            return self._invoke_ai(prompt, max_tokens=8000)
        except Exception as e:
            return f"Error generating to-do review: {e}"

    async def _fetch_todos_full(self) -> str:
        """Fetch open to-do items with full details including body/notes."""
        try:
            async with self._outlook() as session:
                lists_result = await session.call_tool("todo_lists", arguments={"operation": "list"})
                lists_data = self._parse_todo_response(lists_result)
                all_lists = lists_data.get("value", [])
                if not all_lists:
                    return ""

                lines = []
                for lst in all_lists:
                    tasks_result = await session.call_tool("todo_tasks", arguments={
                        "operation": "list", "listId": lst["id"], "showCompleted": False
                    })
                    tasks_data = self._parse_todo_response(tasks_result)
                    open_tasks = tasks_data.get("value", [])
                    if open_tasks:
                        lines.append(f"\n**{lst['displayName']}**")
                        for t in open_tasks:
                            due = ""
                            if t.get("dueDateTime"):
                                due = f" | due {t['dueDateTime'].get('dateTime', '')[:10]}"
                            imp = " | HIGH" if t.get("importance") == "high" else ""
                            # Try to get body from list response; fetch individually if missing
                            body = ""
                            body_content = t.get("body", {}).get("content", "")
                            if not body_content and t.get("id"):
                                try:
                                    detail = await session.call_tool("todo_tasks", arguments={
                                        "operation": "get", "listId": lst["id"], "taskId": t["id"]
                                    })
                                    detail_data = self._parse_todo_response(detail)
                                    body_content = detail_data.get("body", {}).get("content", "")
                                except Exception:
                                    pass
                            if body_content:
                                body = f" | notes: {body_content[:200]}"
                            lines.append(f"  - {t.get('title', 'Untitled')}{due}{imp}{body}")
                return "\n".join(lines)
        except Exception:
            return ""

    # --- Weekly Review ---

    def weekly_review(self, alias: str = "") -> str:
        alias = alias or os.getenv("USER", "")
        sections = []
        try:
            raw_cal, _ = asyncio.run(self._review_calendar_raw(
                view="week", days_ahead=0,
                start_date=(datetime.now() - timedelta(days=7)).strftime('%m-%d-%Y')))
            if not raw_cal.startswith("No calendar"):
                sections.append(f"Calendar this week:\n{raw_cal}")
        except Exception:
            pass
        try:
            emails = self.fetch_inbox_emails(days=7, limit=100)
            if emails:
                sections.append(f"Emails this week: {len(emails)}\n" + "\n".join(
                    f"- {e['from']}: {e['subject']}" for e in emails[:20]))
        except Exception:
            pass
        try:
            sections.append(self._fetch_todos())
        except Exception:
            pass
        combined = "\n\n".join(s for s in sections if s)
        if not combined:
            return "No activity data found for this week."
        prompt = f"""Generate a weekly review for {alias}.

Produce:
# Weekly Review
## 📊 By the Numbers
## 🏆 Key Accomplishments
## 🔄 Carried Forward
## 📈 Patterns & Observations
## 🎯 Next Week Focus

Data:
{combined[:12000]}"""
        try:
            return self._invoke_ai(prompt, max_tokens=10000)
        except Exception as e:
            return f"Error generating weekly review: {e}"

    # --- Memory Persistence ---

    MEMORY_DIR = os.path.expanduser("~/.attache/memory")
    MEMORY_TODAY = os.path.join(MEMORY_DIR, "today.jsonl")
    MEMORY_DAYS_DIR = os.path.join(MEMORY_DIR, "days")
    MEMORY_MONTHLY = os.path.join(MEMORY_DIR, "monthly.json")
    MAX_ENTRY_LEN = 500
    DAILY_SUMMARY_MAX = 600
    MONTHLY_MAX = 2500
    KEEP_DAYS = 7
    KEEP_WEEKS = 4

    def _ensure_memory_dirs(self):
        os.makedirs(self.MEMORY_DAYS_DIR, exist_ok=True)

    def remember(self, text: str, entry_type: str = "action") -> str:
        """Append a memory entry for today."""
        self._ensure_memory_dirs()
        self._compact_if_new_day()
        entry = json.dumps({
            "ts": datetime.now().isoformat(),
            "type": entry_type,
            "text": text[:self.MAX_ENTRY_LEN],
        })
        with open(self.MEMORY_TODAY, "a") as f:
            f.write(entry + "\n")
        return f"Remembered: {text[:80]}"

    def recall(self) -> str:
        """Build memory context for system prompt injection."""
        self._ensure_memory_dirs()
        self._compact_if_new_day()
        sections = []

        # Monthly summary
        if os.path.exists(self.MEMORY_MONTHLY):
            try:
                data = json.loads(open(self.MEMORY_MONTHLY).read())
                if data.get("text"):
                    sections.append(f"### This month (patterns & threads)\n{data['text']}")
            except (json.JSONDecodeError, KeyError):
                pass

        # Daily summaries (last 7 days, newest last)
        day_lines = []
        today_str = datetime.now().strftime("%Y-%m-%d")
        for i in range(self.KEEP_DAYS, 0, -1):
            day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            path = os.path.join(self.MEMORY_DAYS_DIR, f"{day}.json")
            if os.path.exists(path):
                try:
                    data = json.loads(open(path).read())
                    label = "Yesterday" if i == 1 else (datetime.now() - timedelta(days=i)).strftime("%a %b %d")
                    day_lines.append(f"- {label}: {data.get('text', '(empty)')}")
                except (json.JSONDecodeError, KeyError):
                    pass
        if day_lines:
            sections.append("### This week\n" + "\n".join(day_lines))

        # Today's raw entries
        if os.path.exists(self.MEMORY_TODAY):
            try:
                entries = [json.loads(l) for l in open(self.MEMORY_TODAY) if l.strip()]
                if entries:
                    today_lines = []
                    for e in entries:
                        ts = e.get("ts", "")
                        try:
                            t = datetime.fromisoformat(ts).strftime("%H:%M")
                        except Exception:
                            t = "?"
                        today_lines.append(f"- {t} {e.get('text', '')}")
                    sections.append("### Today so far\n" + "\n".join(today_lines))
            except Exception:
                pass

        if not sections:
            return ""
        return "## Memory\n\n" + "\n\n".join(sections)

    def _compact_if_new_day(self):
        """If today.jsonl is from a previous day, compress it and rotate."""
        if not os.path.exists(self.MEMORY_TODAY):
            return
        try:
            first_line = open(self.MEMORY_TODAY).readline().strip()
            if not first_line:
                return
            first_entry = json.loads(first_line)
            entry_date = first_entry["ts"][:10]
            today_str = datetime.now().strftime("%Y-%m-%d")
            if entry_date == today_str:
                return
            # Yesterday's entries need compaction
            entries = [json.loads(l) for l in open(self.MEMORY_TODAY) if l.strip()]
            self._compress_day(entry_date, entries)
            os.remove(self.MEMORY_TODAY)
            self._prune_old_days()
        except Exception:
            pass

    def _compress_day(self, date_str: str, entries: list):
        """AI-compress a day's raw entries into a summary."""
        raw = "\n".join(f"- {e.get('ts', '')[11:16]} [{e.get('type','')}] {e.get('text','')}" for e in entries)
        try:
            summary = self._invoke_ai(
                f"Compress this day's activity log into a single concise paragraph (max 500 chars). "
                f"Focus on: key actions taken, decisions made, unresolved items, and people involved. "
                f"No headers or bullets — just a dense narrative summary.\n\nDate: {date_str}\n\n{raw[:4000]}",
                max_tokens=300, tier="memory"
            )
        except Exception:
            summary = f"{len(entries)} entries logged."
        path = os.path.join(self.MEMORY_DAYS_DIR, f"{date_str}.json")
        with open(path, "w") as f:
            json.dump({"date": date_str, "text": summary[:self.DAILY_SUMMARY_MAX]}, f)

    def _prune_old_days(self):
        """Remove daily summaries older than KEEP_DAYS, folding them into monthly first."""
        cutoff = (datetime.now() - timedelta(days=self.KEEP_DAYS)).strftime("%Y-%m-%d")
        expiring = []
        for fname in sorted(os.listdir(self.MEMORY_DAYS_DIR)):
            if fname.endswith(".json") and fname[:10] < cutoff:
                path = os.path.join(self.MEMORY_DAYS_DIR, fname)
                try:
                    expiring.append(json.loads(open(path).read()))
                except Exception:
                    pass
                os.remove(path)
        if expiring:
            self._fold_into_monthly(expiring)

    def _fold_into_monthly(self, expiring_days: list):
        """Fold expiring daily summaries into the monthly rolling summary."""
        existing = ""
        if os.path.exists(self.MEMORY_MONTHLY):
            try:
                existing = json.loads(open(self.MEMORY_MONTHLY).read()).get("text", "")
            except Exception:
                pass
        new_entries = "\n".join(f"- {d.get('date','')}: {d.get('text','')}" for d in expiring_days)
        cutoff_date = (datetime.now() - timedelta(weeks=self.KEEP_WEEKS)).strftime("%Y-%m-%d")
        try:
            summary = self._invoke_ai(
                f"Update this rolling monthly memory summary. Drop anything before {cutoff_date}. "
                f"Keep: recurring patterns, ongoing threads, key people, unresolved items, user preferences. "
                f"Max 2000 chars, dense narrative, no headers.\n\n"
                f"Existing monthly summary:\n{existing or '(none yet)'}\n\n"
                f"New days to fold in:\n{new_entries}",
                max_tokens=1000, tier="memory"
            )
        except Exception:
            summary = existing + "\n" + new_entries if existing else new_entries
        with open(self.MEMORY_MONTHLY, "w") as f:
            json.dump({
                "updated": datetime.now().isoformat(),
                "text": summary[:self.MONTHLY_MAX],
            }, f)
