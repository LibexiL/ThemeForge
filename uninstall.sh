#!/usr/bin/env bash
# Removes ThemeForge.   bash uninstall.sh            keep your saved themes/settings
#                       bash uninstall.sh --purge    also delete ~/.config/themeforge
set -uo pipefail

APPDIR="$HOME/.local/share/themeforge"
APP="$APPDIR/themeforge.py"

if [ -f "$APP" ]; then
    read -r -p "Put back the config files and colors ThemeForge changed? [Y/n] " ans || ans=""
    if [[ ! "$ans" =~ ^[Nn] ]]; then
        python3 "$APP" --restore || echo "  (restore failed - your originals are in ~/.config/themeforge/backups)"
    fi
fi

echo "→ Stopping ThemeForge widgets, panels, visualizers and the tray service"
pkill -f "themeforge.py --visualizer" 2>/dev/null || true
pkill -f "themeforge.py --panel" 2>/dev/null || true
pkill -f "themeforge.py --service" 2>/dev/null || true
pkill -f "$HOME/.config/themeforge/widgets/" 2>/dev/null || true

echo "→ Removing the app"
rm -f "$HOME/.local/bin/themeforge" \
      "$HOME/.local/share/applications/themeforge.desktop" \
      "$HOME/.local/share/applications/themeforge-next-profile.desktop" \
      "$HOME/.config/autostart/themeforge-widgets.desktop"
rm -rf "$APPDIR"

if [ "${1:-}" = "--purge" ]; then
    rm -rf "$HOME/.config/themeforge"
    echo "→ Deleted ~/.config/themeforge"
else
    echo "  Kept your themes and settings in ~/.config/themeforge (use --purge to delete them)."
fi
echo "✓ ThemeForge removed."
