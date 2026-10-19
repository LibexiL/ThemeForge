#!/usr/bin/env bash
# ThemeForge installer for Nobara / Fedora KDE Plasma.
#
#   From a clone or download:  bash install.sh
#   One-liner:                 curl -fsSL https://github.com/LibexiL/ThemeForge/releases/latest/download/install.sh | bash
#
# Installs to ~/.local/share/themeforge (no root needed except for dnf packages).
set -euo pipefail

REPO="LibexiL/ThemeForge"
APPDIR="$HOME/.local/share/themeforge"
SRC=""

# Use the copy next to this script when there is one, otherwise download the latest release
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/themeforge.py" ]; then
    SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/themeforge.py"
fi

echo "→ Installing dependencies (PySide6, cava, conky, playerctl, curl)…"
if ! sudo dnf install -y python3-pyside6 cava conky playerctl curl; then
    echo "  dnf couldn't install everything; trying the rest separately and PySide6 from pip"
    sudo dnf install -y cava conky playerctl curl || true
    python3 -m pip install --user "PySide6>=6.5"
fi

mkdir -p "$APPDIR" "$HOME/.local/bin" "$HOME/.local/share/applications"

if [ -n "$SRC" ]; then
    echo "→ Installing $SRC"
    cp "$SRC" "$APPDIR/themeforge.py"
else
    echo "→ Downloading the latest release from github.com/$REPO"
    base="https://github.com/$REPO/releases/latest/download"
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL "$base/themeforge.py" -o "$tmp/themeforge.py"
    curl -fsSL "$base/themeforge.py.sha256" -o "$tmp/themeforge.py.sha256"
    (cd "$tmp" && sha256sum -c themeforge.py.sha256)
    cp "$tmp/themeforge.py" "$APPDIR/themeforge.py"
fi

chmod +x "$APPDIR/themeforge.py"
ln -sf "$APPDIR/themeforge.py" "$HOME/.local/bin/themeforge"

cat > "$HOME/.local/share/applications/themeforge.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=ThemeForge
Comment=Theme kitty, cava, KDE, widgets, panels and visualizers from one palette
Exec=python3 $APPDIR/themeforge.py
Icon=preferences-desktop-color
Categories=Settings;DesktopSettings;Qt;
Keywords=theme;colors;palette;conky;cava;kitty;visualizer;
Terminal=false
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo
echo "✓ ThemeForge $(python3 "$APPDIR/themeforge.py" --version | awk '{print $2}') installed."
echo "  Open it from the app menu, or run:  themeforge"
echo "  It checks GitHub for updates on startup (you can turn that off in the app)."
