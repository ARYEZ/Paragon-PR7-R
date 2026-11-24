"""Screenshots of the real window (offscreen) on sample PDFs: python tools/screenshots.py OUT_DIR"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

_cfg = Path(tempfile.gettempdir()) / "pr7r_offscreen.json"
_cfg.write_text(json.dumps({"screens": [{"name": "s", "x": 0, "y": 0, "width": 3200, "height": 2200,
                                          "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_cfg}")
os.environ.setdefault("QT_LOGGING_RULES", "qt.pdf.*=false")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
work = Path(tempfile.mkdtemp())
os.environ["PR7R_DATA"] = str(work / "data")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QSettings.setDefaultFormat(QSettings.Format.IniFormat)
QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(work / "settings"))
import sample_pdf  # noqa: E402
from pr7r import layout, theme  # noqa: E402
from pr7r.main_window import MainWindow, apply_look  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
apply_look(app)
docs = work / "docs"
docs.mkdir()
BOOK = sample_pdf.book(docs / "Night Skies.pdf")
OTHERS = [sample_pdf.short(docs / f"{t}.pdf", t, s) for t, s in
          (("Inverter manual", 3), ("Tax return 2025", 11), ("Recipes from the coast", 21),
           ("Train timetable", 31), ("Lease agreement", 41))]


def settle():
    end = time.time() + 0.6
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def shot(w, name):
    settle()
    w.grab().save(str(out / f"{name}.png"))
    print(out / f"{name}.png")


w = MainWindow()
w.resize(1280, 800)
w.show()
for p in reversed(OTHERS):                       # history for the start page
    w.open_files([str(p)])
    w.close_tab(0)
for _ in range(3):
    w.open_files([str(BOOK)])
    w.close_tab(0)
shot(w, "home")
w.open_files([str(BOOK), str(OTHERS[0]), str(OTHERS[1])])
w.tabs.setCurrentIndex(0)
w.view.set_zoom(layout.FIT_PAGE)
w.view.go_to(3, record=False)
shot(w, "main_window")
w.set_zoom(layout.FIT_WIDTH)
w.find_box.setText("Moon")
w.find_next(True)
w.find_next(True)
shot(w, "find")
w.find_box.clear(); w._find_edited()
w.set_mode(layout.FACING)
w.set_zoom(layout.FIT_PAGE)
w.view.go_to(5, record=False)
shot(w, "facing")
w.set_mode(layout.SINGLE)
w.set_finish("aurora")
w.view.go_to(3, record=False)
shot(w, "main_window_aurora")
w.set_finish("obsidian")
w.close()
