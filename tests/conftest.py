import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["PARAGON_FAMILY_FILE"] = os.path.join(__import__("tempfile").mkdtemp(prefix="family-"), "finish")  # never the real choice
# QtPdf notes bookmarks without an exact place on the page (pypdf writes them so): harmless, and noisy.
os.environ.setdefault("QT_LOGGING_RULES", "qt.pdf.*=false")
# Tests never touch the real data folder (history, thumbnails): PR7R_DATA points at a folder of its own.
os.environ["PR7R_DATA"] = tempfile.mkdtemp(prefix="pr7r-data-")


@pytest.fixture(scope="session")
def qapp(tmp_path_factory):
    # Tests never write the real settings: QSettings goes to INI files in a temp folder.
    from PySide6.QtCore import QSettings, QThreadPool
    from PySide6.QtWidgets import QApplication
    from pr7r import theme
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path_factory.mktemp("settings")))
    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    from pr7r.main_window import apply_look
    apply_look(app)
    yield app
    # Qt's offscreen platform can crash at exit with text left on its clipboard or windows still open.
    QThreadPool.globalInstance().waitForDone(15000)
    for w in app.topLevelWidgets():
        w.close()
    app.clipboard().clear()
    app.processEvents()


@pytest.fixture(autouse=True)
def own_data(tmp_path, monkeypatch):
    monkeypatch.setenv("PR7R_DATA", str(tmp_path / "_data"))
    yield


@pytest.fixture
def clean_settings(qapp):
    from PySide6.QtCore import QSettings
    s = QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, "Paragon", "PR7-R")
    s.clear()
    s.sync()
    yield
    s.clear()
    s.sync()


@pytest.fixture(scope="session")
def _book_master(tmp_path_factory, qapp):
    import sample_pdf
    d = tmp_path_factory.mktemp("pdfs")
    return {"book": sample_pdf.book(d / "Night Skies.pdf"),
            "locked": sample_pdf.book(d / "Locked.pdf", password="secret"),
            "short": sample_pdf.short(d / "Inverter manual.pdf", "Inverter manual", 3, pages=3)}


@pytest.fixture
def pdfs(_book_master, tmp_path):
    """Fresh copies of the test PDFs in this test's folder (tests may rename or rewrite them)."""
    out = {}
    for k, p in _book_master.items():
        out[k] = tmp_path / p.name
        shutil.copy2(p, out[k])
    return out


@pytest.fixture
def window(qapp, clean_settings):
    from pr7r.main_window import MainWindow
    w = MainWindow()
    # An error box nobody answers would wait forever (as it did on Windows CI): fail the test with its text instead.
    w.answers["error"] = lambda text: pytest.fail(f"PR7-R showed an error: {text}")
    w.resize(1200, 800)
    w.show()
    qapp.processEvents()
    yield w
    w.close()
    w.deleteLater()
    qapp.processEvents()
