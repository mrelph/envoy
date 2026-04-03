# How to Make a TUI the Default Interface for Your CLI Tool

A pattern for CLI tools where running the bare command drops you into an interactive TUI/REPL, while subcommands remain available for scripting and automation.

This document uses [Envoy](https://github.com/mrelph/envoy) as a worked example.

---

## The Pattern

```
$ mytool              → launches interactive TUI
$ mytool digest       → runs "digest" subcommand, exits
$ mytool --help       → shows help text
```

The user gets the rich experience by default, but every interactive feature is also available as a scriptable subcommand. This is the best of both worlds: discoverable for humans, composable for machines.

## Why Do This

- Most users run your tool interactively most of the time. Make that the zero-friction path.
- New users don't need to memorize subcommands — they land in a guided interface.
- Power users and cron jobs still get deterministic, scriptable subcommands.
- Slash commands in the TUI can mirror subcommands 1:1, so there's one mental model.

---

## Implementation (Python + Click)

The core trick is three lines of Click configuration.

### 1. The CLI Group: `invoke_without_command=True`

```python
# cli.py
import click

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    """My tool — run with no args for interactive mode."""
    if ctx.invoked_subcommand is None:
        from repl import run_interactive
        run_interactive()
```

`invoke_without_command=True` tells Click to execute the group function even when no subcommand is provided. The `ctx.invoked_subcommand is None` check distinguishes "user typed `mytool`" from "user typed `mytool digest`".

### 2. Register Subcommands Normally

```python
@cli.command()
@click.option('--days', '-d', default=7)
def digest(days):
    """Generate a digest report."""
    run_digest(days)

@cli.command()
def cleanup():
    """Clean up old items."""
    run_cleanup()
```

These work exactly as you'd expect: `mytool digest --days 14` runs and exits.

### 3. The Interactive REPL

```python
# repl.py
def run_interactive():
    """Launch the interactive TUI."""
    print_logo()
    check_connections()

    while True:
        try:
            user_input = input("› ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input:
            continue
        if user_input in ("/quit", "/exit"):
            break
        if user_input.startswith("/"):
            handle_slash_command(user_input)
        else:
            handle_freeform(user_input)
```

### 4. The Entrypoint

Wire it up in your bash wrapper or `pyproject.toml`:

```bash
#!/bin/bash
# mytool — entrypoint
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/cli.py" "$@"
```

Or via setuptools/pyproject.toml:

```toml
[project.scripts]
mytool = "mytool.cli:cli"
```

The `"$@"` passthrough is what makes this work — if the user passes subcommands and flags, Click routes them. If they pass nothing, the group function fires and launches the REPL.

---

## How Envoy Does It

Envoy follows this pattern exactly:

| Layer | File | Role |
|---|---|---|
| Shell entrypoint | `envoy` | Bootstraps venv, handles auth, passes `$@` to `cli.py` |
| CLI router | `cli.py` | Click group with `invoke_without_command=True` |
| Interactive REPL | `repl.py` | Logo, connection checks, agent creation, REPL loop |
| Subcommands | `cli.py` | `digest`, `cleanup`, `customers`, etc. registered as `@cli.command()` |

The key section of `cli.py`:

```python
@click.group(invoke_without_command=True)
@click.version_option(version=VERSION)
@click.option('--verbose', '-v', is_flag=True, default=False)
@click.pass_context
def cli(ctx, verbose):
    """Envoy — Your AI Chief of Staff."""
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose

    if ctx.invoked_subcommand is None:
        from repl import run_interactive
        run_interactive()
```

Every slash command in the REPL (e.g., `/digest 7`) maps to the same logic as the CLI subcommand (`envoy digest --days 7`). One implementation, two interfaces.

---

## Advice

### Keep the REPL import lazy

Use `from repl import run_interactive` inside the function, not at the top of the file. This keeps `mytool digest` fast — it never loads the REPL, prompt toolkit, or any TUI dependencies.

### Mirror subcommands as slash commands

If `mytool digest --days 7` works, then `/digest 7` should work in the REPL. Users shouldn't have to learn two interfaces. Envoy does this by mapping slash commands to the same underlying functions that the CLI subcommands call.

### Make `--help` still work

`invoke_without_command=True` doesn't break `--help`. Click handles `mytool --help` before your group function runs. No special handling needed.

### Handle Ctrl+C and EOF gracefully

The REPL should catch `KeyboardInterrupt` and `EOFError` and exit cleanly, not dump a traceback. This is table stakes for a good TUI.

### Don't break pipes and scripts

`mytool digest --days 7 | head -20` must still work. Your subcommands should detect whether stdout is a TTY and adjust output accordingly (e.g., skip Rich formatting when piped):

```python
import sys
if sys.stdout.isatty():
    rich_print(output)
else:
    print(plain_text)
```

### Provide a `--no-interactive` escape hatch

Some users will want to suppress the REPL even when running the bare command (e.g., in a script that sources your tool). A `--no-interactive` flag or `MYTOOL_NO_INTERACTIVE=1` env var is a nice safety valve.

### Show a status bar or connection check on startup

If your TUI depends on external services (APIs, MCP servers, databases), check them at REPL startup and show the status. Envoy does this with an animated connection check. It takes a second but saves minutes of debugging when something is down.

### Keep subcommand output clean for automation

Subcommands should produce parseable output (or at least no spinners/animations) so they work in cron jobs and pipelines. Reserve the rich UI for the interactive REPL.

---

## Other Frameworks

The same pattern works outside Click:

| Framework | Equivalent |
|---|---|
| **argparse** | Check `if args.command is None` after parsing, then launch REPL |
| **Typer** | Use `@app.callback(invoke_without_command=True)` with the same `ctx.invoked_subcommand is None` check |
| **Go (cobra)** | Set `Run` on the root command to launch TUI; subcommands override it |
| **Rust (clap)** | Match on `None` in the subcommand match arm |
| **Node (commander)** | Check `program.args.length === 0` before calling `program.parse()` |

---

## Summary

The recipe:

1. Make your CLI group/root command execute when no subcommand is given.
2. In that handler, check for "no subcommand" and launch the REPL.
3. Register all features as both subcommands and slash commands.
4. Keep the REPL import lazy so subcommands stay fast.
5. Respect TTY detection so pipes and scripts still work.

That's it. Three lines of routing logic, and your tool becomes interactive-first without sacrificing scriptability.
