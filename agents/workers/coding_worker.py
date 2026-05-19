"""Coding worker — delegates coding tasks to Claude Code (or Kiro) as an autonomous agent."""

import os
import shutil
import subprocess
import sys

from strands import Agent, tool
from agents.workers import _model


def _find_cli() -> tuple[str, str]:
    """Find the best available coding CLI. Returns (path, name)."""
    for name in ("kiro-cli", "claude"):
        path = shutil.which(name)
        if path:
            return path, name
    return "", ""


def create(session_mgr=None):

    @tool
    def run_coding_agent(task: str, working_directory: str = "", allow_edits: bool = True) -> str:
        """Run an autonomous coding agent (Claude Code or Kiro) to completion on a task.
        The agent can read/write files, run commands, and iterate until done.
        Use for: writing code, fixing bugs, refactoring, creating files, running tests,
        generating scripts, code review, or any development task.

        Args:
            task: Detailed description of the coding task to accomplish
            working_directory: Directory to run in (default: current directory)
            allow_edits: Whether the agent may edit files (default: True). Set False for read-only analysis.
        """
        cli_path, cli_name = _find_cli()
        if not cli_path:
            return "⚠️ No coding CLI found. Install Claude Code (`claude`) or Kiro (`kiro`) and ensure it's in PATH."

        cwd = working_directory or os.getcwd()
        if not os.path.isdir(cwd):
            return f"⚠️ Directory not found: {cwd}"

        # Build command — non-interactive, autonomous
        cmd = [cli_path]
        if cli_name == "kiro-cli":
            cmd.extend(["chat", "--no-interactive"])
            if allow_edits:
                cmd.append("--trust-all-tools")
            cmd.append(task)
        else:
            # claude CLI
            cmd.append("--print")
            if allow_edits:
                cmd.append("--dangerously-skip-permissions")
            else:
                cmd.extend(["--permission-mode", "plan"])
            cmd.append(task)

        print(f"[coding] Delegating to {cli_name}: {task[:120]}...", file=sys.stderr)

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout
            )
            output = result.stdout.strip()
            if result.returncode != 0 and result.stderr:
                output += f"\n\n⚠️ stderr: {result.stderr.strip()[-500:]}"
            if not output:
                output = "(Agent completed with no output)"
            # Truncate very long output to avoid blowing context
            if len(output) > 12000:
                output = output[:6000] + "\n\n... [truncated] ...\n\n" + output[-4000:]
            return f"✅ [{cli_name}] completed:\n\n{output}"
        except subprocess.TimeoutExpired:
            return f"⚠️ [{cli_name}] timed out after 10 minutes. The task may be too large — try breaking it into smaller steps."
        except Exception as e:
            return f"⚠️ [{cli_name}] failed: {e}"

    @tool
    def shared_context(operation: str = "read", key: str = "", value: str = "") -> str:
        """Read or post shared context visible to all workers.
        Args:
            operation: 'read' to get context, 'post' to share
            key: Context key
            value: Context value (for post)
        """
        from agents.workers import read_context, post_context
        if operation == "post" and key:
            post_context(key, value, source="coding")
            return f"Posted to shared context: {key}"
        return read_context(key)

    cli_path, cli_name = _find_cli()
    cli_status = f"Using {cli_name} at {cli_path}" if cli_path else "⚠️ No coding CLI found"

    return Agent(
        model=_model("medium"),
        system_prompt=f"""You are a coding specialist that delegates development tasks to an autonomous coding agent ({cli_status}).

When given a coding task, use run_coding_agent with a clear, detailed prompt. Include:
- What files to create or modify
- Expected behavior and edge cases
- Any constraints (language, framework, style)

For complex tasks, break them into sequential run_coding_agent calls.
Use shared_context to post results or read context from other workers.""",
        tools=[run_coding_agent, shared_context],
        callback_handler=None,
        **({"session_manager": session_mgr} if session_mgr else {}),
    )
