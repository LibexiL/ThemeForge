# Changelog

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
