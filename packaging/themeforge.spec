Name:           themeforge
Version:        2.5.1
Release:        1%{?dist}
Summary:        One palette for kitty, cava, KDE Plasma, widgets, panels and visualizers

License:        MIT
URL:            https://github.com/LibexiL/ThemeForge
Source0:        %{url}/archive/v%{version}/ThemeForge-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  desktop-file-utils
Requires:       python3 >= 3.10
Requires:       python3-pyside6
Requires:       cava
Requires:       conky
Requires:       playerctl
Requires:       curl
Recommends:     kde-cli-tools
Recommends:     libnotify

%description
ThemeForge themes your whole KDE Plasma desktop from one palette: kitty, cava,
KDE colors and accent, Konsole, icons, Discord (Vencord/Vesktop), Spotify
(Spicetify), btop, Starship and your wallpaper. It also builds conky widgets,
clickable desktop panels (games launcher, now playing card) and music
visualizers in the same colors, follows the album art of what's playing, and
switches between whole-desktop profiles from a tray icon or shortcut.

%prep
%autosetup -n ThemeForge-%{version}

%build
# nothing to build - a single Python script

%install
install -Dpm 0755 themeforge.py %{buildroot}%{_datadir}/themeforge/themeforge.py
install -d %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/themeforge <<'SH'
#!/bin/sh
exec /usr/bin/python3 %{_datadir}/themeforge/themeforge.py "$@"
SH
chmod 0755 %{buildroot}%{_bindir}/themeforge
install -Dpm 0644 packaging/themeforge.desktop %{buildroot}%{_datadir}/applications/themeforge.desktop
desktop-file-validate %{buildroot}%{_datadir}/applications/themeforge.desktop

%files
%license LICENSE
%doc README.md CHANGELOG.md
%{_bindir}/themeforge
%{_datadir}/themeforge/
%{_datadir}/applications/themeforge.desktop

%changelog
* Fri Oct 30 2026 LibexiL <LibexiL@users.noreply.github.com> - 2.5.1-1
- Windows fixes: Win+D, drive list, CPU temperature

* Fri Oct 30 2026 LibexiL <LibexiL@users.noreply.github.com> - 2.5.0-1
- Windows version; UTF-8 file handling; --selftest

* Mon Oct 19 2026 LibexiL <LibexiL@users.noreply.github.com> - 2.4.0-1
- Calendar, countdown, drives, network and notes panels; panel customization; particles

* Mon Oct 19 2026 LibexiL <LibexiL@users.noreply.github.com> - 2.3.1-1
- Keep ThemeForge's desktop windows out of the taskbar

* Sun Oct 18 2026 LibexiL <LibexiL@users.noreply.github.com> - 2.3.0-1
- Animated panels and visualizers; clock, system gauges and weather panels

* Sun Oct 18 2026 LibexiL <LibexiL@users.noreply.github.com> - 2.2.0-1
- Panels, profiles, album-art mode, tray icon, more app targets, community themes
