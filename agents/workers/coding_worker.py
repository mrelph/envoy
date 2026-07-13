"""Coding worker — runs an autonomous coding agent (Claude Code or Kiro) as a subprocess.

`run_coding_agent` used to be wrapped in a medium-tier Strands agent whose only
job was to re-prompt this same subprocess call (see M8 in
PROJECT-REVIEW-2026-07-06.md) — an extra LLM round-trip that added latency and
lost fidelity on the task description the supervisor had already written.
It's now exposed directly as the `coding_worker` tool in tools.py, which calls
`run_coding_agent` below with no intermediate agent. This module is no longer
registered as a worker in agents/workers/__init__.py.
"""

import os
import shutil
import subprocess
import sys
import time

# Subprocess timeout bounds. The per-request budget is ~120s, but coding tasks
# can legitimately exceed it; we still cap so the user is never stuck forever.
_CODING_MIN_TIMEOUT = 60
_CODING_MAX_TIMEOUT = 600


def _find_cli() -> tuple[str, str]:
    """Find the best available coding CLI. Returns (path, name)."""
    for name in ("kiro-cli", "claude"):
        path = shutil.which(name)
        if path:
            return path, name
    return "", ""


def run_coding_agent(task: str, working_directory: str = "", allow_edits: bool = False) -> str:
    """Run an autonomous coding agent (Claude Code or Kiro) to completion on a task.
    The agent can read files and, only if explicitly permitted, write files and run
    commands, iterating until done. Use for: writing code, fixing bugs, refactoring,
    creating files, running tests, generating scripts, code review, or any development task.

    Runs in read-only/plan mode by default. Edits, file writes, and shell commands
    require explicit allow_edits=True — only set that when the user has clearly asked
    for changes to be made, not just analyzed.

    Args:
        task: Detailed description of the coding task to accomplish
        working_directory: Directory to run in (default: current directory). Must be
            under an allow-listed directory (see local_files' allowed_dirs config).
        allow_edits: Whether the agent may edit files / run commands (default: False —
            read-only plan mode). Requires explicit allow_edits=True to permit edits.
    """
    cli_path, cli_name = _find_cli()
    if not cli_path:
        return "⚠️ No coding CLI found. Install Claude Code (`claude`) or Kiro (`kiro`) and ensure it's in PATH."

    cwd = working_directory or os.getcwd()
    if not os.path.isdir(cwd):
        return f"⚠️ Directory not found: {cwd}"

    # Restrict to the same filesystem allow-list local_files enforces — the
    # compensating control for allow_edits=True / shell access. Validated
    # even when working_directory was left blank (defaulting to the
    # current directory), per C5 in PROJECT-REVIEW-2026-07-06.md.
    #
    # Lazy-imported from tools (rather than tools importing this module at
    # load time) to avoid a circular import: tools.py imports
    # agents.workers.get_worker at module scope, so agents.workers.* modules
    # must not import tools.py at module scope either.
    try:
        from tools import _allowed_dirs, _is_path_allowed
        allowed = _allowed_dirs()
    except Exception:
        allowed = []
    if not allowed:
        return ("⚠️ No directories allowed for the coding agent. Add allowed_dirs to "
                 '~/.envoy/config.json:\n{"allowed_dirs": ["~/Projects"]}')
    if not _is_path_allowed(cwd, allowed):
        return (f"⚠️ Directory not allowed: {cwd}. Add it (or a parent directory) to "
                 f"allowed_dirs in ~/.envoy/config.json — the same allow-list local_files uses: {allowed}")

    # Pre-flight against the per-request budget. The subprocess makes its
    # own opaque LLM calls, so we can't enforce mid-flight — but we can
    # refuse to start a new long-running task once the budget is spent.
    budget = None
    try:
        from agents.budget import get_budget
        budget = get_budget()
        if budget.exceeded:
            return f"⚠️ Request budget exceeded ({budget.summary()}). Skipping coding sub-agent."
    except Exception:
        pass

    # Cap subprocess timeout to remaining budget (with a usable floor) so
    # the supervisor turn doesn't sit idle for ten minutes.
    timeout = _CODING_MAX_TIMEOUT
    if budget is not None:
        remaining = max(0.0, budget.max_wall - budget.elapsed)
        timeout = max(_CODING_MIN_TIMEOUT, min(_CODING_MAX_TIMEOUT, int(remaining + _CODING_MIN_TIMEOUT)))

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

    print(f"[coding] Delegating to {cli_name} (timeout {timeout}s): {task[:120]}...", file=sys.stderr)

    started = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
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
        return f"⚠️ [{cli_name}] timed out after {timeout}s. The task may be too large — try breaking it into smaller steps."
    except Exception as e:
        return f"⚠️ [{cli_name}] failed: {e}"
    finally:
        # Account for the call in the per-request budget. Token counts are
        # opaque from outside the subprocess, so estimate by wall time at
        # medium-tier rate. This at least prevents a runaway loop of
        # coding-worker calls from being free.
        try:
            if budget is not None:
                elapsed = time.monotonic() - started
                # Rough estimate: ~30 in / 200 out tokens per second of work
                est_in = int(elapsed * 30)
                est_out = int(elapsed * 200)
                budget.record_ai_call(input_tokens=est_in, output_tokens=est_out, tier="medium")
        except Exception:
            pass
