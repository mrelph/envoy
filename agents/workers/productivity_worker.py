"""Productivity worker — todos, tickets, memory, cron."""

from strands import Agent, tool
from agents.base import run
from agents.workers import _USER, _model


def create():
    from agents import todo as todo_mod, tickets as tix_mod, memory2 as mem_mod
    from agents import workflows as wf

    @tool
    def todo_items(operation: str = "list", items: str = "", list_name: str = "",
                   task_title: str = "", subtasks: str = "",
                   due_date: str = "", importance: str = "", new_title: str = "",
                   status: str = "", body: str = "") -> str:
        """Manage To-Do items — list, add, complete, update, delete, or add subtasks.
        Args:
            operation: list, add, complete, update, delete, subtasks, review
            items: Newline-separated items to add (for add)
            list_name: To-Do list name
            task_title: Task title (for complete/update/delete/subtasks)
            subtasks: Newline-separated subtask items
            due_date: Due date ISO format (for add/update)
            importance: low, normal, or high (for add/update)
            new_title: New title (for update)
            status: notStarted, inProgress, completed, waitingOnOthers, deferred (for update)
            body: Task body/notes (for add/update)
        """
        if operation == "review":
            return wf.todo_review(_USER)
        if operation == "add":
            action_items = []
            for l in items.split("\n"):
                l = l.strip()
                if not l:
                    continue
                item = {"title": l}
                if due_date: item["due_date"] = due_date
                if importance: item["importance"] = importance
                if body: item["body"] = body
                action_items.append(item)
            if not action_items:
                return "No items provided."
            ok = run(todo_mod.add_tasks(action_items, list_name or None))
            return f"Added {len(action_items)} items." if ok else "Failed to add items."
        if operation == "complete":
            return run(todo_mod.complete_task(list_name or "Envoy Action Items", task_title))
        if operation == "update":
            return run(todo_mod.update_task(
                list_name or "Envoy Action Items", task_title,
                new_title=new_title, due_date=due_date, importance=importance,
                status=status, body=body))
        if operation == "delete":
            return run(todo_mod.delete_task(list_name or "Envoy Action Items", task_title))
        if operation == "subtasks":
            sub_list = [s.strip() for s in subtasks.split("\n") if s.strip()]
            return run(todo_mod.add_subtasks(list_name, task_title, sub_list))
        return run(todo_mod.fetch_todos())

    @tool
    def tickets(alias: str = "") -> str:
        """Scan open tickets assigned to you or your team.
        Args:
            alias: Your alias (default: $USER)
        """
        return run(tix_mod.scan_tickets(alias or _USER))

    @tool
    def remember_item(text: str, entry_type: str = "action") -> str:
        """Save something to persistent memory.
        Args:
            text: What to remember
            entry_type: action, context, or decision
        """
        return mem_mod.remember(text, entry_type)

    @tool
    def cron_jobs(action: str = "list", name: str = "", schedule: str = "", command: str = "") -> str:
        """Manage scheduled cron jobs.
        Args:
            action: list, add, remove, presets
            name: Job name
            schedule: Cron expression
            command: Envoy command
        """
        from tools import manage_cron
        return manage_cron(action=action, name=name, schedule=schedule, command=command)

    return Agent(
        model=_model("medium"),
        system_prompt="You are a productivity specialist. You manage to-dos (list, add with due dates/importance, complete, update, delete), scan tickets, maintain memory, and manage cron jobs. For briefings, EOD summaries, and weekly reviews, tell the user to use /briefing, /eod, or /weekly commands. Be action-oriented.",
        tools=[todo_items, tickets, remember_item, cron_jobs],
        callback_handler=None,
    )
