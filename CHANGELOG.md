# Changelog

## [2.2.0] - 2026-10-18

### Added
- **Panels**, which are clickable desktop windows drawn in your palette:
  - A **games launcher** that shows every shortcut in a folder. It can copy shortcuts from your Desktop or pick apps and games from the app menu.
  - A **now playing card** with album art, a seekable progress bar and playback buttons.
  - Both can glow with the bass.
- **Album-art mode.** Your desktop recolors to match the cover of whatever's playing, and goes back to your own theme when the music stops.
- **Desktop profiles.** Save your palette, wallpaper, targets and which widgets, visualizers and panels are running, then switch in one click, from the tray, a keyboard shortcut, or `--profile` / `--next-profile`.
- **Tray icon** for profiles, themes and album-art mode. Middle-click switches to the next profile.
- **New app targets:**
  - Discord (Vencord, Vesktop, Equicord, BetterDiscord)
  - Spotify (Spicetify)
  - btop
  - Starship
  - Vivaldi (theme export)
  - Icon theme, with Papirus folder colors matched to your accent
- The KDE accent color is now set together with the color scheme.
- **Visualizers:** a new frame style that wraps around a panel, and a "glow with the bass" option for every style.
- **Widget blocks:** CPU temperature, GPU usage and temperature (AMD and NVIDIA), and a calendar.
- **Community themes:** 8 to start with, browsable and installable in the app. Themes can also be imported and exported.
- A Fedora/COPR package (`packaging/themeforge.spec`, `.copr/Makefile`).
- `--list-profiles` command-line option.

### Fixed
- Network widget labels showed boxes (missing ↓↑ glyphs). They now read "Download" and "Upload", and both labels can be edited.
- CPU, memory and network graphs in widgets drew as a sliver on some conky versions.
- "&" in some labels showed up as an underlined letter.

## [2.1.0] - 2026-10-18

### Added
- **Music visualizers.** You can run any number of desktop visualizers at once.
  - Six styles: bars, mirrored bars, LED blocks, wave, mirrored wave and radial ring.
  - Each gets palette-driven colors, stereo mode, placement per monitor, live editing while running, and start at login.
- **Auto-updater.** ThemeForge checks GitHub releases on startup and verifies the SHA-256 checksum before installing. Also available as `--update`.
- `--restore` and `--version` command-line options.
- `uninstall.sh`, and a one-line installer that downloads the latest release.

## [2.0.0] - 2026-10-18

### Added
- First public version:
  - Palette editor with built-in themes and wallpaper extraction.
  - Applies colors to kitty, cava, KDE Plasma, Konsole, the wallpaper and existing conky configs.
  - Block-based conky widget builder with live preview.
  - Backup and restore of every file ThemeForge changes.
