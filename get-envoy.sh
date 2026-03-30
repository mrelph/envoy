#!/bin/bash
# get-envoy.sh — Download, install, or update Envoy
# Usage: curl -fsSL https://raw.githubusercontent.com/mrelph/envoy/main/get-envoy.sh | bash
set -e

REPO="https://github.com/mrelph/envoy.git"
INSTALL_DIR="${ENVOY_DIR:-$HOME/.envoy}"
LINK="/usr/local/bin/envoy"

echo ""
echo "  ✈  Envoy Installer"
echo "  ───────────────────"
echo ""

# Require git and python3
for cmd in git python3; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: $cmd is required but not found." >&2
        exit 1
    fi
done

# Clone or update
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Updating existing installation..."
    git -C "$INSTALL_DIR" fetch --tags --quiet
    git -C "$INSTALL_DIR" pull --ff-only --quiet
    # Refresh dependencies
    if [ -f "$INSTALL_DIR/venv/bin/pip" ]; then
        "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
    fi
else
    echo "  Cloning Envoy..."
    git clone --quiet "$REPO" "$INSTALL_DIR"
fi

# Set up Python venv + dependencies
if [ ! -f "$INSTALL_DIR/venv/bin/python3" ]; then
    echo "  Setting up Python environment..."
    python3 -m venv "$INSTALL_DIR/venv"
    "$INSTALL_DIR/venv/bin/pip" install -q -r "$INSTALL_DIR/requirements.txt"
fi

# Make entrypoint executable
chmod +x "$INSTALL_DIR/envoy"

# Symlink to PATH
if [ -w "$(dirname "$LINK")" ]; then
    ln -sf "$INSTALL_DIR/envoy" "$LINK"
else
    echo "  Linking to $LINK (requires sudo)..."
    sudo ln -sf "$INSTALL_DIR/envoy" "$LINK"
fi

VERSION="$(cat "$INSTALL_DIR/VERSION" 2>/dev/null || echo "unknown")"
echo ""
echo "  ✓ Envoy v${VERSION} installed to $INSTALL_DIR"
echo "  ✓ Linked envoy → $LINK"
echo ""
echo "  Get started:"
echo "    envoy init    # first-time setup"
echo "    envoy         # launch"
echo ""
