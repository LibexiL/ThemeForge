import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# ThemeForge reads HOME at import time, so point it at a throwaway folder first
_HOME = Path(tempfile.mkdtemp(prefix="themeforge-test-home-"))
os.environ["HOME"] = str(_HOME)
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
