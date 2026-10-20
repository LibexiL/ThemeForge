# Changelog

## [2.4.0] - 2026-10-19

### Added
- **Five new panels:**
  - **Calendar**: click the arrows to change month (the grid slides), click the month name to jump back to today. Today glows.
  - **Countdown** to any date and time: digits roll like a flip clock as they change.
  - **Drives**: free space on every real drive, detected automatically, with animated bars that turn red past 90%.
  - **Network graph**: live download and upload, scrolling smoothly.
  - **Notes & to-do**: shows a Markdown file. Click a checkbox to tick it off; the change is saved to the file. Editing the file anywhere updates the panel.
- **CPU threads** for the system panel: one animated bar per thread.
- **Customize any panel:**
  - Background: solid, gradient, frosted glass or outline only.
  - Highlight color, font, text size and a drop shadow.
- **Motion options for any panel:**
  - Entrance: fade, slide up, pop in or none.
  - Animation speed and a breathing glow.
  - Fade out while the mouse is over it, so you can see the desktop behind.
- **Move panels by dragging them**: right-click a panel on the desktop, choose "Move this panel" and drop it where you want. The new position is saved and snapped to a 4 px grid.
- **Visualizers:**
  - A **particle fountain** style: sparks thrown up by the music fall back under gravity.
  - A **dot columns** style.
  - A **flowing colors** option that cycles the gradient over time.

## [2.3.1] - 2026-10-19

### Fixed
- Panels, visualizers and widgets showed up in the Plasma taskbar as blank "X" entries flagged as demanding attention, which kept an auto-hiding panel open.
  - ThemeForge now adds a KWin window rule for its desktop windows. The rule hides them from the taskbar, pager and Alt+Tab, keeps them below other windows, and stops them from taking focus.
  - The rule is added when the app opens and whenever a panel, visualizer or widget starts. `themeforge --fix-windows` adds it by hand, and "Restore my original files" removes it.

## [2.3.0] - 2026-10-18

### Added
- **Three new panels:**
  - **Clock**, in three styles: digital with a sweeping seconds ring, digital with a seconds bar, or analog with a smooth second hand.
  - **System gauges**: animated arc gauges for CPU, RAM, GPU, CPU and GPU temperature, and disk, plus a network speed row. NVIDIA GPUs are read with `nvidia-smi`, AMD GPUs from sysfs.
  - **Weather**: animated icons (turning sun, drifting clouds, falling rain and snow, lightning, a moon at night) and a 3-day forecast from wttr.in. Click the panel to open the full forecast.
- **Animations everywhere ThemeForge draws:**
  - Panels fade in, and colors blend smoothly whenever the palette changes (including in album-art mode).
  - Games launcher icons lift and glow on hover, and bounce with a ripple when clicked.
  - The now playing card crossfades album art, scrolls long titles, shows a small equalizer while playing, runs a light along the progress bar, and pulses the play button with the bass. It can also show the art as a **spinning record**.
  - An optional **animated shimmer outline** for any panel.
  - A per-panel "Animations" switch. With animations off, a panel only redraws when something changes.
- **Visualizers:**
  - Falling **peak caps**, held briefly before they drop.
  - A **spin** setting for the radial ring, the new orb and the frame.
  - A new **Orb** style: a glowing round wave.

### Changed
- Animation timers stop when nothing is moving, so idle panels use no CPU.

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
