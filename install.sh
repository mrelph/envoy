#!/bin/bash
# Envoy installer — sets up dependencies and adds envoy to PATH
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LINK="/usr/local/bin/envoy"

echo "Installing Envoy..."

# Install Python venv + dependencies
if [ ! -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    echo "Setting up Python environment..."
    python3 -m venv "$SCRIPT_DIR/venv"
    "$SCRIPT_DIR/venv/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
fi

# Symlink to PATH
if [ -w "$(dirname "$LINK")" ]; then
    ln -sf "$SCRIPT_DIR/envoy" "$LINK"
    echo "✓ Linked envoy → $LINK"
else
    sudo ln -sf "$SCRIPT_DIR/envoy" "$LINK"
    echo "✓ Linked envoy → $LINK (sudo)"
fi

echo "✓ Install complete. Run 'envoy init' to set up your profile."
