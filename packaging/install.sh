#!/bin/bash
# Register the extracted Prism folder with the desktop environment: a launcher
# entry, an icon, and a `prism` command. Everything goes under ~/.local, so no
# root and nothing to uninstall but three files (see --uninstall).
set -e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="in.alphakore.prism"
BIN="$HOME/.local/bin"
DESKTOP="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/512x512/apps"

if [ "$1" = "--uninstall" ]; then
    rm -f "$BIN/prism" "$DESKTOP/$APP_ID.desktop" "$ICONS/$APP_ID.png"
    update-desktop-database "$DESKTOP" 2>/dev/null || true
    echo "Removed the launcher entry. Delete this folder to finish."
    exit 0
fi

mkdir -p "$BIN" "$DESKTOP" "$ICONS"
ln -sf "$HERE/Prism" "$BIN/prism"
cp -f "$HERE/$APP_ID.png" "$ICONS/$APP_ID.png"

# Exec must be the absolute path: the .desktop file is read by the session,
# which does not have this folder on PATH.
sed "s|^Exec=.*|Exec=$HERE/Prism|" "$HERE/$APP_ID.desktop" > "$DESKTOP/$APP_ID.desktop"
chmod +x "$DESKTOP/$APP_ID.desktop"
update-desktop-database "$DESKTOP" 2>/dev/null || true

echo "Prism is installed for $USER."
echo "  · launch it from your applications menu, or run: prism"
echo "  · remove it with: $HERE/install.sh --uninstall"
if ! command -v google-chrome >/dev/null 2>&1 && \
   ! command -v google-chrome-stable >/dev/null 2>&1; then
    echo
    echo "!  Google Chrome was not found. Prism drives your logged-in Chrome"
    echo "   to run the AI tools — install it from google.com/chrome first."
fi
