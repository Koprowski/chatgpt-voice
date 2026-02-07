#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/venv"
CONFIG_DIR="$HOME/.config/chatgpt-voice"
TOGGLE_SCRIPT="$DIR/toggle"

echo "=== ChatGPT Voice Transcription Setup ==="
echo

# 1. Create virtualenv and install deps
echo "[1/5] Setting up Python virtualenv..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -e ".[linux]"

echo "[2/5] Installing Playwright Chromium..."
"$VENV/bin/python3" -m playwright install chromium
# Install system deps if needed (may require sudo)
"$VENV/bin/python3" -m playwright install-deps chromium 2>/dev/null || \
    echo "  Note: If browser fails to launch, run: sudo $VENV/bin/python3 -m playwright install-deps chromium"

# 3. Make toggle executable
echo "[3/5] Setting permissions..."
chmod +x "$TOGGLE_SCRIPT"

# 4. Config directory
echo "[4/5] Creating config..."
mkdir -p "$CONFIG_DIR"

# 5. Set up GNOME custom keyboard shortcut
echo "[5/5] Setting up GNOME keyboard shortcut..."

SHORTCUT_PATH="/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/chatgpt-voice/"
SHORTCUT_CMD="$VENV/bin/python3 $TOGGLE_SCRIPT"

# Get existing custom keybindings and append ours if not present
EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || echo "[]")

if echo "$EXISTING" | grep -q "chatgpt-voice"; then
    echo "  Shortcut already registered."
else
    # Add our path to the list
    if [ "$EXISTING" = "@as []" ] || [ "$EXISTING" = "[]" ]; then
        NEW="['$SHORTCUT_PATH']"
    else
        # Remove trailing ] and append
        NEW="${EXISTING%]*}, '$SHORTCUT_PATH']"
    fi
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEW"
fi

# Configure the shortcut
DCONF_PATH="org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:$SHORTCUT_PATH"
gsettings set "$DCONF_PATH" name "ChatGPT Voice Toggle"
gsettings set "$DCONF_PATH" command "$SHORTCUT_CMD"

# Check if a binding is already set
CURRENT_BINDING=$(gsettings get "$DCONF_PATH" binding 2>/dev/null || echo "''")
if [ "$CURRENT_BINDING" = "''" ] || [ "$CURRENT_BINDING" = "" ]; then
    gsettings set "$DCONF_PATH" binding "<Super>period"
    echo "  Hotkey set to Super+. (period)"
    echo "  Change it in: Settings > Keyboard > Custom Shortcuts"
else
    echo "  Hotkey already set to: $CURRENT_BINDING"
fi

echo
echo "=== Setup complete ==="
echo
echo "Next steps:"
echo "  1. Log in to ChatGPT (one-time):"
echo "     $VENV/bin/python3 -m chatgpt_voice login"
echo "     (Log in to ChatGPT in the browser that opens, then Ctrl+C)"
echo
echo "  2. Start the daemon:"
echo "     $VENV/bin/python3 -m chatgpt_voice start"
echo
echo "  3. Press Super+. to toggle voice recording"
echo "     - First press:  starts recording"
echo "     - Second press: stops recording, copies text to clipboard"
echo "     - Paste with Ctrl+V"
echo
echo "  To stop the daemon:"
echo "     $VENV/bin/python3 -m chatgpt_voice stop"
echo
echo "  To run on login, add to GNOME Startup Applications:"
echo "     $VENV/bin/python3 -m chatgpt_voice start"
