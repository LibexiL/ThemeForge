# Contributing to ThemeForge

## Share a theme

Community themes live in [`themes/`](themes). Everyone can install them from **More ▾ → Browse community themes…** inside ThemeForge.

1. In ThemeForge, make the palette you want to share and choose **More ▾ → Export this theme…**.
2. Open the exported `.json` file and fill in `"author"` (your GitHub name) and a short `"description"` (140 characters at most).
3. Fork this repo and put the file in `themes/`, named in lowercase with dashes (for example `neon-underground.json`).
4. Rebuild the index:
   ```bash
   python3 tools/build_theme_index.py
   ```
5. Open a pull request with both files.

CI checks that the colors are valid and the index is up to date. Please use a name that isn't already taken. If your theme is based on someone else's color scheme, say so in the description.

## Working on the code

ThemeForge is deliberately a single file, `themeforge.py`, because the auto-updater swaps that one file.

```bash
pip install -r requirements.txt pytest ruff
QT_QPA_PLATFORM=offscreen pytest -q tests     # tests run without a display
ruff check --select F,E9 themeforge.py tests tools
python3 themeforge.py                          # run it straight from the clone
```

A copy running from a git clone never updates itself; use `git pull`.

### Windows

The same file runs on Windows; code that differs checks `IS_WINDOWS`. Most of the Windows code (registry, Windows Terminal, audio capture, media controls, shortcuts, updater) has tests in `tests/test_windows.py` that use fakes, so they run on Linux too.

On Windows:

```powershell
py -m pip install -r requirements-windows.txt pytest
$env:QT_QPA_PLATFORM = "offscreen"; py -m pytest -q tests
py themeforge.py --selftest
```

The **CI** workflow's `windows` job runs the tests and the self-test from source. It then builds the app with PyInstaller and self-tests it, builds the installer with Inno Setup, installs it, and self-tests the installed copy. Each check shows up as an annotation on the run's summary page.

## Releasing

1. Bump the version in **both** places:
   - `VERSION` in `themeforge.py`
   - `Version:` in `packaging/themeforge.spec`, plus a `%changelog` entry
2. Add a section to `CHANGELOG.md`.
3. Commit, then tag and push:
   ```bash
   git tag v2.2.0
   git push origin main v2.2.0
   ```
4. The **Release** workflow then:
   - checks the tag matches both versions
   - runs the tests
   - publishes `themeforge.py`, `themeforge.py.sha256` and `install.sh`, with the changelog section as the release notes.
   - builds the Windows app on a Windows runner, self-tests it, and adds `ThemeForge-Setup.exe`, `ThemeForge-Windows.zip` and their `.sha256` files to the same release.

   Installed copies offer the update on their next start.

## Setting up the COPR package (one time)

[COPR](https://copr.fedorainfracloud.org) builds RPMs that Fedora and Nobara users install with `dnf`.

1. Log in to COPR with a Fedora account.
2. Create a project named `themeforge`. Choose the Fedora releases Nobara is based on (for example `fedora-42-x86_64`), then click **Create**.
3. Go to **Packages → New package → SCM**, and set:
   - Clone URL: `https://github.com/LibexiL/ThemeForge.git`
   - Build SRPM with: **make srpm** (it uses `.copr/Makefile`)
   - Turn on auto-rebuild.
4. Copy the webhook URL from **Settings → Integrations**. Add it to the GitHub repo under **Settings → Webhooks** (content type `application/json`, "Just the push event" is enough).
5. Trigger the first build with **Rebuild**.

After that, every push builds a new RPM, and users install with:

```bash
sudo dnf copr enable libexil/themeforge
sudo dnf install themeforge
```

To test the package locally on Fedora or Nobara:

```bash
make -f .copr/Makefile srpm outdir=/tmp/tf
rpmbuild --rebuild /tmp/tf/themeforge-*.src.rpm
```
