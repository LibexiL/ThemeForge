import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# ThemeForge reads HOME at import time, so point it at a throwaway folder first
_HOME = Path(tempfile.mkdtemp(prefix="themeforge-test-home-"))
os.environ["HOME"] = str(_HOME)
os.environ["USERPROFILE"] = str(_HOME)                  # Path.home() on Windows
os.environ["APPDATA"] = str(_HOME / "AppData" / "Roaming")
os.environ["LOCALAPPDATA"] = str(_HOME / "AppData" / "Local")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def home():
    """A clean fake home directory for each test."""
    for child in _HOME.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    return _HOME


@pytest.fixture
def tf(home):
    import themeforge
    return themeforge


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """Painting text needs a Qt application object; one per test run."""
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# Tests of things that only exist on Linux (kitty, cava, conky, KDE, KWin, .desktop files…)
LINUX_ONLY = {
    "test_kitty_include_is_added_once_and_kept_last", "test_cava_color_section_replaced_and_rest_kept",
    "test_backup_and_restore_round_trip", "test_conky_recolor_only_touches_known_keys",
    "test_every_widget_block_generates", "test_helper_reads_cpu_temperature_from_hwmon",
    "test_helper_calendar_highlights_today", "test_helper_script_runs_standalone",
    "test_discord_only_writes_for_installed_clients", "test_btop_selects_theme_once",
    "test_papirus_folder_color_matching", "test_icon_themes_skip_cursor_only_themes",
    "test_launcher_items_read_desktop_files", "test_kwin_rule_merges_with_existing_rules_and_restores",
    "test_kwin_rule_created_from_scratch", "test_settings_survive_old_or_partial_files",
}


def pytest_collection_modifyitems(config, items):
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(reason="Linux-only feature")
    for item in items:
        if item.name in LINUX_ONLY:
            item.add_marker(skip)
