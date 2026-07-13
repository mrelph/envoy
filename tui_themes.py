"""TUI theme system — colour palettes for the Envoy terminal interface.

Themes define a consistent set of semantic colour tokens. The TUI loads one
theme at startup and applies it to widget styles and the generated CSS.
"""

import json
from pathlib import Path

THEMES = {
    "dark": {  # GitHub dark — the original default
        "bg": "#0d1117",
        "bg_secondary": "#161b22",
        "border": "#21262d",
        "text": "#e6edf3",
        "text_dim": "#7d8590",
        "accent": "#58a6ff",
        "success": "#3fb950",
        "warning": "#d29922",
        "error": "#f85149",
        "bar_bg": "#010409",
    },
    "light": {  # clean light theme
        "bg": "#ffffff",
        "bg_secondary": "#f6f8fa",
        "border": "#d0d7de",
        "text": "#1f2328",
        "text_dim": "#656d76",
        "accent": "#0969da",
        "success": "#1a7f37",
        "warning": "#9a6700",
        "error": "#cf222e",
        "bar_bg": "#f6f8fa",
    },
    "nord": {  # Arctic colour scheme
        "bg": "#2e3440",
        "bg_secondary": "#3b4252",
        "border": "#4c566a",
        "text": "#eceff4",
        "text_dim": "#d8dee9",
        "accent": "#88c0d0",
        "success": "#a3be8c",
        "warning": "#ebcb8b",
        "error": "#bf616a",
        "bar_bg": "#2e3440",
    },
    "dracula": {  # Dracula colour scheme
        "bg": "#282a36",
        "bg_secondary": "#44475a",
        "border": "#6272a4",
        "text": "#f8f8f2",
        "text_dim": "#6272a4",
        "accent": "#bd93f9",
        "success": "#50fa7b",
        "warning": "#f1fa8c",
        "error": "#ff5555",
        "bar_bg": "#21222c",
    },
    "solarized": {  # Solarized dark
        "bg": "#002b36",
        "bg_secondary": "#073642",
        "border": "#586e75",
        "text": "#839496",
        "text_dim": "#657b83",
        "accent": "#268bd2",
        "success": "#859900",
        "warning": "#b58900",
        "error": "#dc322f",
        "bar_bg": "#002b36",
    },
}


def get_theme(name: str = None) -> dict:
    """Load the active theme. Reads from ~/.envoy/config.json if name not given."""
    if name is None:
        from agents.paths import config_dir
        config_file = config_dir() / "config.json"
        if config_file.exists():
            try:
                cfg = json.loads(config_file.read_text())
                name = cfg.get("theme", "dark")
            except Exception:
                name = "dark"
        else:
            name = "dark"
    return THEMES.get(name, THEMES["dark"])


def get_theme_name() -> str:
    """Return the name of the currently active theme."""
    from agents.paths import config_dir
    config_file = config_dir() / "config.json"
    if config_file.exists():
        try:
            cfg = json.loads(config_file.read_text())
            name = cfg.get("theme", "dark")
            if name in THEMES:
                return name
        except Exception:
            pass
    return "dark"


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
    return f"""/* Envoy TUI — generated from theme */

Screen {{
    background: {t['bg']};
}}

#mcp-bar {{
    height: auto;
    dock: top;
    background: {t['bg_secondary']};
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
    padding: 1 4;
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
    background: {t['bg_secondary']};
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
    background: {t['bar_bg']};
    color: {t['text_dim']};
    padding: 0 2;
    border-top: solid {t['border']};
}}
"""
