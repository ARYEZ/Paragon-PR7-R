"""PR7-R's window, laid out and behaving like SumatraPDF's: menus (File, View, Go To, Zoom, Favorites, Settings,
Help), the toolbar, a tab per document, the Bookmarks panel, Find, the start page with Frequently read, and
presentation / fullscreen.

Anything that would ask the user goes through `_ask(kind, ...)`; tests answer it with `window.answers[kind]`."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDesktopServices, QFont, QImage, QKeySequence, QPainter, QPen
from PySide6.QtPdf import QPdfBookmarkModel, QPdfDocument
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                               QPushButton, QSplitter, QStackedWidget, QTabBar, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import __version__, family, history, layout, settings, theme, widgets
from .pageview import PageView, find_in_page

PDF_FILTER = "PDF documents (*.pdf);;All files (*)"
ZOOM_CHOICES = [("Fit Page", layout.FIT_PAGE), ("Fit Width", layout.FIT_WIDTH), ("Actual Size", 100)] + \
               [(f"{z:g}%", z) for z in (400, 200, 150, 125, 100, 75, 50, 25)]

EXTRA = """
QTabBar {{ background: {bg}; }}
QTabBar::tab {{ background: {bg}; color: {dim}; border: 1px solid {edge}; border-bottom: none; padding: 7px 14px;
  margin-right: 2px; border-top-left-radius: 5px; border-top-right-radius: 5px; min-width: 120px; max-width: 260px; }}
QTabBar::tab:selected {{ background: {widget}; color: {text}; border-top: 2px solid {accent}; }}
QTabBar::close-button {{ image: url("{close}"); subcontrol-position: right; margin: 2px; }}
QTabBar::close-button:hover {{ background: {edge}; border-radius: 3px; }}
QTreeWidget#bookmarks {{ border: none; background: {bg}; show-decoration-selected: 0; }}
QTreeWidget#bookmarks::item:selected {{ background: {band}; color: #FFFFFF; }}
QTreeWidget#bookmarks::branch:selected {{ background: transparent; }}
QLabel#side {{ color: {dim}; font-weight: 600; font-size: 11px; padding: 8px 10px 4px 10px; }}
QLabel#count {{ color: {dim}; padding: 0 6px; }}
"""


def _close_svg() -> str:
    import tempfile
    path = Path(tempfile.gettempdir()) / f"pr7r_close_{theme.FINISH}.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12">'
                    f'<path d="M3 3 L9 9 M9 3 L3 9" stroke="{theme.TEXT_DIM}" stroke-width="1.5" '
                    'stroke-linecap="round"/></svg>')
    return path.as_posix()


def stylesheet() -> str:
    return theme.stylesheet() + EXTRA.format(
        bg=theme.BACKGROUND, edge=theme.PANEL_EDGE, widget=theme.WIDGET, text=theme.TEXT, dim=theme.TEXT_DIM,
        accent=theme.ACCENT, close=_close_svg(), band=theme.qss_gradient(theme.LIT))


def apply_look(app: QApplication) -> None:
    app.setPalette(theme.palette())
    app.setStyleSheet(stylesheet())


def zoom_text(z) -> str:
    if z == layout.FIT_PAGE:
        return "Fit Page"
    if z == layout.FIT_WIDTH:
        return "Fit Width"
    return f"{float(z):g}%"


def zoom_value(text: str):
    t = text.strip().lower().replace(" ", "")
    if t == "fitpage":
        return layout.FIT_PAGE
    if t == "fitwidth":
        return layout.FIT_WIDTH
    if t == "actualsize":
        return 100.0
    try:
        return float(t.rstrip("%"))
    except ValueError:
        return None


# ============================================================================ a document
class Doc:
    """One open document: its file, QtPdf document, page view and outline."""

    def __init__(self, path: str, pdf: QPdfDocument, view: PageView):
        self.path = os.path.abspath(path)
        self.pdf = pdf
        self.view = view
        self.outline: list[tuple[int, str, int, QPointF]] = []    # (level, title, page, location)
        self.search_text = ""
        self.search_case = False

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def read_outline(self) -> None:
        model = QPdfBookmarkModel()
        model.setDocument(self.pdf)
        out = []

        def walk(parent, level):
            for row in range(model.rowCount(parent)):
                idx = model.index(row, 0, parent)
                out.append((level, str(model.data(idx, QPdfBookmarkModel.Role.Title.value) or ""),
                            int(model.data(idx, QPdfBookmarkModel.Role.Page.value) or 0),
                            model.data(idx, QPdfBookmarkModel.Role.Location.value) or QPointF()))
                walk(idx, level + 1)
        from PySide6.QtCore import QModelIndex
        walk(QModelIndex(), 0)
        self.outline = out


# ============================================================================ the start page
class Home(QWidget):
    """SumatraPDF's start page: Frequently read (thumbnails of the documents opened most) and Open a document."""
    opened = Signal(str)
    open_dialog = Signal()

    TW, TH, GX, GY = 150, 212, 44, 64

    def __init__(self, hist: history.History, parent=None):
        super().__init__(parent)
        self.hist = hist
        self.items: list[tuple[str, QImage | None, QRectF]] = []
        self.hover = -1
        self.setMouseTracking(True)

    def refresh(self) -> None:
        self.items = []
        if settings.get_bool("show_frequent", True):
            for e in self.hist.frequent():
                self.items.append((e.path, thumbnail(e.path), QRectF()))
        self.update()

    def _layout(self):
        cols = max(1, int((self.width() - 400) // (self.TW + self.GX)))
        for i, (path, img, _) in enumerate(self.items):
            x, y = 60 + (i % cols) * (self.TW + self.GX), 90 + (i // cols) * (self.TH + self.GY)
            self.items[i] = (path, img, QRectF(x, y, self.TW, self.TH))

    def links(self) -> list[tuple[str, str, QRectF]]:
        x = max(self.width() - 330, 60 + self.TW + self.GX)
        names = [("open", "Open a document...   Ctrl+O"),
                 ("recent", "Show frequently read" if not settings.get_bool("show_frequent", True)
                  else "Hide frequently read")]
        return [(icon, text, QRectF(x, 124 + 32 * i, 270, 22)) for i, (icon, text) in enumerate(names)]

    def paintEvent(self, _):
        self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.BACKGROUND))
        f = QFont("Inter"); f.setPixelSize(15); f.setWeight(QFont.Weight.DemiBold)
        p.setFont(f); p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(60, 30, 600, 30), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "FREQUENTLY READ" if settings.get_bool("show_frequent", True) else "PARAGON PR7-R")
        bar = QRectF(60, 62, 120, 2)
        p.fillRect(bar, theme.family_gradient(bar.left(), 0, bar.right(), 0))
        f2 = QFont("Inter"); f2.setPixelSize(12)
        for i, (path, img, r) in enumerate(self.items):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 160 if theme.FINISH == "obsidian" else 40))
            p.drawRoundedRect(r.translated(0, 4), 4, 4)
            p.fillRect(r, QColor("#FFFFFF"))
            if img is not None and not img.isNull():
                p.drawImage(r, img)
            p.setPen(QPen(QColor(theme.PANEL_EDGE), 1)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawRect(r)
            if i == self.hover:
                p.setPen(QPen(theme.family_gradient(r.left(), 0, r.right(), 0), 2))
                p.drawRoundedRect(r.adjusted(-4, -4, 4, 4), 5, 5)
            p.setFont(f2); p.setPen(QColor(theme.TEXT))
            name = p.fontMetrics().elidedText(os.path.basename(path), Qt.TextElideMode.ElideMiddle, self.TW + 30)
            p.drawText(QRectF(r.x() - 15, r.bottom() + 8, self.TW + 30, 18), Qt.AlignmentFlag.AlignCenter, name)
        links = self.links()
        f3 = QFont("Inter"); f3.setPixelSize(12); f3.setWeight(QFont.Weight.DemiBold); p.setFont(f3)
        x = links[0][2].x()
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(x, 90, 270, 20), Qt.AlignmentFlag.AlignLeft, "START")
        for icon, text, r in links:
            widgets.draw_icon(p, icon, QRectF(r.x(), r.y(), 20, 20), QColor(theme.LED_ORANGE), 1.6)
            p.setPen(QColor(theme.TEXT))
            p.drawText(QRectF(r.x() + 30, r.y(), 240, 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       text)
        p.setFont(f2); p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(QRectF(x, links[-1][2].bottom() + 26, 270, 60), Qt.TextFlag.TextWordWrap,
                   "Drop a PDF here, or open one from PR7-E or Explorer.")

    def item_at(self, pos) -> int:
        for i, (_, _, r) in enumerate(self.items):
            if r.adjusted(-6, -6, 6, 30).contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self.item_at(e.position())
        on_link = any(r.contains(e.position()) for _, _, r in self.links())
        self.setCursor(Qt.CursorShape.PointingHandCursor if i >= 0 or on_link else Qt.CursorShape.ArrowCursor)
        if i != self.hover:
            self.hover = i
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        i = self.item_at(e.position())
        if i >= 0:
            self.opened.emit(self.items[i][0])
            return
        for icon, _, r in self.links():
            if r.contains(e.position()):
                if icon == "open":
                    self.open_dialog.emit()
                else:
                    settings.set("show_frequent", not settings.get_bool("show_frequent", True))
                    self.refresh()

    def contextMenuEvent(self, e):
        i = self.item_at(QPointF(e.pos()))
        if i < 0:
            return
        m = QMenu(self)
        m.addAction("Open", lambda: self.opened.emit(self.items[i][0]))
        m.addAction("Remove from history", lambda: (self.hist.hide(self.items[i][0]), self.refresh()))
        m.exec(e.globalPos())


def load_pdf(pdf: QPdfDocument, path: str) -> QPdfDocument.Error:
    """Load a PDF from a copy of its bytes in memory, not from the file. QtPdf keeps a file it loaded open, and Windows
    won't rename or overwrite an open file; SumatraPDF doesn't lock documents either, so PR7-R's Rename works and
    another program can rewrite the PDF while it's shown (it's then reloaded)."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return QPdfDocument.Error.FileNotFound
    buf = QBuffer(pdf)                    # owned by the document: it reads pages from it as needed
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    old = getattr(pdf, "_buffer", None)
    pdf._buffer = buf
    pdf.load(buf)
    if old is not None:
        old.deleteLater()
    # Loading from a device is asynchronous in Qt: it's done once the status says Ready or Error.
    while pdf.status() == QPdfDocument.Status.Loading:
        QApplication.processEvents()
    return pdf.error()


def thumbnail(path: str) -> QImage | None:
    """The first page as a 300 px wide picture, kept in the data folder while the file is unchanged."""
    import hashlib
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = hashlib.sha1(f"{os.path.normcase(os.path.abspath(path))}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()
    cache = history.data_dir() / "thumbnails" / f"{key[:20]}.png"
    if cache.exists():
        img = QImage(str(cache))
        if not img.isNull():
            return img
    doc = QPdfDocument()
    if load_pdf(doc, path) != QPdfDocument.Error.None_ or doc.pageCount() == 0:
        return None
    s = doc.pagePointSize(0)
    img = doc.render(0, QSize(300, int(300 * s.height() / max(s.width(), 1))))
    out = QImage(img.size(), QImage.Format.Format_RGB32)
    out.fill(QColor("#FFFFFF"))
    p = QPainter(out); p.drawImage(0, 0, img); p.end()
    doc.close()
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        out.save(str(cache))
    except OSError:
        pass
    return out


# ============================================================================ the window
class MainWindow(QMainWindow):
    def __init__(self, files: list[str] | None = None, hist: history.History | None = None, page: int | None = None):
        super().__init__()
        self.answers: dict = {}          # tests: kind -> answer, instead of dialogs
        self.hist = hist or history.History()
        self.docs: list[Doc] = []
        self.fullscreen = None           # None, "fullscreen" or "presentation"
        self._before_full = None
        self.resize(1280, 820)
        self.setAcceptDrops(True)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self._file_changed)
        self._reloads: dict[str, QTimer] = {}
        self._build()
        self._build_menus()
        self.home.refresh()
        self._sync()
        if files:
            self.open_files(files, page=page)
        elif settings.get_bool("restore_session", True):
            self.open_files([p for p in settings.get_list("session") if os.path.isfile(p)], quiet=True)
            current = settings.get("session_current", "")
            for i, d in enumerate(self.docs):
                if os.path.normcase(d.path) == os.path.normcase(current):
                    self.tabs.setCurrentIndex(i)

    # ------------------------------------------------------------------ building
    def _key(self, icon, tip, slot, checkable=False):
        k = widgets.SmallKey(icon, tip, checkable)
        k.clicked.connect(slot)
        return k

    def _build(self):
        central = QWidget()
        col = QVBoxLayout(central)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.header = widgets.Header("PDF READER")
        col.addWidget(self.header)
        self.toolbar = QWidget()
        bar = QHBoxLayout(self.toolbar)
        bar.setContentsMargins(12, 8, 12, 8)
        bar.setSpacing(4)

        def gap():
            line = QFrame(); line.setFixedSize(1, 22); line.setObjectName("gap")
            line.setStyleSheet(f"background: {theme.PANEL_EDGE};")
            bar.addSpacing(6); bar.addWidget(line); bar.addSpacing(6)

        bar.addWidget(self._key("open", "Open (Ctrl+O)", self.open_dialog))
        self.k_print = self._key("print", "Print (Ctrl+P)", self.print_document)
        bar.addWidget(self.k_print)
        gap()
        self.k_prev = self._key("prev", "Previous page", lambda: self.view and self.view.prev_page())
        self.k_next = self._key("next", "Next page", lambda: self.view and self.view.next_page())
        bar.addWidget(self.k_prev); bar.addWidget(self.k_next)
        self.page_box = QLineEdit(); self.page_box.setFixedWidth(52); self.page_box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_box.setToolTip("Page (Ctrl+G)")
        self.page_box.returnPressed.connect(self._page_entered)
        bar.addSpacing(4); bar.addWidget(self.page_box)
        self.page_total = QLabel(""); self.page_total.setObjectName("count")
        bar.addWidget(self.page_total)
        gap()
        self.k_zoom_out = self._key("zoomout", "Zoom out (Ctrl+-)", lambda: self.view and self.view.zoom_step(False))
        self.k_zoom_in = self._key("zoomin", "Zoom in (Ctrl++)", lambda: self.view and self.view.zoom_step(True))
        bar.addWidget(self.k_zoom_out); bar.addWidget(self.k_zoom_in)
        self.zoom_box = QComboBox(); self.zoom_box.setEditable(True); self.zoom_box.setFixedWidth(122)
        for text, _ in ZOOM_CHOICES:
            self.zoom_box.addItem(text)
        self.zoom_box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.zoom_box.activated.connect(lambda i: self.set_zoom(ZOOM_CHOICES[i][1]))
        self.zoom_box.lineEdit().returnPressed.connect(lambda: self.set_zoom(zoom_value(self.zoom_box.currentText())))
        bar.addSpacing(4); bar.addWidget(self.zoom_box)
        gap()
        self.k_fitpage = self._key("fitpage", "Fit page (Ctrl+0)", lambda: self.set_zoom(layout.FIT_PAGE), True)
        self.k_fitwidth = self._key("fitwidth", "Fit width (Ctrl+2)", lambda: self.set_zoom(layout.FIT_WIDTH), True)
        self.k_facing = self._key("facing", "Facing (Ctrl+7)", lambda: self.set_mode(
            layout.SINGLE if self.view and self.view.mode == layout.FACING else layout.FACING), True)
        self.k_rotate = self._key("rotate", "Rotate right (Ctrl+Shift++)", lambda: self.rotate(90))
        for k in (self.k_fitpage, self.k_fitwidth, self.k_facing, self.k_rotate):
            bar.addWidget(k)
        gap()
        self.k_bookmarks = self._key("bookmarks", "Bookmarks (F12)", lambda: self.show_bookmarks(not self.side.isVisible()),
                                     True)
        bar.addWidget(self.k_bookmarks)
        bar.addStretch(1)
        bar.addWidget(self._key("search", "Find (Ctrl+F)", self.focus_find))
        self.find_box = QLineEdit(); self.find_box.setPlaceholderText("Find"); self.find_box.setFixedWidth(220)
        self.find_box.setClearButtonEnabled(True)
        self.find_box.installEventFilter(self)
        self.find_box.returnPressed.connect(lambda: self.find_next(True))
        self.find_box.textEdited.connect(self._find_edited)
        bar.addWidget(self.find_box)
        self.k_case = self._key("case", "Match case", self._find_edited, True)
        bar.addWidget(self.k_case)
        self.find_count = QLabel(""); self.find_count.setObjectName("count")
        bar.addWidget(self.find_count)
        self.k_find_prev = self._key("prev", "Previous match (Shift+F3)", lambda: self.find_next(False))
        self.k_find_next = self._key("next", "Next match (F3)", lambda: self.find_next(True))
        bar.addWidget(self.k_find_prev); bar.addWidget(self.k_find_next)
        col.addWidget(self.toolbar)

        self.tabs = QTabBar()
        self.tabs.setTabsClosable(True)
        self.tabs.setDrawBase(False)
        self.tabs.setMovable(True)
        self.tabs.setExpanding(False)
        self.tabs.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabMoved.connect(self._tab_moved)
        self.tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._tab_menu)
        self.tabwrap = QWidget()
        tw = QHBoxLayout(self.tabwrap)
        tw.setContentsMargins(10, 4, 10, 0)
        tw.addWidget(self.tabs)
        tw.addStretch(1)
        col.addWidget(self.tabwrap)

        self.split = QSplitter()
        self.split.setHandleWidth(1)
        self.side = QWidget()
        sl = QVBoxLayout(self.side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        lbl = QLabel("BOOKMARKS"); lbl.setObjectName("side")
        sl.addWidget(lbl)
        self.tree = QTreeWidget()
        self.tree.setObjectName("bookmarks")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.itemClicked.connect(self._bookmark_clicked)
        self.tree.itemActivated.connect(self._bookmark_clicked)
        sl.addWidget(self.tree)
        self.split.addWidget(self.side)
        self.stack = QStackedWidget()
        self.home = Home(self.hist)
        self.home.opened.connect(lambda p: self.open_files([p]))
        self.home.open_dialog.connect(self.open_dialog)
        self.stack.addWidget(self.home)
        self.split.addWidget(self.stack)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([260, 1020])
        col.addWidget(self.split, 1)
        self.setCentralWidget(central)

    def _act(self, menu, text, slot=None, shortcut=None, checkable=False, key=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, (list, tuple)) else [shortcut])])
        if checkable:
            a.setCheckable(True)
        if slot:
            a.triggered.connect(slot)
        menu.addAction(a)
        if key:
            self.actions_by_key[key] = a
        return a

    def _build_menus(self):
        self.actions_by_key: dict[str, QAction] = {}
        mb = self.menuBar()
        f = mb.addMenu("&File")
        self._act(f, "&Open...", self.open_dialog, "Ctrl+O", key="open")
        self._act(f, "&Close", lambda: self.close_tab(self.tabs.currentIndex()), ["Ctrl+W", "Ctrl+F4"], key="close")
        f.addSeparator()
        self._act(f, "Save &As...", self.save_as, "Ctrl+S", key="save_as")
        self._act(f, "Re&name...", self.rename, "F2", key="rename")
        self._act(f, "&Print...", self.print_document, "Ctrl+P", key="print")
        f.addSeparator()
        self._act(f, "Show in &folder", self.show_in_folder, key="folder")
        f.addSeparator()
        self._act(f, "P&roperties", self.properties, "Ctrl+D", key="properties")
        self.recent_sep = f.addSeparator()
        self.file_menu = f
        self.recent_actions: list[QAction] = []
        self.exit_sep = f.addSeparator()
        self._act(f, "E&xit", self.close, "Ctrl+Q")
        f.aboutToShow.connect(self._fill_recent)

        v = mb.addMenu("&View")
        g = QActionGroup(self)
        for text, mode, sc in (("&Single page", layout.SINGLE, "Ctrl+6"), ("&Facing", layout.FACING, "Ctrl+7"),
                               ("&Book view", layout.BOOK, "Ctrl+8")):
            a = self._act(v, text, lambda _=False, m=mode: self.set_mode(m), sc, True, key=mode)
            g.addAction(a)
        self._act(v, "Show &pages continuously", lambda on: self.set_continuous(on), None, True, key="continuous")
        v.addSeparator()
        self._act(v, "Rotate &left", lambda: self.rotate(-90), "Ctrl+Shift+-", key="rotate_left")
        self._act(v, "Rotate &right", lambda: self.rotate(90), ["Ctrl+Shift++", "Ctrl+Shift+="], key="rotate_right")
        v.addSeparator()
        self._act(v, "Pr&esentation", lambda: self.set_fullscreen("presentation"), ["F5", "Ctrl+L"], key="presentation")
        self._act(v, "F&ullscreen", lambda: self.set_fullscreen("fullscreen"), ["F11", "Ctrl+Shift+L"], key="fullscreen")
        v.addSeparator()
        self._act(v, "Book&marks", lambda on: self.show_bookmarks(on), "F12", True, key="bookmarks")
        self._act(v, "Show &toolbar", lambda on: self.show_toolbar(on), "F8", True, key="toolbar")
        v.addSeparator()
        self._act(v, "Select &all", lambda: self.view and self.view.select_all(), "Ctrl+A", key="select_all")
        self._act(v, "&Copy selection", self.copy, ["Ctrl+C", "Ctrl+Insert"], key="copy")

        go = mb.addMenu("&Go To")
        self._act(go, "&Next page", lambda: self.view and self.view.next_page(), None, key="next")
        self._act(go, "&Previous page", lambda: self.view and self.view.prev_page(), None, key="prev")
        self._act(go, "&First page", lambda: self.view and self.view.go_to(0), "Ctrl+Home", key="first")
        self._act(go, "&Last page", lambda: self.view and self.view.go_to(self.view.page_count() - 1), "Ctrl+End",
                  key="last")
        self._act(go, "Pa&ge...", self.go_to_page_dialog, "Ctrl+G", key="goto")
        go.addSeparator()
        self._act(go, "&Back", lambda: self.view and self.view.back(), ["Alt+Left"], key="back")
        self._act(go, "F&orward", lambda: self.view and self.view.forward(), ["Alt+Right"], key="forward")
        go.addSeparator()
        self._act(go, "Fin&d...", self.focus_find, "Ctrl+F", key="find")
        self._act(go, "Find &next", lambda: self.find_next(True), "F3", key="find_next")
        self._act(go, "Find pre&vious", lambda: self.find_next(False), "Shift+F3", key="find_prev")

        z = mb.addMenu("&Zoom")
        zg = QActionGroup(self)
        for text, val, sc in (("Fit &page", layout.FIT_PAGE, "Ctrl+0"), ("&Actual size", 100.0, "Ctrl+1"),
                              ("Fit &width", layout.FIT_WIDTH, "Ctrl+2")):
            zg.addAction(self._act(z, text, lambda _=False, x=val: self.set_zoom(x), sc, True, key=f"zoom_{val}"))
        z.addSeparator()
        for pct in layout.ZOOMS:
            zg.addAction(self._act(z, f"{pct:g}%", lambda _=False, x=pct: self.set_zoom(float(x)), None, True,
                                   key=f"zoom_{float(pct)}"))
        z.addSeparator()
        self._act(z, "Zoom &in", lambda: self.view and self.view.zoom_step(True), ["Ctrl++", "Ctrl+="], key="zoom_in")
        self._act(z, "Zoom &out", lambda: self.view and self.view.zoom_step(False), "Ctrl+-", key="zoom_out")
        self._act(z, "Custom &zoom...", self.custom_zoom, "Ctrl+Y", key="custom_zoom")
        self.zoom_group = zg

        self.fav_menu = mb.addMenu("F&avorites")
        self.fav_menu.aboutToShow.connect(self._fill_favorites)

        s = mb.addMenu("&Settings")
        fin = s.addMenu("&Finish")
        fg = QActionGroup(self)
        for name in theme.FINISHES:
            a = self._act(fin, name.upper(), lambda _=False, n=name: self.set_finish(n), None, True, key=f"finish_{name}")
            a.setChecked(name == theme.FINISH)
            fg.addAction(a)
        self._act(s, "&Options...", self.options, key="options")
        s.addSeparator()
        self._act(s, "Check for &updates...", self.check_updates, key="updates")

        h = mb.addMenu("&Help")
        self._act(h, "&Keyboard shortcuts", self.shortcuts, "F1", key="shortcuts")
        h.addSeparator()
        self._act(h, "&About Paragon PR7-R", self.about, key="about")

        self.actions_by_key["bookmarks"].setChecked(settings.get_bool("show_bookmarks", True))
        self.actions_by_key["toolbar"].setChecked(settings.get_bool("show_toolbar", True))
        self.toolbar.setVisible(settings.get_bool("show_toolbar", True))
        # Keys that work anywhere in the window except text fields: Esc leaves fullscreen.
        esc = QAction(self); esc.setShortcut(QKeySequence("Escape")); esc.triggered.connect(self._escape)
        self.addAction(esc)
        for seq, slot in (("Ctrl+Tab", lambda: self._cycle(1)), ("Ctrl+Shift+Tab", lambda: self._cycle(-1)),
                          ("Ctrl+PgDown", lambda: self._cycle(1)), ("Ctrl+PgUp", lambda: self._cycle(-1))):
            a = QAction(self); a.setShortcut(QKeySequence(seq)); a.triggered.connect(slot); self.addAction(a)

    # ------------------------------------------------------------------ asking
    def _ask(self, kind: str, *args):
        if kind in self.answers:
            a = self.answers[kind]
            return a(*args) if callable(a) else a
        if kind == "password":
            text, ok = QInputDialog.getText(self, "Password", f"{args[0]} is protected by a password.\nPassword:",
                                            QLineEdit.EchoMode.Password)
            return text if ok else None
        if kind == "open":
            files, _ = QFileDialog.getOpenFileNames(self, "Open", settings.get("last_dir", ""), PDF_FILTER)
            return files
        if kind == "save_as":
            path, _ = QFileDialog.getSaveFileName(self, "Save As", args[0], PDF_FILTER)
            return path or None
        if kind == "rename":
            text, ok = QInputDialog.getText(self, "Rename", "New name:", QLineEdit.EchoMode.Normal, args[0])
            return text if ok else None
        if kind == "page":
            n, ok = QInputDialog.getInt(self, "Go to Page", f"Page number (1 - {args[1]}):", args[0], 1, args[1])
            return n if ok else None
        if kind == "zoom":
            text, ok = QInputDialog.getText(self, "Custom Zoom", "Zoom (%):", QLineEdit.EchoMode.Normal, args[0])
            return text if ok else None
        if kind == "error":
            QMessageBox.warning(self, "Paragon PR7-R", args[0])
            return None
        if kind == "print":
            return None
        return None

    # ------------------------------------------------------------------ documents
    @property
    def doc(self) -> Doc | None:
        i = self.tabs.currentIndex()
        return self.docs[i] if 0 <= i < len(self.docs) else None

    @property
    def view(self) -> PageView | None:
        d = self.doc
        return d.view if d else None

    def open_dialog(self):
        files = self._ask("open")
        if files:
            settings.set("last_dir", os.path.dirname(files[0]))
            self.open_files(files)

    def open_files(self, files: list[str], page: int | None = None, quiet: bool = False) -> None:
        """Open each file in a tab, or switch to its tab when it's open already (as SumatraPDF does)."""
        for path in files:
            path = os.path.abspath(path)
            for i, d in enumerate(self.docs):
                if os.path.normcase(d.path) == os.path.normcase(path):
                    self.tabs.setCurrentIndex(i)
                    if page is not None:
                        d.view.go_to(page)
                    break
            else:
                self._open(path, page, quiet)
        self.raise_()
        self.activateWindow()

    def _load(self, path: str) -> QPdfDocument | None:
        pdf = QPdfDocument(self)
        err = load_pdf(pdf, path)
        tries = 0
        while err == QPdfDocument.Error.IncorrectPassword and tries < 5:
            pw = self._ask("password", os.path.basename(path))
            if pw is None:
                return None
            pdf.setPassword(pw)
            err = load_pdf(pdf, path)
            tries += 1
        if err != QPdfDocument.Error.None_:
            return None
        return pdf

    def _open(self, path: str, page: int | None, quiet: bool) -> Doc | None:
        if not os.path.isfile(path):
            if not quiet:
                self._ask("error", f"{path}\n\nThe file doesn't exist.")
            return None
        pdf = self._load(path)
        if pdf is None:
            if not quiet:
                self._ask("error", f"{os.path.basename(path)}\n\nPR7-R couldn't open this file: it isn't a PDF, "
                                   "it's damaged, or the password was wrong.")
            return None
        view = PageView()
        doc = Doc(path, pdf, view)
        doc.read_outline()
        entry = self.hist.opened(path)
        remember = settings.get_bool("remember_state", True) and entry.opened > 1
        view.mode = (entry.layout if remember and entry.layout else settings.get("default_layout", layout.SINGLE))
        view.continuous = entry.continuous if remember and entry.layout else settings.get_bool("default_continuous", True)
        view.rotation = entry.rotation if remember else 0
        z = entry.zoom if remember and entry.zoom else settings.get("default_zoom", layout.FIT_PAGE)
        view.zoom = zoom_value(z) or layout.FIT_PAGE
        view.pageChanged.connect(lambda p, d=doc: self._page_changed(d))
        view.zoomChanged.connect(lambda _z, d=doc: d is self.doc and self._sync())
        view.selectionChanged.connect(lambda _s: self._sync())
        view.navigated.connect(self._sync)
        view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        view.customContextMenuRequested.connect(self._page_menu)
        self.docs.append(doc)
        self.stack.addWidget(view)
        i = self.tabs.addTab(widgets.file_icon("document", 16), doc.name)
        self.tabs.setTabToolTip(i, path)
        self.tabs.setCurrentIndex(i)
        self.stack.setCurrentWidget(view)
        view.set_document(pdf, page if page is not None else (entry.page if remember else 0),
                          entry.top if remember and page is None else 0.0)
        self.watcher.addPath(path)
        self._tab_changed(i)
        return doc

    def close_tab(self, i: int) -> None:
        if not (0 <= i < len(self.docs)):
            return
        d = self.docs[i]
        self._remember(d)
        self.watcher.removePath(d.path)
        self.docs.pop(i)
        self.tabs.removeTab(i)
        self.stack.removeWidget(d.view)
        d.view.set_document(None)
        d.view.deleteLater()
        d.pdf.close()
        d.pdf.deleteLater()
        if not self.docs:
            self.home.refresh()
            self.stack.setCurrentWidget(self.home)
            self._tab_changed(-1)

    def _remember(self, d: Doc) -> None:
        page, top = d.view.position()
        v = d.view
        self.hist.remember(d.path, page=page, top=round(top, 1), zoom=str(v.zoom), layout=v.mode,
                           continuous=v.continuous, rotation=v.rotation)

    def _tab_changed(self, i: int) -> None:
        d = self.doc
        if d:
            self.stack.setCurrentWidget(d.view)
            d.view.setFocus()
            self.find_box.setText(d.search_text)
        self._fill_bookmarks()
        self._sync()

    def _tab_moved(self, a: int, b: int) -> None:
        self.docs.insert(b, self.docs.pop(a))

    def _cycle(self, step: int) -> None:
        if self.docs:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % len(self.docs))

    def _tab_menu(self, pos):
        i = self.tabs.tabAt(pos)
        if i < 0:
            return
        m = QMenu(self)
        m.addAction("Close", lambda: self.close_tab(i))
        m.addAction("Close other tabs", lambda: self._close_others(i))
        m.addAction("Close tabs to the right", lambda: [self.close_tab(j) for j in range(len(self.docs) - 1, i, -1)])
        m.addSeparator()
        m.addAction("Show in folder", lambda: self.show_in_folder(self.docs[i]))
        m.exec(self.tabs.mapToGlobal(pos))

    def _close_others(self, keep: int) -> None:
        d = self.docs[keep]
        for j in range(len(self.docs) - 1, -1, -1):
            if self.docs[j] is not d:
                self.close_tab(j)

    def _file_changed(self, path: str) -> None:
        """The file changed on disk (rewritten by another program): reload it where the reader was, as Sumatra does.
        Writers often replace the file in steps, so wait a moment first."""
        t = self._reloads.get(path)
        if t is None:
            t = self._reloads[path] = QTimer(self)
            t.setSingleShot(True)
            t.setInterval(500)
            t.timeout.connect(lambda p=path: self.reload(p))
        t.start()

    def reload(self, path: str) -> None:
        for d in self.docs:
            if os.path.normcase(d.path) != os.path.normcase(path):
                continue
            if not os.path.isfile(path):
                return
            page, top = d.view.position()
            pdf = self._load(path)
            if pdf is None:
                return
            old = d.pdf
            d.pdf = pdf
            d.read_outline()
            d.view.set_document(pdf, page, top)
            old.close(); old.deleteLater()
            if path not in self.watcher.files():
                self.watcher.addPath(path)
            if d is self.doc:
                self._fill_bookmarks()
                self._sync()

    # ------------------------------------------------------------------ the toolbar and menus follow the document
    def _page_changed(self, d: Doc) -> None:
        if d is self.doc:
            self._sync_bookmark()
            self._sync()

    def _sync(self) -> None:
        d, v = self.doc, self.view
        has = d is not None
        n = v.page_count() if v else 0
        cur = v.current_page() if v else 0
        self.setWindowTitle(f"{d.name} - Paragon PR7-R" if d else "Paragon PR7-R")
        self.header.subtitle = "PDF READER"
        if not self.page_box.hasFocus():
            self.page_box.setText(d.pdf.pageLabel(cur) or str(cur + 1) if has and n else "")
        self.page_total.setText(f"/ {n}" if has else "")
        self.tabwrap.setVisible(has)
        for w in (self.k_print, self.k_prev, self.k_next, self.page_box, self.k_zoom_out, self.k_zoom_in, self.zoom_box,
                  self.k_fitpage, self.k_fitwidth, self.k_facing, self.k_rotate, self.find_box, self.k_case,
                  self.k_find_prev, self.k_find_next):
            w.setEnabled(has)
        self.k_prev.setEnabled(has and cur > 0)
        self.k_next.setEnabled(has and cur < n - 1)
        for key in ("close", "save_as", "rename", "print", "folder", "properties", "single", "facing", "book",
                    "continuous", "rotate_left", "rotate_right", "presentation", "fullscreen", "select_all", "next",
                    "prev", "first", "last", "goto", "find", "find_next", "find_prev", "zoom_in", "zoom_out",
                    "custom_zoom"):
            self.actions_by_key[key].setEnabled(has)
        for a in self.zoom_group.actions():
            a.setEnabled(has)
        self.actions_by_key["copy"].setEnabled(bool(v and v.selected_text))
        self.actions_by_key["back"].setEnabled(bool(v and v.can_go_back()))
        self.actions_by_key["forward"].setEnabled(bool(v and v.can_go_forward()))
        if v:
            self.actions_by_key[v.mode].setChecked(True)
            self.actions_by_key["continuous"].setChecked(v.continuous)
            self.k_facing.setChecked(v.mode == layout.FACING)
            self.k_fitpage.setChecked(v.zoom == layout.FIT_PAGE)
            self.k_fitwidth.setChecked(v.zoom == layout.FIT_WIDTH)
            key = f"zoom_{v.zoom if v.zoom in (layout.FIT_PAGE, layout.FIT_WIDTH) else float(v.zoom)}"
            for a in self.zoom_group.actions():
                a.setChecked(False)
            if key in self.actions_by_key:
                self.actions_by_key[key].setChecked(True)
            if not self.zoom_box.lineEdit().hasFocus():
                self.zoom_box.setEditText(zoom_text(v.zoom) if v.zoom in (layout.FIT_PAGE, layout.FIT_WIDTH)
                                          else f"{v.zoom_percent():.0f}%")
        else:
            self.k_facing.setChecked(False); self.k_fitpage.setChecked(False); self.k_fitwidth.setChecked(False)
            self.zoom_box.setEditText("")
            self.find_count.setText("")
        show_side = has and settings.get_bool("show_bookmarks", True) and bool(d and d.outline) and not self.fullscreen
        self.side.setVisible(show_side)
        self.k_bookmarks.setChecked(show_side)
        self.k_bookmarks.setEnabled(bool(d and d.outline))

    def _page_entered(self) -> None:
        d = self.doc
        if not d:
            return
        text = self.page_box.text().strip()
        page = d.pdf.pageIndexForLabel(text)
        if page < 0:
            try:
                page = int(text) - 1
            except ValueError:
                page = -1
        if 0 <= page < d.view.page_count():
            d.view.go_to(page)
            d.view.setFocus()
        self._sync()

    def go_to_page_dialog(self) -> None:
        v = self.view
        if v:
            n = self._ask("page", v.current_page() + 1, v.page_count())
            if n:
                v.go_to(int(n) - 1)

    def set_zoom(self, z) -> None:
        if self.view and z is not None:
            self.view.set_zoom(z)
            self.view.setFocus()
            self._sync()

    def custom_zoom(self) -> None:
        v = self.view
        if v:
            text = self._ask("zoom", f"{v.zoom_percent():.0f}")
            z = zoom_value(str(text)) if text else None
            if z is not None:
                self.set_zoom(z)

    def set_mode(self, mode: str) -> None:
        if self.view:
            self.view.set_mode(mode)
            self._sync()

    def set_continuous(self, on: bool) -> None:
        if self.view:
            self.view.set_continuous(on)
            self._sync()

    def rotate(self, degrees: int) -> None:
        if self.view:
            self.view.rotate(degrees)
            self._sync()

    def copy(self) -> None:
        if self.find_box.hasFocus() or self.page_box.hasFocus():
            w = QApplication.focusWidget()
            if isinstance(w, QLineEdit):
                w.copy()
            return
        if self.view:
            self.view.copy()

    # ------------------------------------------------------------------ bookmarks
    def _fill_bookmarks(self) -> None:
        self.tree.clear()
        d = self.doc
        self._bookmark_items: list[QTreeWidgetItem] = []
        if not d:
            return
        parents: list[QTreeWidgetItem] = []
        for level, title, page, loc in d.outline:
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.ItemDataRole.UserRole, (page, loc))
            item.setToolTip(0, title)
            parents = parents[:level]
            (parents[-1].addChild(item) if parents else self.tree.addTopLevelItem(item))
            parents.append(item)
            self._bookmark_items.append(item)
        for i in range(self.tree.topLevelItemCount()):   # first level open, like Sumatra's default
            self.tree.topLevelItem(i).setExpanded(self.tree.topLevelItemCount() <= 12)
        self._sync_bookmark()

    def _bookmark_clicked(self, item: QTreeWidgetItem, _col=0) -> None:
        page, loc = item.data(0, Qt.ItemDataRole.UserRole)
        if self.view:
            self._following = True
            self.view.go_to(page, max(0.0, loc.y() - 20) if loc is not None and loc.y() > 0 else 0.0)
            self._following = False

    def _sync_bookmark(self) -> None:
        """The bookmark of the section being read is the selected one."""
        if getattr(self, "_following", False) or not self.view or not getattr(self, "_bookmark_items", None):
            return
        cur = self.view.current_page()
        best = None
        for item in self._bookmark_items:
            page, _ = item.data(0, Qt.ItemDataRole.UserRole)
            if page <= cur:
                best = item
        if best is not None:
            p = best.parent()
            visible = best
            while p is not None:     # the deepest bookmark that can be seen without opening a closed one
                if not p.isExpanded():
                    visible = p
                p = p.parent()
            self.tree.blockSignals(True)
            self.tree.setCurrentItem(visible)
            self.tree.blockSignals(False)
        else:
            self.tree.clearSelection()

    def show_bookmarks(self, on: bool) -> None:
        settings.set("show_bookmarks", bool(on))
        self.actions_by_key["bookmarks"].setChecked(bool(on))
        self._sync()

    def show_toolbar(self, on: bool) -> None:
        settings.set("show_toolbar", bool(on))
        self.toolbar.setVisible(bool(on))

    # ------------------------------------------------------------------ Find
    def focus_find(self) -> None:
        if not self.toolbar.isVisible():
            self.show_toolbar(True)
            self.actions_by_key["toolbar"].setChecked(True)
        self.find_box.setFocus()
        self.find_box.selectAll()

    def _find_edited(self, *_):
        d = self.doc
        if d:
            d.search_text = ""          # searched again on Enter / F3
            d.view.set_matches([])
            self.find_count.setText("")

    def find_next(self, forward: bool = True) -> None:
        """Enter / F3: the next match after the reader's place (Shift: the one before), searching every page the
        first time. Matches are painted on the pages; the count shows which one this is."""
        d = self.doc
        text = self.find_box.text()
        if not d or not text:
            return
        case = self.k_case.isChecked()
        v = d.view
        if d.search_text != text or d.search_case != case:
            found = []
            for page in range(v.page_count()):
                found += find_in_page(d.pdf, page, text, case)
                if page % 25 == 24:
                    QApplication.processEvents()
            d.search_text, d.search_case = text, case
            v.set_matches(found)
            start_page = v.current_page()
            after = [i for i, m in enumerate(found) if m.page >= start_page]
            before = [i for i, m in enumerate(found) if m.page < start_page]
            i = (after[0] if after else 0) if forward else (before[-1] if before else len(found) - 1)
        else:
            if not v.matches:
                i = -1
            else:
                i = (v.match + (1 if forward else -1)) % len(v.matches)
        if v.matches:
            v.show_match(i)
            self.find_count.setText(f"{i + 1} of {len(v.matches)}")
        else:
            self.find_count.setText("No matches")
        self._sync()

    def eventFilter(self, obj, e):
        if obj is self.find_box and e.type() == QEvent.Type.KeyPress:
            if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.find_next(False)
                return True
            if e.key() == Qt.Key.Key_Escape:
                if self.view:
                    self.view.setFocus()
                return True
        return super().eventFilter(obj, e)

    # ------------------------------------------------------------------ presentation and fullscreen
    def set_fullscreen(self, kind: str | None) -> None:
        v = self.view
        if kind and not v:
            return
        if self.fullscreen == kind:
            kind = None
        if self.fullscreen and kind is None:          # back to the window
            state = self._before_full
            self.fullscreen = None
            self.menuBar().show(); self.header.show()
            self.toolbar.setVisible(settings.get_bool("show_toolbar", True))
            self.tabwrap.setVisible(bool(self.docs))
            if state and state["doc"] in self.docs:
                d = state["doc"]
                d.view.presenting = False
                d.view.mode, d.view.continuous, d.view.zoom = state["mode"], state["continuous"], state["zoom"]
                page = d.view.current_page()
                d.view.relayout(keep=False)
                d.view.go_to(page, record=False)
            if state and state["maximized"]:
                self.showMaximized()
            else:
                self.showNormal()
            self._sync()
            return
        if self.fullscreen:
            self.set_fullscreen(None)
        self._before_full = {"doc": self.doc, "mode": v.mode, "continuous": v.continuous, "zoom": v.zoom,
                             "maximized": self.isMaximized()}
        self.fullscreen = kind
        for w in (self.menuBar(), self.header, self.toolbar, self.tabwrap, self.side):
            w.hide()
        if kind == "presentation":     # one page at a time, the whole page, on black
            page = v.current_page()
            v.presenting = True
            v.continuous = False
            v.zoom = layout.FIT_PAGE
            v.relayout(keep=False)
            v.go_to(page, record=False)
        self.showFullScreen()
        v.setFocus()

    def _escape(self) -> None:
        if self.fullscreen:
            self.set_fullscreen(None)
        elif self.view and self.view.selected_text:
            self.view.clear_selection()

    # ------------------------------------------------------------------ file commands
    def save_as(self) -> None:
        d = self.doc
        if not d:
            return
        target = self._ask("save_as", d.path)
        if target and os.path.normcase(os.path.abspath(target)) != os.path.normcase(d.path):
            if not target.lower().endswith(".pdf") and "." not in os.path.basename(target):
                target += ".pdf"
            try:
                shutil.copy2(d.path, target)
            except OSError as e:
                self._ask("error", f"Couldn't save {target}:\n{e}")

    def rename(self) -> None:
        """Rename the document's file (it's closed and reopened at the same place)."""
        d = self.doc
        if not d:
            return
        name = self._ask("rename", d.name)
        if not name or name == d.name:
            return
        if not name.lower().endswith(".pdf") and d.name.lower().endswith(".pdf"):
            name += ".pdf"
        if any(c in name for c in '\\/:*?"<>|'):
            self._ask("error", f"{name}\n\nA file name can't contain any of these: \\ / : * ? \" < > |")
            return
        target = os.path.join(os.path.dirname(d.path), name)
        if os.path.exists(target):
            self._ask("error", f"{name} already exists in this folder.")
            return
        i = self.docs.index(d)
        page, top = d.view.position()
        self._remember(d)
        self.watcher.removePath(d.path)
        d.pdf.close()
        try:
            os.rename(d.path, target)
        except OSError as e:
            self._ask("error", f"Couldn't rename {d.name}:\n{e}")
            target = d.path
        self.hist.renamed(d.path, target)
        pdf = self._load(target)
        if pdf is None:
            return
        d.path, d.pdf = os.path.abspath(target), pdf
        d.view.set_document(pdf, page, top)
        self.tabs.setTabText(i, d.name)
        self.tabs.setTabToolTip(i, d.path)
        self.watcher.addPath(d.path)
        self._sync()

    def show_in_folder(self, d: Doc | None = None) -> None:
        """The document's folder: in PR7-E when it is the folder app (its "Use PR7-E for Folders"), else Explorer
        with the file selected."""
        d = d if isinstance(d, Doc) else self.doc
        if not d:
            return
        folder = os.path.dirname(d.path)
        if family.pr7e_for_folders() and family.launch("PR7-E", [folder]):
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", d.path])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def properties(self) -> None:
        d = self.doc
        if d:
            dlg = PropertiesDialog(d, self)
            self.properties_dialog = dlg   # tests read it
            if "properties" not in self.answers:
                dlg.exec()

    def print_document(self) -> None:
        d = self.doc
        if not d:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = self._ask("print") if "print" in self.answers else None
        if printer is None:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setDocName(d.name)
            printer.setFromTo(1, d.view.page_count())
            dlg = QPrintDialog(printer, self)
            dlg.setMinMax(1, d.view.page_count())
            dlg.setOption(QPrintDialog.PrintDialogOption.PrintCurrentPage, True)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
        print_pages(d.pdf, printer, d.view.current_page(), d.view.rotation)

    # ------------------------------------------------------------------ favorites and recent files
    def _fill_recent(self) -> None:
        for a in self.recent_actions:
            self.file_menu.removeAction(a)
        self.recent_actions = []
        for n, e in enumerate(self.hist.recent(10), 1):
            a = QAction(f"&{n % 10} {os.path.basename(e.path)}", self)
            a.setToolTip(e.path)
            a.triggered.connect(lambda _=False, p=e.path: self.open_files([p]))
            self.file_menu.insertAction(self.exit_sep, a)
            self.recent_actions.append(a)

    def _fill_favorites(self) -> None:
        m = self.fav_menu
        m.clear()
        d = self.doc
        a = m.addAction("&Add to favorites", self.add_favorite)
        a.setShortcut(QKeySequence("Ctrl+B"))
        a.setEnabled(d is not None)
        is_fav = bool(d and self.hist.get(d.path) and
                      any(f.page == d.view.current_page() for f in self.hist.get(d.path).favorites))
        r = m.addAction("&Remove from favorites", self.remove_favorite)
        r.setEnabled(is_fav)
        favs = self.hist.favorites()
        if favs:
            m.addSeparator()
        for e, f in favs:
            label = f.name or f"page {f.page + 1}"
            fa = m.addAction(f"{os.path.basename(e.path)}: {label}")
            fa.triggered.connect(lambda _=False, p=e.path, pg=f.page: self.open_files([p], page=pg))

    def add_favorite(self) -> None:
        d = self.doc
        if d:
            page = d.view.current_page()
            label = d.pdf.pageLabel(page)
            name = self._ask("favorite", page) if "favorite" in self.answers else (
                f"page {label}" if label and label != str(page + 1) else "")
            self.hist.add_favorite(d.path, page, name or "")

    def remove_favorite(self) -> None:
        d = self.doc
        if d:
            self.hist.remove_favorite(d.path, d.view.current_page())

    # ------------------------------------------------------------------ the page's right-click menu
    def _page_menu(self, pos):
        v = self.view
        if not v:
            return
        m = QMenu(self)
        c = m.addAction("&Copy selection", v.copy)
        c.setEnabled(bool(v.selected_text))
        link = v.link_at(QPointF(pos))
        if link and link[0] is not None and not link[0].isEmpty():
            m.addAction("Copy &link address", lambda: QApplication.clipboard().setText(link[0].toString()))
        m.addAction("Select &all", v.select_all)
        m.addSeparator()
        m.addAction("Add page to &favorites", self.add_favorite)
        m.addSeparator()
        m.addAction("Rotate &left", lambda: self.rotate(-90))
        m.addAction("Rotate &right", lambda: self.rotate(90))
        m.addSeparator()
        if self.fullscreen:
            m.addAction("&Exit fullscreen", lambda: self.set_fullscreen(None))
        m.addAction("P&roperties", self.properties)
        m.exec(v.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ settings and help
    def set_finish(self, name: str) -> None:
        theme.set_finish(name)
        settings.set("finish", name)
        app = QApplication.instance()
        apply_look(app)
        for gap in self.toolbar.findChildren(QFrame, "gap"):
            gap.setStyleSheet(f"background: {theme.PANEL_EDGE};")
        self.actions_by_key[f"finish_{name}"].setChecked(True)
        for w in [self.header, self.home, *(d.view.viewport() for d in self.docs)]:
            w.update()

    def options(self) -> None:
        dlg = OptionsDialog(self)
        self.options_dialog = dlg
        if "options" not in self.answers and dlg.exec() == QDialog.DialogCode.Accepted:
            dlg.apply()
            self.home.refresh()

    def check_updates(self) -> None:
        from . import update_ui
        update_ui.check(self, manual=True)

    def shortcuts(self) -> None:
        rows = [("Open / Close", "Ctrl+O / Ctrl+W"), ("Next / previous page", "N, P, Right, Left, Space"),
                ("First / last page", "Home, End"), ("Go to page", "Ctrl+G"), ("Back / Forward", "Alt+Left / Alt+Right"),
                ("Find / next / previous", "Ctrl+F / F3 / Shift+F3"), ("Zoom in / out", "Ctrl++ / Ctrl+-, Ctrl+wheel"),
                ("Fit page / actual size / fit width", "Ctrl+0 / Ctrl+1 / Ctrl+2"),
                ("Single / facing / book view", "Ctrl+6 / Ctrl+7 / Ctrl+8"),
                ("Rotate left / right", "Ctrl+Shift+- / Ctrl+Shift++"), ("Presentation / fullscreen", "F5 / F11"),
                ("Bookmarks / toolbar", "F12 / F8"), ("Copy selection / select all", "Ctrl+C / Ctrl+A"),
                ("Next / previous tab", "Ctrl+Tab / Ctrl+Shift+Tab"), ("Properties / print", "Ctrl+D / Ctrl+P"),
                ("Add to favorites", "Ctrl+B")]
        dlg = QDialog(self)
        dlg.setWindowTitle("Keyboard Shortcuts")
        form = QFormLayout(dlg)
        for what, keys in rows:
            k = QLabel(keys); k.setStyleSheet(f"color: {theme.TEXT_DIM};")
            form.addRow(what, k)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)
        self.shortcuts_dialog = dlg
        if "shortcuts" not in self.answers:
            dlg.exec()

    def about(self) -> None:
        if "about" in self.answers:
            return
        QMessageBox.about(self, "About Paragon PR7-R",
                          f"<b>Paragon PR7-R</b> {__version__}<br>A PDF reader that works the way SumatraPDF works."
                          "<br><br>Pages are drawn by PDFium, through Qt's QtPdf.")

    # ------------------------------------------------------------------ drag and drop, closing
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile() and os.path.isfile(u.toLocalFile())]
        if files:
            self.open_files(files)
            e.acceptProposedAction()

    def save_session(self) -> None:
        for d in self.docs:
            self._remember(d)
        settings.set("session", [d.path for d in self.docs])
        settings.set("session_current", self.doc.path if self.doc else "")

    def closeEvent(self, e):
        if self.fullscreen:
            self.set_fullscreen(None)
        self.save_session()
        super().closeEvent(e)


def print_pages(pdf: QPdfDocument, printer, current: int = 0, rotation: int = 0) -> int:
    """Print the pages the print dialog chose, each scaled to fit the paper and centred. Returns pages printed."""
    from PySide6.QtPrintSupport import QPrinter
    n = pdf.pageCount()
    if printer.printRange() == QPrinter.PrintRange.CurrentPage:
        pages = [current]
    elif printer.printRange() == QPrinter.PrintRange.PageRange and printer.fromPage() > 0:
        pages = list(range(printer.fromPage() - 1, min(printer.toPage(), n)))
    else:
        pages = list(range(n))
    from .pageview import ROTATIONS
    from PySide6.QtPdf import QPdfDocumentRenderOptions
    painter = QPainter()
    if not painter.begin(printer):
        return 0
    done = 0
    for k, page in enumerate(pages):
        if k:
            printer.newPage()
        area = printer.pageRect(QPrinter.Unit.DevicePixel)
        w, h = layout.rotated((pdf.pagePointSize(page).width(), pdf.pagePointSize(page).height()), rotation)
        s = min(area.width() / w, area.height() / h)
        size = QSize(int(w * s), int(h * s))
        opts = QPdfDocumentRenderOptions()
        opts.setRotation(ROTATIONS[rotation % 360])
        img = pdf.render(page, size, opts)
        x = (area.width() - size.width()) / 2
        y = (area.height() - size.height()) / 2
        painter.drawImage(QRectF(x, y, size.width(), size.height()), img)
        done += 1
    painter.end()
    return done


# ============================================================================ dialogs
class PropertiesDialog(QDialog):
    """File > Properties: what the PDF says about itself, and the file's size and pages (Sumatra's list)."""

    def __init__(self, d: Doc, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Document Properties")
        self.setMinimumWidth(460)
        pdf = d.pdf
        F = QPdfDocument.MetaDataField

        def meta(f):
            v = pdf.metaData(f)
            if hasattr(v, "toString") and hasattr(v, "isValid"):
                return v.toString("d MMMM yyyy, HH:mm") if v.isValid() else ""
            return str(v or "")

        size = os.path.getsize(d.path) if os.path.exists(d.path) else 0
        ps = pdf.pagePointSize(0) if pdf.pageCount() else None
        self.rows = [("File", d.path), ("Title", meta(F.Title)), ("Subject", meta(F.Subject)),
                     ("Author", meta(F.Author)), ("Keywords", meta(F.Keywords)), ("Created", meta(F.CreationDate)),
                     ("Modified", meta(F.ModificationDate)), ("Application", meta(F.Creator)),
                     ("PDF producer", meta(F.Producer)),
                     ("File size", f"{size / 1024 / 1024:.2f} MB ({size:,} bytes)" if size >= 1024 * 1024
                      else f"{size / 1024:.1f} KB ({size:,} bytes)"),
                     ("Number of pages", str(pdf.pageCount())),
                     ("Page size", f"{ps.width() / 72 * 25.4:.0f} x {ps.height() / 72 * 25.4:.0f} mm "
                                   f"({ps.width():.0f} x {ps.height():.0f} pt)" if ps else "")]
        form = QFormLayout(self)
        for k, v in self.rows:
            if v:
                lab = QLabel(v)
                lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                lab.setWordWrap(True)
                key = QLabel(k.upper()); key.setStyleSheet(f"color: {theme.TEXT_DIM}; font-weight: 600; font-size: 11px;")
                form.addRow(key, lab)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self) -> dict:
        return dict(self.rows)


class OptionsDialog(QDialog):
    """Settings > Options: SumatraPDF's Options that apply here."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Options")
        self.setMinimumWidth(480)
        form = QFormLayout(self)
        self.zoom = QComboBox()
        for text, val in ZOOM_CHOICES[:3] + [("75%", 75), ("50%", 50)]:
            self.zoom.addItem(text, str(val))
        cur = settings.get("default_zoom", layout.FIT_PAGE)
        self.zoom.setCurrentIndex(max(0, self.zoom.findData(cur)))
        self.layout_box = QComboBox()
        for text, val in (("Single page", layout.SINGLE), ("Facing", layout.FACING), ("Book view", layout.BOOK)):
            self.layout_box.addItem(text, val)
        self.layout_box.setCurrentIndex(max(0, self.layout_box.findData(settings.get("default_layout", layout.SINGLE))))
        self.continuous = QCheckBox("Show pages continuously")
        self.continuous.setChecked(settings.get_bool("default_continuous", True))
        self.remember = QCheckBox("Remember these settings for each document")
        self.remember.setChecked(settings.get_bool("remember_state", True))
        self.session = QCheckBox("Reopen the documents that were open when PR7-R was closed")
        self.session.setChecked(settings.get_bool("restore_session", True))
        self.frequent = QCheckBox("Show frequently read documents on the start page")
        self.frequent.setChecked(settings.get_bool("show_frequent", True))
        from . import update_ui
        self.updates = QCheckBox("Check for updates automatically")
        self.updates.setChecked(update_ui.auto_enabled())
        for label, w in (("DEFAULT ZOOM", self.zoom), ("DEFAULT LAYOUT", self.layout_box)):
            form.addRow(label, w)
        for w in (self.continuous, self.remember, self.session, self.frequent, self.updates):
            form.addRow(w)
        from . import shell
        if shell.available():
            b = QPushButton("Make PR7-R the default PDF reader...")
            b.clicked.connect(shell.open_default_apps)
            form.addRow(b)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def apply(self) -> None:
        from . import update_ui
        settings.set("default_zoom", self.zoom.currentData())
        settings.set("default_layout", self.layout_box.currentData())
        settings.set("default_continuous", self.continuous.isChecked())
        settings.set("remember_state", self.remember.isChecked())
        settings.set("restore_session", self.session.isChecked())
        settings.set("show_frequent", self.frequent.isChecked())
        update_ui.set_auto(self.updates.isChecked())
