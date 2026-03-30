#!/bin/bash
# Envoy installer — sets up dependencies, skills, and adds envoy to PATH
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LINK="/usr/local/bin/envoy"

echo ""
echo "  ✈  Installing Envoy v$(cat "$SCRIPT_DIR/VERSION")"
echo "  ─────────────────────────"
echo ""

# Check prerequisites
for cmd in python3 mwinit; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "  ⚠  $cmd not found — some features may not work"
    fi
done

for mcp in builder-mcp aws-outlook-mcp; do
    if ! command -v "$mcp" &>/dev/null; then
        echo "  ⚠  $mcp not found — install it for full functionality"
    fi
done

# Install Python venv + dependencies
if [ ! -f "$SCRIPT_DIR/venv/bin/python3" ]; then
    echo "  Setting up Python environment..."
    python3 -m venv "$SCRIPT_DIR/venv"
    "$SCRIPT_DIR/venv/bin/pip" install -q -r "$SCRIPT_DIR/requirements.txt"
    echo "  ✓ Dependencies installed"
else
    echo "  ✓ Python environment exists"
fi

# Install bundled skills to ~/.envoy/skills/
SKILLS_SRC="$SCRIPT_DIR/templates/skills"
SKILLS_DST="$HOME/.envoy/skills"
if [ -d "$SKILLS_SRC" ]; then
    mkdir -p "$SKILLS_DST"
    installed=0
    for skill in "$SKILLS_SRC"/*/; do
        name="$(basename "$skill")"
        if [ ! -d "$SKILLS_DST/$name" ]; then
            cp -r "$skill" "$SKILLS_DST/$name"
            installed=$((installed + 1))
        fi
    done
    total=$(ls -d "$SKILLS_DST"/*/ 2>/dev/null | wc -l)
    echo "  ✓ Skills: $total installed ($installed new)"
fi

# Make entrypoint executable
chmod +x "$SCRIPT_DIR/envoy"

# Symlink to PATH
if [ -w "$(dirname "$LINK")" ]; then
    ln -sf "$SCRIPT_DIR/envoy" "$LINK"
    echo "  ✓ Linked envoy → $LINK"
else
    sudo ln -sf "$SCRIPT_DIR/envoy" "$LINK"
    echo "  ✓ Linked envoy → $LINK (sudo)"
fi

# AWS credentials check
if [ -f "$SCRIPT_DIR/.env" ] || aws sts get-caller-identity &>/dev/null 2>&1; then
    echo "  ✓ AWS credentials found"
else
    echo "  ⚠  No AWS credentials — copy .env.example to .env and add your keys"
fi

echo ""
echo "  ✓ Install complete!"
echo ""
echo "  Next steps:"
echo "    envoy init    # configure your identity and agent personality"
echo "    envoy         # launch the interactive REPL"
echo "    envoy --help  # see all commands"
echo ""
