"""Email agent — Outlook fetch, search, read, send, reply, classify, delete, flag, attachments."""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict

from envoy_logger import get_logger
from agents.base import (
    outlook, invoke_ai, agent_name, make_tag, log_sent,
    parse_email_search_result,
)


async def read_full_thread(conversation_id: str, session=None) -> str:
    """Read full email thread body as markdown text."""
    async def _read(s):
        result = await s.call_tool("email_read", arguments={
            "conversationId": conversation_id, "format": "markdown"
        })
        return str(result.content[0].text) if result.content else ""
    if session:
        return await _read(session)
    async with outlook() as s:
        return await _read(s)


async def get_attachments(item_id: str, session=None) -> str:
    """Download and return attachment metadata for an email item."""
    async def _fetch(s):
        result = await s.call_tool("email_attachments", arguments={"attachmentId": item_id})
        return str(result.content[0].text) if result.content else ""
    try:
        if session:
            return await _fetch(session)
        async with outlook() as s:
            return await _fetch(s)
    except Exception:
        return ""


async def flag_email(item_id: str, item_change_key: str, status: str = "Flagged",
                     due_date: str = "", categories: List[str] = None,
                     importance: str = "", session=None) -> str:
    """Flag, categorize, or set importance on an email."""
    async def _update(s):
        args = {"itemId": item_id, "itemChangeKey": item_change_key}
        if status:
            flag_args = {"status": status}
            if due_date:
                flag_args["dueDate"] = due_date
            args["flag"] = flag_args
        if categories is not None:
            args["categories"] = categories
        if importance:
            args["importance"] = importance
        result = await s.call_tool("email_update", arguments=args)
        return str(result.content[0].text) if result.content else "Updated."
    try:
        if session:
            return await _update(session)
        async with outlook() as s:
            return await _update(s)
    except Exception as e:
        return f"Error updating email: {e}"


async def get_contacts(query: str = "", limit: int = 20) -> str:
    """Search email contacts."""
    try:
        async with outlook() as session:
            args = {}
            if query:
                args["query"] = query
            if limit:
                args["limit"] = limit
            result = await session.call_tool("email_contacts", arguments=args)
            return str(result.content[0].text) if result.content else "No contacts found."
    except Exception as e:
        return f"Error fetching contacts: {e}"


async def get_categories() -> List[str]:
    """Get available email categories."""
    try:
        async with outlook() as session:
            result = await session.call_tool("email_categories", arguments={})
            return json.loads(result.content[0].text) if result.content else []
    except Exception:
        return []


async def get_recent_emails(alias: str, days: int = 14, session=None) -> List[Dict]:
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    async def _fetch(s):
        result = await s.call_tool("email_search", arguments={
            "query": f"from:{alias}@amazon.com",
            "startDate": start_date, "endDate": end_date, "limit": 50
        })
        return parse_email_search_result(result)

    if session:
        return await _fetch(session)
    async with outlook() as s:
        return await _fetch(s)


async def fetch_inbox(days: int = 14, limit: int = 100) -> List[Dict]:
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    async with outlook() as session:
        result = await session.call_tool("email_search", arguments={
            "query": "*", "folder": "inbox",
            "startDate": start_date, "endDate": end_date, "limit": limit
        })
        return parse_email_search_result(result)


def classify_emails(emails: List[Dict], user_alias: str) -> List[Dict]:
    if not emails:
        return []
    try:
        # Read full bodies for emails where preview is ambiguous (batch up to 20)
        from agents.base import run
        async def _enrich():
            async with outlook() as session:
                for e in emails[:20]:
                    if e.get('conversationId') and len(e.get('snippet', '')) < 100:
                        try:
                            body = await read_full_thread(e['conversationId'], session)
                            if body:
                                e['full_body'] = body[:1000]
                        except Exception:
                            pass
        try:
            run(_enrich())
        except Exception:
            pass

        email_list = ""
        for i, e in enumerate(emails):
            body_text = e.get('full_body', e.get('snippet', ''))[:500]
            email_list += (
                f"[{i}] From: {e['from']} | To: {e['to']} | Subject: {e['subject']} | Date: {e['date']}\n"
                f"    Body: {body_text}\n\n"
            )
        prompt = f"""You are a conservative email triage assistant. The user is {user_alias}@amazon.com.

Classify each email as exactly one of:
- DELETE — ONLY truly junk: mass marketing, vendor newsletters, automated spam, external event promos, mass surveys. NOT if from a colleague or mentions user's team/projects.
- REVIEW — Routine automated notifications, very large distro list generics, old resolved threads.
- KEEP — Default. Anything from a person discussing work, CC'd discussions, org announcements, leadership comms, anything mentioning user/team/projects, anything uncertain.

CRITICAL: Be very conservative. Most work email has value. Only flag truly worthless email as DELETE.

For each email, output EXACTLY one line:
[index] CLASSIFICATION reason

Emails:
{email_list}"""
        ai_text = invoke_ai(prompt, max_tokens=8000, tier="light")
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
        get_logger().log_error(f"Error classifying emails: {e}")
        for em in emails:
            em['classification'] = 'KEEP'
            em['reason'] = f'Classification error: {e}'
        return emails


async def delete_emails(conversation_ids: List[str]) -> Dict[str, int]:
    results = {'deleted': 0, 'failed': 0}
    async with outlook() as session:
        for cid in conversation_ids:
            try:
                await session.call_tool("email_move", arguments={
                    "conversationId": cid, "targetFolder": "deleteditems"
                })
                results['deleted'] += 1
            except Exception:
                results['failed'] += 1
    return results


async def send_email(to: List[str], subject: str, body: str,
                     cc: List[str] = None, bcc: List[str] = None) -> str:
    track_tag = make_tag()
    tagged_body = f"{body}<p style='color:#999;font-size:11px'>{track_tag}</p>"
    try:
        async with outlook() as session:
            args = {"to": to, "subject": subject, "body": tagged_body}
            if cc:
                args["cc"] = cc
            if bcc:
                args["bcc"] = bcc
            await session.call_tool("email_send", arguments=args)
            log_sent(track_tag, "", to[0] if to else "", "email", body[:200])
            return f"✅ Email sent ({track_tag})."
    except Exception as e:
        return f"Error sending email: {e}"


async def draft_email(to: List[str], subject: str, body: str,
                      cc: List[str] = None, bcc: List[str] = None) -> str:
    track_tag = make_tag()
    tagged_body = f"{body}<p style='color:#999;font-size:11px'>{track_tag}</p>"
    try:
        async with outlook() as session:
            args = {"operation": "create", "to": to, "subject": subject, "body": tagged_body}
            if cc:
                args["cc"] = cc
            if bcc:
                args["bcc"] = bcc
            await session.call_tool("email_draft", arguments=args)
            log_sent(track_tag, "", to[0] if to else "", "email_draft", body[:200])
            return f"✅ Draft created ({track_tag})."
    except Exception as e:
        return f"Error creating draft: {e}"


async def reply_to_email(conversation_id: str, body: str, reply_all: bool = False) -> str:
    track_tag = make_tag()
    tagged_body = f"{body}<p style='color:#999;font-size:11px'>{track_tag}</p>"
    try:
        async with outlook() as session:
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
            log_sent(track_tag, conversation_id, "", "email", body[:200])
            return f"✅ Reply sent ({track_tag})."
    except Exception as e:
        return f"Error replying: {e}"


async def email_digest(digest: str, manager_alias: str, days: int, include_summary: bool = False) -> bool:
    async with outlook() as session:
        html_body = _markdown_to_html(digest)
        subject = f"{agent_name()}: {'AI ' if include_summary else ''}Team Digest - Last {days} Days"

        # Try to find an existing thread to reply to instead of creating a new email
        try:
            search_result = await session.call_tool("email_search", arguments={
                "query": subject, "folder": "sentitems", "limit": 1
            })
            existing = parse_email_search_result(search_result)
            if existing:
                read_result = await session.call_tool("email_read", arguments={
                    "conversationId": existing[0]['conversationId'], "format": "text"
                })
                read_data = json.loads(read_result.content[0].text) if read_result.content else {}
                content = read_data.get("content", read_data) if isinstance(read_data, dict) else {}
                items = content.get("items", content.get("emails", [])) if isinstance(content, dict) else []
                if not items and isinstance(content, dict) and "itemId" in content:
                    items = [content]
                if items:
                    latest = items[-1] if isinstance(items, list) else items
                    item_id = latest.get("itemId", latest.get("id", ""))
                    change_key = latest.get("itemChangeKey", latest.get("changeKey", ""))
                    if item_id and change_key:
                        result = await session.call_tool("email_reply", arguments={
                            "itemId": item_id, "itemChangeKey": change_key,
                            "body": html_body, "replyAll": False
                        })
                        return not result.isError
        except Exception:
            pass  # Fall through to send new email

        result = await session.call_tool("email_send", arguments={
            "to": [f"{manager_alias}@amazon.com"],
            "subject": subject, "body": html_body
        })
        return not result.isError


async def scan_customer_emails(alias: str, days: int = 14, team_aliases: List[str] = None) -> str:
    all_aliases = [alias] + (team_aliases or [])
    all_emails = []
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')

    async with outlook() as session:
        for person in all_aliases:
            get_logger().log_info(f"Scanning external emails for {person}...")
            print(f"Scanning external emails for {person}...")
            result = await session.call_tool("email_search", arguments={
                "query": f"to:{person}@amazon.com",
                "startDate": start_date, "endDate": end_date, "limit": 50
            })
            emails = parse_email_search_result(result)
            for e in emails:
                if 'amazon.com' not in e['from'].lower():
                    e['recipient'] = person
                    all_emails.append(e)

    if not all_emails:
        return "No external customer emails found."

    email_list = ""
    for i, e in enumerate(all_emails):
        email_list += f"[{i}] To: {e['recipient']} | From: {e['from']} | Subject: {e['subject']} | Date: {e['date']} | Preview: {e['snippet'][:200]}\n"

    prompt = f"""You are analyzing external customer emails sent to an Amazon team.
The manager is {alias}@amazon.com. Team members: {', '.join(all_aliases)}.

Produce a report:
# Customer Email Report
**Period:** Last {days} days | **Scanned:** {len(all_emails)} external emails

## 🔴 Action Required
- **[Subject]** from [sender] → [recipient] ([date]) — [what action is needed]

## ⚠️ Follow-Up Recommended
- **[Subject]** from [sender] → [recipient] ([date]) — [why]

## 📋 FYI / No Action
- **[Subject]** from [sender] → [recipient] ([date]) — [brief note]

## Summary
[2-3 sentences]

Skip empty sections. Flag time-sensitive items. Only include emails from last {days} days.

Emails:
{email_list}"""
    try:
        return invoke_ai(prompt, tier="heavy")
    except Exception as e:
        return f"# Customer Email Report\n\n**Error:** {e}\n"


async def check_replies() -> str:
    from agents.base import load_sent
    entries = load_sent()
    if not entries:
        return "No sent messages to check."

    results = []
    email_entries = [e for e in entries if e["medium"] in ("email", "email_draft")]
    if email_entries:
        try:
            async with outlook() as session:
                for entry in email_entries[-20:]:
                    try:
                        search_result = await session.call_tool("email_search", arguments={
                            "query": entry["tag"], "limit": 5
                        })
                        found = parse_email_search_result(search_result)
                        if len(found) > 1:
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


def _markdown_to_html(md_text: str) -> str:
    """Simple markdown to HTML conversion."""
    html = "<html><body style='font-family: Arial, sans-serif;'>"
    for line in md_text.split('\n'):
        if line.startswith('# '):
            html += f"<h1>{line[2:]}</h1>"
        elif line.startswith('## '):
            html += f"<h2>{line[3:]}</h2>"
        elif line.startswith('### '):
            html += f"<h3>{line[4:]}</h3>"
        elif line.startswith('- '):
            html += f"<li>{line[2:]}</li>"
        elif line.startswith('---'):
            html += "<hr>"
        elif line.startswith('**') and line.endswith('**'):
            html += f"<p><strong>{line[2:-2]}</strong></p>"
        elif line.strip():
            html += f"<p>{line}</p>"
    html += "</body></html>"
    return html


async def move_to_folder(conversation_ids: List[str], target_folder: str) -> Dict[str, int]:
    """Move emails to a folder. Folders: archive, inbox, deleteditems, sentitems, or a folder ID."""
    results = {'moved': 0, 'failed': 0}
    async with outlook() as session:
        for cid in conversation_ids:
            try:
                await session.call_tool("email_move", arguments={
                    "conversationId": cid, "targetFolder": target_folder
                })
                results['moved'] += 1
            except Exception:
                results['failed'] += 1
    return results


async def mark_read(conversation_id: str, mark_as: str = "read") -> str:
    """Mark an email as read or unread."""
    async with outlook() as session:
        result = await session.call_tool("email_read", arguments={
            "conversationId": conversation_id, "markAs": mark_as
        })
        return f"✅ Marked {mark_as}."
