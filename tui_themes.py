"""TUI theme system — colour palettes for the Envoy terminal interface.

Three purpose-built themes for long productivity sessions. Each palette is
designed for readability, clear spatial hierarchy, and minimal eye fatigue.

Tokens:
    bg          — main content background (largest surface)
    bg_surface  — elevated surfaces: input area, MCP bar, modals
    border      — structural dividers (low-contrast, never shouty)
    text        — primary text (high contrast against bg)
    text_dim    — secondary text, metadata, timestamps
    text_faint  — tertiary: hints, placeholders, inactive states
    accent      — prompt symbol, active indicators, links
    accent_dim  — softer variant of accent for secondary highlights
    success     — connected, fast, healthy
    warning     — slow, needs attention
    error       — disconnected, failed
    model       — model name highlight in status bar
"""

import json
from pathlib import Path

THEMES = {
    "midnight": {
        # Deep blue-black — easy on the eyes for evening/night sessions.
        # Inspired by a clear night sky, not a code editor.
        "bg": "#101820",
        "bg_surface": "#1a2332",
        "border": "#2a3a4a",
        "text": "#d4dce8",
        "text_dim": "#7a8a9a",
        "text_faint": "#4a5a6a",
        "accent": "#6cb4e8",
        "accent_dim": "#3d7aa0",
        "success": "#5cb886",
        "warning": "#d4a054",
        "error": "#d46464",
        "model": "#b8a0d8",
    },
    "paper": {
        # Warm off-white — daylight/bright environment theme.
        # Not clinical white; has warmth without being beige-slop.
        "bg": "#f8f6f2",
        "bg_surface": "#edeae4",
        "border": "#d4cfc6",
        "text": "#2c2c2c",
        "text_dim": "#6b6560",
        "text_faint": "#9b9590",
        "accent": "#2868a0",
        "accent_dim": "#5a8ab8",
        "success": "#2a7a4a",
        "warning": "#8a6420",
        "error": "#b83a3a",
        "model": "#6a4a8a",
    },
    "slate": {
        # Cool neutral grey — the default. Works in any lighting.
        # Sits between dark and light; professional without being boring.
        "bg": "#1e2228",
        "bg_surface": "#282e36",
        "border": "#3a424c",
        "text": "#c8cdd4",
        "text_dim": "#6e7a88",
        "text_faint": "#464e58",
        "accent": "#5aa0d0",
        "accent_dim": "#3a6a8c",
        "success": "#58a878",
        "warning": "#c89848",
        "error": "#c85858",
        "model": "#a088c8",
    },
}

# The default theme
DEFAULT_THEME = "slate"


def get_theme(name: str = None) -> dict:
    """Load the active theme. Reads from ~/.envoy/config.json if name not given."""
    if name is None:
        from agents.paths import config_dir
        config_file = config_dir() / "config.json"
        if config_file.exists():
            try:
                cfg = json.loads(config_file.read_text())
                name = cfg.get("theme", DEFAULT_THEME)
            except Exception:
                name = DEFAULT_THEME
        else:
            name = DEFAULT_THEME
    return THEMES.get(name, THEMES[DEFAULT_THEME])


def get_theme_name() -> str:
    """Return the name of the currently active theme."""
    from agents.paths import config_dir
    config_file = config_dir() / "config.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            name = cfg.get("theme", DEFAULT_THEME)
            if name in THEMES:
                return name
        except Exception:
            pass
    return DEFAULT_THEME


def set_theme(name: str) -> bool:
    """Save theme preference to ~/.envoy/config.json. Returns False if unknown theme."""
    if name not in THEMES:
        return False
    from agents.paths import config_dir
    config_file = config_dir() / "config.json"
    cfg = {}
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
        except Exception:
            pass
    cfg["theme"] = name
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(cfg, indent=2))
    return True


def list_themes() -> list:
    """Return list of available theme names."""
    return list(THEMES.keys())


def build_css(theme: dict = None) -> str:
    """Generate the TUI CSS string from a theme dict."""
    if theme is None:
        theme = get_theme()
    t = theme
    return f"""/* Envoy TUI — generated from active theme */

Screen {{
    background: {t['bg']};
}}

#mcp-bar {{
    height: auto;
    dock: top;
    background: {t['bg_surface']};
    padding: 0 2;
    border-bottom: solid {t['border']};
}}

#feed {{
    height: auto;
    max-height: 5;
    padding: 0 2;
    background: {t['bg']};
    border-bottom: dashed {t['border']};
}}

#output {{
    height: 1fr;
    padding: 1 3;
    overflow-x: hidden;
    background: {t['bg']};
    scrollbar-size: 0 0;
}}

#output:focus {{
    border: none;
}}

#spinner {{
    height: 1;
    background: {t['bg']};
    padding: 0 3;
}}

#input-area {{
    dock: bottom;
    height: auto;
    max-height: 8;
    padding: 0 2;
    margin: 0 2;
    background: {t['bg_surface']};
    border: round {t['border']};
}}

#prompt-label {{
    width: 3;
    padding: 0 0 0 1;
    color: {t['accent']};
    text-style: bold;
}}

#input {{
    background: transparent;
    border: none;
    width: 1fr;
    min-height: 1;
    max-height: 6;
    color: {t['text']};
}}

#input:focus {{
    border: none;
}}

#status-bar {{
    dock: bottom;
    height: auto;
    background: {t['bg_surface']};
    color: {t['text_dim']};
    padding: 0 2;
    border-top: solid {t['border']};
}}
"""
