"""Mock-up pictures of PR7-R, drawn offscreen with real Qt widgets: python tools/mockup.py OUT_DIR"""
import json
import time
import os
import sys
import tempfile
from pathlib import Path

_cfg = Path(tempfile.gettempdir()) / "pr7r_offscreen.json"
_cfg.write_text(json.dumps({"screens": [{"name": "s", "x": 0, "y": 0, "width": 3200, "height": 2200,
                                          "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.environ.setdefault("QT_QPA_PLATFORM", f"offscreen:configfile={_cfg}")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPen  # noqa: E402
from PySide6.QtPdf import QPdfDocument, QPdfSearchModel  # noqa: E402
from PySide6.QtPdfWidgets import QPdfView  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,  # noqa: E402
                               QMenu, QSplitter, QTabBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from pr7r import theme, widgets  # noqa: E402
import sample_pdf  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/mockup")
out.mkdir(parents=True, exist_ok=True)
app = QApplication([])
theme.load_fonts()
work = Path(tempfile.mkdtemp())
GUIDE = sample_pdf.field_guide(work / "Night Skies.pdf")
OTHERS = [sample_pdf.short(work / f"{t}.pdf", t, s) for t, s in
          (("Inverter manual", 3), ("Tax return 2025", 11), ("Recipes from the coast", 21),
           ("Train timetable", 31), ("Lease agreement", 41))]

MENUS = {
    "&File": ["&Open...\tCtrl+O", "&Close\tCtrl+W", "-", "Save &As...\tCtrl+S", "Re&name...\tF2", "&Print...\tCtrl+P",
              "-", "Show in &folder", "Open &with PR7-E", "-", "P&roperties\tCtrl+D", "-", "1 Night Skies.pdf",
              "2 Inverter manual.pdf", "3 Tax return 2025.pdf", "-", "E&xit\tCtrl+Q"],
    "&View": ["&Single page\tCtrl+6", "&Facing\tCtrl+7", "&Book view\tCtrl+8", "Show &pages continuously", "-",
              "Rotate &left\tCtrl+Shift+-", "Rotate &right\tCtrl+Shift++", "-", "Pr&esentation\tF5",
              "F&ullscreen\tF11", "-", "Book&marks\tF12", "Show &toolbar\tF8", "-", "Select &all\tCtrl+A",
              "&Copy selection\tCtrl+C"],
    "&Go To": ["&Next page\tRight", "&Previous page\tLeft", "&First page\tHome", "&Last page\tEnd",
               "Pa&ge...\tCtrl+G", "-", "&Back\tAlt+Left", "F&orward\tAlt+Right", "-", "Fin&d...\tCtrl+F"],
    "&Zoom": ["Fit &page\tCtrl+0", "&Actual size\tCtrl+1", "Fit &width\tCtrl+2", "Fit &content\tCtrl+3", "-",
              "6400%", "3200%", "1600%", "800%", "400%", "200%", "150%", "125%", "100%", "50%", "25%", "-",
              "Custom &zoom...\tCtrl+Y"],
    "F&avorites": ["&Add to favorites\tCtrl+B", "&Remove from favorites", "Show &favorites"],
    "&Settings": ["&Finish", "&Options...", "-", "Check for &updates..."],
    "&Help": ["&Keyboard shortcuts", "&About Paragon PR7-R"],
}
CHECKED = {"Show &pages continuously", "Book&marks\tF12", "Show &toolbar\tF8", "Fit &page\tCtrl+0"}

EXTRA = """
QTabBar {{ background: {bg}; }}
QTabBar::tab {{ background: {bg}; color: {dim}; border: 1px solid {edge}; border-bottom: none; padding: 7px 14px;
  margin-right: 2px; border-top-left-radius: 5px; border-top-right-radius: 5px; min-width: 140px; }}
QTabBar::tab:selected {{ background: {widget}; color: {text}; border-top: 2px solid {accent}; }}
QTreeWidget {{ border: none; background: {bg}; show-decoration-selected: 0; }}
QTreeWidget::item:selected {{ background: {band}; color: #FFFFFF; }}
QTreeWidget::branch:selected {{ background: transparent; }}
QTabBar::close-button {{ image: url("{close}"); subcontrol-position: right; margin: 2px; }}
QTabBar::close-button:hover {{ background: {edge}; border-radius: 3px; }}
QLabel#side {{ color: {dim}; font-weight: 600; font-size: 11px; padding: 8px 10px 4px 10px; }}
QLabel#count {{ color: {dim}; padding: 0 6px; }}
"""


def keys_row(win, finder: str = "", home: bool = False) -> QWidget:
    page_fit = not finder
    bar = QWidget()
    bar.setAutoFillBackground(True)
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(12, 8, 12, 8)
    lay.setSpacing(4)

    def gap():
        line = QFrame(); line.setFixedSize(1, 22); line.setStyleSheet(f"background: {theme.PANEL_EDGE};")
        lay.addSpacing(6); lay.addWidget(line); lay.addSpacing(6)

    for name, tip in (("open", "Open"), ("print", "Print")):
        lay.addWidget(widgets.SmallKey(name, tip))
    gap()
    lay.addWidget(widgets.SmallKey("prev", "Previous page"))
    lay.addWidget(widgets.SmallKey("next", "Next page"))
    page = QLineEdit("" if home else "2" if finder else "4"); page.setFixedWidth(46); page.setAlignment(Qt.AlignCenter)
    lay.addSpacing(4); lay.addWidget(page)
    total = QLabel("" if home else "/ 18"); total.setObjectName("count"); lay.addWidget(total)
    gap()
    lay.addWidget(widgets.SmallKey("zoomout", "Zoom out"))
    lay.addWidget(widgets.SmallKey("zoomin", "Zoom in"))
    zoom = QComboBox(); zoom.addItems(["Fit Page" if page_fit else "Fit Width", "Fit Width" if page_fit else "Fit Page", "Actual Size", "200%", "100%", "50%"])
    zoom.setFixedWidth(118); lay.addSpacing(4); lay.addWidget(zoom)
    gap()
    fp = widgets.SmallKey("fitpage", "Fit page", True); fp.setChecked(page_fit); lay.addWidget(fp)
    fw = widgets.SmallKey("fitwidth", "Fit width", True); fw.setChecked(not page_fit); lay.addWidget(fw)
    lay.addWidget(widgets.SmallKey("facing", "Facing", True))
    lay.addWidget(widgets.SmallKey("rotate", "Rotate right"))
    gap()
    bm = widgets.SmallKey("bookmarks", "Bookmarks", True); bm.setChecked(True); lay.addWidget(bm)
    lay.addStretch(1)
    find = QLineEdit(finder); find.setPlaceholderText("Find"); find.setFixedWidth(220)
    lay.addWidget(widgets.SmallKey("search", "Find"))
    lay.addWidget(find)
    if finder:
        c = QLabel("4 of 14"); c.setObjectName("count"); lay.addWidget(c)
        lay.addWidget(widgets.SmallKey("prev", "Previous match"))
        lay.addWidget(widgets.SmallKey("next", "Next match"))
    return bar


def outline(section: int = 2) -> QTreeWidget:
    t = QTreeWidget()
    t.setHeaderHidden(True)
    t.setIndentation(16)
    cover = QTreeWidgetItem(["Cover"])
    t.addTopLevelItem(cover)
    for num, title, sections in sample_pdf.CHAPTERS:
        ch = QTreeWidgetItem([f"{num}  {title}"])
        t.addTopLevelItem(ch)
        for s in sections:
            ch.addChild(QTreeWidgetItem([s]))
        if num in "12":
            ch.setExpanded(True)
    t.setCurrentItem(t.topLevelItem(1).child(section))
    return t


def window(doc_view: QWidget, finder: str = "", side: bool = True, home: bool = False) -> QMainWindow:
    win = QMainWindow()
    win.resize(1280, 800)
    win.setWindowTitle("Night Skies.pdf - Paragon PR7-R")
    for title, items in MENUS.items():
        win.menuBar().addMenu(title)
    central = QWidget()
    col = QVBoxLayout(central)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(0)
    col.addWidget(widgets.Header("PDF READER"))
    col.addWidget(keys_row(win, finder, home))
    tabs = QTabBar()
    tabs.setTabsClosable(True)
    tabs.setDrawBase(False)
    for name in ("Night Skies.pdf", "Inverter manual.pdf", "Tax return 2025.pdf"):
        tabs.addTab(widgets.file_icon("document", 16), name)
    tabwrap = QWidget(); tw = QHBoxLayout(tabwrap); tw.setContentsMargins(10, 4, 10, 0); tw.addWidget(tabs); tw.addStretch(1)
    if not home:
        col.addWidget(tabwrap)
    split = QSplitter()
    split.setHandleWidth(1)
    if side:
        panel = QWidget(); pl = QVBoxLayout(panel); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(0)
        lbl = QLabel("BOOKMARKS"); lbl.setObjectName("side"); pl.addWidget(lbl); pl.addWidget(outline(0 if finder else 2))
        split.addWidget(panel)
    split.addWidget(doc_view)
    if side:
        split.setSizes([260, 1020])
    col.addWidget(split, 1)
    win.setCentralWidget(central)
    return win


class Pages(QWidget):
    """PR7-R's own page view (what the app will use instead of QPdfView, whose search marks are blue and can't be
    recoloured): pages rendered by QPdfDocument, laid out continuously, matches painted in family colours."""

    def __init__(self, first: int = 0, top: float = 0, fit_page: bool = True, search: str = "", current: int = 0):
        super().__init__()
        self.doc = QPdfDocument(self)
        self.doc.load(str(GUIDE))
        self.first, self.top, self.fit_page, self.current = first, top, fit_page, current
        self.hits = []
        if search:
            model = QPdfSearchModel(self)
            model.setDocument(self.doc)
            model.setSearchString(search)
            end = time.time() + 3
            from PySide6.QtCore import QModelIndex
            while model.rowCount(QModelIndex()) < 14 and time.time() < end:
                app.processEvents()
            self.hits = [model.resultAtIndex(i) for i in range(model.rowCount(QModelIndex()))]
            self.first = self.hits[current].page()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.PANEL if theme.FINISH == "obsidian" else "#D9D4D6"))
        size = self.doc.pagePointSize(0)
        m, gap = 18, 14
        k = (self.height() - 2 * m) / size.height() if self.fit_page else (self.width() - 80) / size.width()
        w, h = size.width() * k, size.height() * k
        x = (self.width() - w) / 2
        y = m - self.top * k
        if self.hits:
            y = 300 - self.hits[self.current].location().y() * k
        dpr = self.devicePixelRatioF()
        page = self.first
        while y < self.height() and page < self.doc.pageCount():
            r = QRectF(x, y, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 120 if theme.FINISH == "obsidian" else 35)); p.drawRect(r.translated(0, 3))
            img = self.doc.render(page, QSize(int(w * dpr), int(h * dpr)))
            p.fillRect(r, QColor("#FFFFFF"))  # QPdfDocument.render leaves the paper transparent
            p.drawImage(r, img)
            for i, hit in enumerate(self.hits):
                if hit.page() != page:
                    continue
                boxes = hit.rectangles()
                whole = boxes[0]
                for box in boxes[1:]:
                    whole = whole.united(box) if box.top() < whole.bottom() and box.bottom() > whole.top() else whole
                for box in [whole]:
                    b = QRectF(r.x() + box.x() * k, r.y() + box.y() * k, box.width() * k, box.height() * k).adjusted(-2, -1, 2, 1)
                    if i == self.current:
                        c = QColor(theme.LED_ORANGE); c.setAlphaF(.42)
                        p.setBrush(c); p.setPen(QPen(QColor(theme.ACCENT), 1.5))
                    else:
                        c = QColor(theme.ACCENT); c.setAlphaF(.18)
                        p.setBrush(c); p.setPen(Qt.NoPen)
                    p.drawRoundedRect(b, 2, 2)
            y += h + gap
            page += 1
        thumb = QRectF(self.width() - 8, 20 + (self.height() - 80) * self.first / self.doc.pageCount(), 4, 60)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.family_gradient(0, thumb.top(), 0, thumb.bottom()))
        p.drawRoundedRect(thumb, 2, 2)


class Home(QWidget):
    """SumatraPDF's start page: FREQUENTLY READ thumbnails, in family colours."""

    def __init__(self):
        super().__init__()
        self.thumbs = []
        for path in [GUIDE] + OTHERS:
            d = QPdfDocument(self); d.load(str(path))
            self.thumbs.append((path.stem + ".pdf", d.render(0, QSize(300, 424))))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BACKGROUND))
        f = QFont("Inter"); f.setPixelSize(15); f.setWeight(QFont.DemiBold)
        p.setFont(f); p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(60, 30, 600, 30), Qt.AlignLeft | Qt.AlignVCenter, "FREQUENTLY READ")
        bar = QRectF(60, 62, 120, 2)
        p.fillRect(bar, theme.family_gradient(bar.left(), 0, bar.right(), 0))
        tw, th, gx, gy = 150, 212, 44, 60
        for i, (name, img) in enumerate(self.thumbs):
            x, y = 60 + (i % 3) * (tw + gx), 90 + (i // 3) * (th + gy)
            r = QRectF(x, y, tw, th)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 160)); p.drawRoundedRect(r.translated(0, 4), 4, 4)
            p.fillRect(r, QColor("#FFFFFF"))  # QPdfDocument.render leaves the paper transparent
            p.drawImage(r, img)
            p.setPen(QPen(QColor(theme.PANEL_EDGE), 1)); p.setBrush(Qt.NoBrush); p.drawRect(r)
            if i == 0:
                p.setPen(QPen(theme.family_gradient(r.left(), 0, r.right(), 0), 2))
                p.drawRoundedRect(r.adjusted(-4, -4, 4, 4), 5, 5)
            f2 = QFont("Inter"); f2.setPixelSize(12); p.setFont(f2); p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(x - 10, y + th + 8, tw + 20, 18), Qt.AlignCenter, name)
        f3 = QFont("Inter"); f3.setPixelSize(12); f3.setWeight(QFont.DemiBold); p.setFont(f3)
        right = QRectF(self.width() - 330, 90, 270, 400)
        p.setPen(QColor(theme.TEXT_DIM)); p.drawText(QRectF(right.left(), right.top(), 270, 20), Qt.AlignLeft, "START")
        y = right.top() + 34
        for icon, text in (("open", "Open a document...   Ctrl+O"), ("star", "Favorites"), ("recent", "Hide frequently read")):
            widgets.draw_icon(p, icon, QRectF(right.left(), y - 2, 20, 20), QColor(theme.LED_ORANGE), 1.6)
            p.setPen(QColor(theme.TEXT)); p.drawText(QRectF(right.left() + 30, y, 240, 18), Qt.AlignLeft | Qt.AlignVCenter, text)
            y += 32
        p.setPen(QColor(theme.TEXT_DIM))
        f4 = QFont("Inter"); f4.setPixelSize(12); p.setFont(f4)
        p.drawText(QRectF(right.left(), y + 20, 270, 80), Qt.TextWordWrap,
                   "Drop a PDF here, or open one from PR7-E or Explorer.")


def shoot(win: QMainWindow, name: str, menu: str | None = None) -> None:
    import time
    win.show()
    end = time.time() + 4  # QPdfView renders pages on a worker thread: give it time
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)
    img = win.grab().toImage()
    if menu:
        m = QMenu(win)
        for text in MENUS[menu]:
            if text == "-":
                m.addSeparator()
            else:
                a = m.addAction(text)
                if text in CHECKED:
                    a.setCheckable(True); a.setChecked(True)
        m.ensurePolished()
        m.resize(m.sizeHint())
        acts = [a for a in win.menuBar().actions() if a.text() == menu]
        at = win.menuBar().actionGeometry(acts[0]).bottomLeft()
        m.popup(win.mapToGlobal(at)); app.processEvents()
        m.setActiveAction(m.actions()[{"&View": 3, "&Zoom": 2}.get(menu, 0)]); app.processEvents()
        p = QPainter(img)
        p.drawPixmap(at, m.grab())
        p.end()
        m.hide()
    img.save(str(out / f"{name}.png"))
    print(out / f"{name}.png")
    win.close()


def close_svg() -> str:
    path = Path(tempfile.gettempdir()) / f"pr7r_close_{theme.FINISH}.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                    f'<path d="M3 3 L9 9 M9 3 L3 9" stroke="{theme.TEXT_DIM}" stroke-width="1.5" '
                    'stroke-linecap="round"/></svg>')
    return path.as_posix()


def all_shots():
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet() + EXTRA.format(
        bg=theme.BACKGROUND, panel=theme.PANEL, edge=theme.PANEL_EDGE, widget=theme.WIDGET, text=theme.TEXT,
        dim=theme.TEXT_DIM, accent=theme.ACCENT, close=close_svg(), band=theme.qss_gradient(theme.LIT)))
    suffix = "" if theme.FINISH == "obsidian" else "_aurora"
    shoot(window(Pages(first=3)), "main" + suffix)
    if suffix:
        return
    shoot(window(Pages(fit_page=False, search="Moon", current=3), finder="Moon"), "find")
    shoot(window(Pages(first=3), side=False), "view_menu", menu="&View")
    shoot(window(Home(), side=False, home=True), "home")


all_shots()
theme.set_finish("aurora")
all_shots()
