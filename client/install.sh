#!/usr/bin/env bash
# Install the Claude-Horn tray client for the current user, with autostart at login.
# Usage: client/install.sh <client-name>     e.g. client/install.sh desktop
set -euo pipefail
NAME="${1:?usage: install.sh <client-name>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
uv tool install --force "$HERE"

mkdir -p ~/.local/share/claude-horn
rm -rf ~/.local/share/claude-horn/sounds
cp -r "$REPO/sounds" ~/.local/share/claude-horn/sounds

CFG=~/.config/claude-horn/client.json
mkdir -p "$(dirname "$CFG")"
if [[ ! -f "$CFG" ]]; then
  sed "s/\"name\": \"desktop\"/\"name\": \"$NAME\"/" "$HERE/client.example.json" > "$CFG"
  chmod 600 "$CFG"
  echo "Wrote $CFG: set the MQTT host, username and password in it."
fi

mkdir -p ~/.config/autostart
BIN="$(command -v claude-horn-client || echo "$HOME/.local/bin/claude-horn-client")"
sed "s|@BIN@|$BIN|" "$HERE/claude-horn.desktop" > ~/.config/autostart/claude-horn.desktop
mkdir -p ~/.local/share/applications
cp ~/.config/autostart/claude-horn.desktop ~/.local/share/applications/
echo "Installed. Starts at login; start it now with: $BIN &"
