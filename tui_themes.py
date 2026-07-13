"""TUI theme system — colour palettes for the Envoy terminal interface.

Purpose-built themes for long productivity sessions. Each palette is
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
        # Muted warm grey — light theme without the glare. Reads like
        # unbleached paper under soft light, not a white screen at 100%.
        "bg": "#e4e0d8",
        "bg_surface": "#d6d1c7",
        "border": "#b8b2a6",
        "text": "#2a2a28",
        "text_dim": "#5c5852",
        "text_faint": "#8a847c",
        "accent": "#1e5c8c",
        "accent_dim": "#4a7ea6",
        "success": "#236640",
        "warning": "#7a5518",
        "error": "#a32e2e",
        "model": "#5c3f78",
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
    "forest": {
        # Dark green undertone — grounded, calm, earthy.
        # Good for long focus sessions when blue-tinted screens feel clinical.
        "bg": "#141c18",
        "bg_surface": "#1c2820",
        "border": "#2e3e34",
        "text": "#ccd8d0",
        "text_dim": "#728878",
        "text_faint": "#4a5c50",
        "accent": "#6ab88c",
        "accent_dim": "#3c7a58",
        "success": "#6ab88c",
        "warning": "#c8a848",
        "error": "#c86858",
        "model": "#8ab8c8",
    },
    "ember": {
        # Warm dark — amber-tinted for late night without blue light.
        # Feels like working by lamplight; reduces eye strain after hours.
        "bg": "#1c1814",
        "bg_surface": "#28221c",
        "border": "#3e3428",
        "text": "#d8cec4",
        "text_dim": "#8a7e72",
        "text_faint": "#5c5248",
        "accent": "#d4944c",
        "accent_dim": "#8c6434",
        "success": "#6aaa68",
        "warning": "#d4944c",
        "error": "#c85c4c",
        "model": "#c8a878",
    },
    "mono": {
        # High-contrast monochrome — maximum readability, zero colour noise.
        # For accessibility or when you want the content to do the talking.
        "bg": "#121212",
        "bg_surface": "#1e1e1e",
        "border": "#3a3a3a",
        "text": "#eeeeee",
        "text_dim": "#999999",
        "text_faint": "#5a5a5a",
        "accent": "#ffffff",
        "accent_dim": "#bbbbbb",
        "success": "#88cc88",
        "warning": "#cccc66",
        "error": "#cc6666",
        "model": "#bbbbbb",
    },
}

# The default theme
DEFAULT_THEME = "slate"

# In-memory cache — theme is resolved once per process from config.json,
# then reused on every render. Avoids disk I/O on each widget refresh and
# prevents inconsistency during rapid re-renders (e.g. window resize).
_cached_theme: dict | None = None
_cached_theme_name: str | None = None


def get_theme(name: str = None) -> dict:
    """Return the active theme dict. Cached after first resolution."""
    global _cached_theme, _cached_theme_name
    if name is None and _cached_theme is not None:
        return _cached_theme
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
    result = THEMES.get(name, THEMES[DEFAULT_THEME])
    _cached_theme = result
    _cached_theme_name = name
    return result


def invalidate_cache() -> None:
    """Clear the cached theme — called after set_theme() so next get_theme() re-reads."""
    global _cached_theme, _cached_theme_name
    _cached_theme = None
    _cached_theme_name = None


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
    invalidate_cache()
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

#input-area:focus-within {{
    border: round {t['accent_dim']};
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
