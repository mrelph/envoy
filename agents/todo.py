"""Todo agent — list, create, update, review tasks."""

import json
from typing import List, Dict

from agents.base import outlook, parse_todo_response


async def fetch_todos() -> str:
    """Fetch open to-do items as a formatted string."""
    try:
        async with outlook() as session:
            lists_result = await session.call_tool("todo_lists", arguments={"operation": "list"})
            lists_data = parse_todo_response(lists_result)
            all_lists = lists_data.get("value", [])
            if not all_lists:
                return ""
            lines = []
            for lst in all_lists:
                tasks_result = await session.call_tool("todo_tasks", arguments={
                    "operation": "list", "listId": lst["id"]
                })
                tasks_data = parse_todo_response(tasks_result)
                tasks = tasks_data.get("value", [])
                open_tasks = [t for t in tasks if t.get("status") != "completed"]
                if open_tasks:
                    lines.append(f"## {lst['displayName']} ({len(open_tasks)} open)")
                    for t in open_tasks:
                        due = t.get("dueDateTime", {})
                        due_str = f" (due {due.get('dateTime', '')[:10]})" if due else ""
                        lines.append(f"- {t.get('title', '?')}{due_str}")
            return "\n".join(lines) if lines else ""
    except Exception as e:
        return f"Error fetching to-dos: {e}"


async def fetch_todos_full() -> str:
    """Fetch open to-do items with full details including body/notes."""
    try:
        async with outlook() as session:
            lists_result = await session.call_tool("todo_lists", arguments={"operation": "list"})
            lists_data = parse_todo_response(lists_result)
            all_lists = lists_data.get("value", [])
            if not all_lists:
                return ""
            lines = []
            for lst in all_lists:
                tasks_result = await session.call_tool("todo_tasks", arguments={
                    "operation": "list", "listId": lst["id"]
                })
                tasks_data = parse_todo_response(tasks_result)
                tasks = tasks_data.get("value", [])
                open_tasks = [t for t in tasks if t.get("status") != "completed"]
                if open_tasks:
                    lines.append(f"## {lst['displayName']} ({len(open_tasks)} open)")
                    for t in open_tasks:
                        due = t.get("dueDateTime", {})
                        due_str = f" | Due: {due.get('dateTime', '')[:10]}" if due else ""
                        body = t.get("body", {}).get("content", "")
                        body_str = f"\n  Notes: {body[:200]}" if body and body.strip() else ""
                        importance = t.get("importance", "normal")
                        imp_str = " ⚡" if importance == "high" else ""
                        lines.append(f"- {t.get('title', '?')}{imp_str}{due_str}{body_str}")
            return "\n".join(lines) if lines else ""
    except Exception as e:
        return f"Error fetching to-dos: {e}"


async def add_tasks(action_items: List[Dict[str, str]], list_name: str = None) -> bool:
    """Add action items as tasks to Microsoft To-Do."""
    list_name = list_name or "Envoy Action Items"
    try:
        async with outlook() as session:
            lists_result = await session.call_tool("todo_lists", arguments={"operation": "list"})
            lists_data = parse_todo_response(lists_result)
            list_id = None
            for lst in lists_data.get("value", []):
                if lst["displayName"].lower() == list_name.lower():
                    list_id = lst["id"]
                    break
            if not list_id:
                create_result = await session.call_tool("todo_lists", arguments={
                    "operation": "create", "displayName": list_name
                })
                create_data = parse_todo_response(create_result)
                list_id = create_data.get("id")
            if not list_id:
                return False
            for item in action_items:
                await session.call_tool("todo_tasks", arguments={
                    "operation": "create", "listId": list_id,
                    "title": item.get("title", "Action item"),
                    "body": item.get("owner", ""),
                })
            return True
    except Exception:
        return False


async def add_subtasks(list_name: str, task_title: str, subtasks: List[str]) -> str:
    try:
        async with outlook() as session:
            lists_result = await session.call_tool("todo_lists", arguments={"operation": "list"})
            lists_data = parse_todo_response(lists_result)
            list_id = None
            for lst in lists_data.get("value", []):
                if lst["displayName"].lower() == list_name.lower():
                    list_id = lst["id"]
                    break
            if not list_id:
                return f"List '{list_name}' not found."
            tasks_result = await session.call_tool("todo_tasks", arguments={
                "operation": "list", "listId": list_id
            })
            tasks_data = parse_todo_response(tasks_result)
            task_id = None
            for t in tasks_data.get("value", []):
                if task_title.lower() in t.get("title", "").lower():
                    task_id = t["id"]
                    break
            if not task_id:
                return f"Task '{task_title}' not found in '{list_name}'."
            for sub in subtasks:
                await session.call_tool("todo_checklist", arguments={
                    "operation": "create", "listId": list_id,
                    "taskId": task_id, "displayName": sub
                })
            return f"✅ Added {len(subtasks)} subtasks to '{task_title}'."
    except Exception as e:
        return f"Error adding subtasks: {e}"
