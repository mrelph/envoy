"""Envoy — Plain text REPL fallback (no TUI dependencies)."""

import os
import sys
from agent import get_agent, reload_agent
from dispatch import COMMANDS, COMMAND_GROUPS, dispatch


def run_interactive():
    """Plain text REPL — fallback when Textual is unavailable."""
    print("\n  ✈  Envoy — Your AI Chief of Staff")
    print("  Type /help for commands, or just chat.\n")

    # MCP check (non-animated)
    try:
        from ui import _check_mcp_servers
        status = _check_mcp_servers()
        parts = [f"{'✓' if ok else '✗'} {name}" for name, ok in status.items()]
        print(f"  MCP: {', '.join(parts)}\n")
    except Exception:
        pass

    print("  Loading agent…", end="", flush=True)
    agent = get_agent()
    print(" ready.\n")

    while True:
        try:
            raw = input("› ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.lower() in ("quit", "exit", "q", "/exit", "/quit"):
            print("Goodbye!")
            break

        if stripped.lower() == "/help":
            for group_name, cmds in COMMAND_GROUPS:
                print(f"\n  {group_name}")
                for cmd in cmds:
                    entry = COMMANDS.get(cmd)
                    desc = entry[0] if entry else ""
                    print(f"    {cmd:20s} {desc}")
            print()
            continue

        if stripped.lower() == "/status":
            try:
                from ui import _check_mcp_servers
                for name, ok in _check_mcp_servers().items():
                    print(f"  {'✓' if ok else '✗'} {name}")
            except Exception as e:
                print(f"  Error: {e}")
            continue

        if stripped.lower() == "/settings":
            from init_cmd import run_settings
            run_settings()
            reload_agent()
            agent = get_agent()
            continue

        if stripped.lower() == "/backup":
            from backup import run_backup
            run_backup()
            continue

        if stripped.lower() == "/mwinit":
            import subprocess
            print("  Launching mwinit — check your browser…")
            subprocess.run(["mwinit", "-o"])
            from agents.base import _persistent
            _persistent.clear()
            print("  ✓ Midway refreshed")
            continue

        # Refresh in case /models (or another path) called reload_agent().
        agent = get_agent()
        result, handled = dispatch(stripped, agent)
        if handled and result:
            print(f"\n{result}\n")
        elif not handled:
            # System command not handled by dispatch
            pass
