"""PR7-R's page view: the document's pages, drawn by QtPdf (PDFium), laid out by `layout`, in family colours.

It is our own widget rather than QtPdf's QPdfView because QPdfView paints search matches in fixed blue / cyan (the
family has no blue) and has no facing or book view, rotation or presentation mode. What it does, as SumatraPDF does:
scrolling (wheel, keys, dragging the page), Ctrl+wheel zoom at the mouse, links (pointer, tooltip, click), selecting
text by dragging over it and copying it, matches of Find, and Back / Forward through the places the reader jumped
from."""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field

from PySide6.QtCore import QModelIndex, QPointF, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions, QPdfLinkModel
from PySide6.QtWidgets import QAbstractScrollArea, QToolTip

from . import layout, theme

ROTATIONS = {0: QPdfDocumentRenderOptions.Rotation.None_, 90: QPdfDocumentRenderOptions.Rotation.Clockwise90,
             180: QPdfDocumentRenderOptions.Rotation.Clockwise180, 270: QPdfDocumentRenderOptions.Rotation.Clockwise270}
CACHE = 24                 # rendered pages kept
WHOLE_PAGE_LIMIT = 4096    # above this many pixels a side, only the visible part of a page is rendered


@dataclass
class Match:
    """One Find match: its page, where it is in the page's text, and one box per line (points)."""
    page: int
    start: int
    length: int
    rects: list[QRectF] = field(default_factory=list)


def line_boxes(rects: list[QRectF]) -> list[QRectF]:
    """PDFium gives a box per letter; joined into one box per line of text."""
    lines: list[QRectF] = []
    for r in sorted(rects, key=lambda r: (round(r.center().y()), r.x())):
        for i, ln in enumerate(lines):
            if r.top() < ln.bottom() - 1 and r.bottom() > ln.top() + 1:
                lines[i] = ln.united(r)
                break
        else:
            lines.append(QRectF(r))
    return lines


def find_in_page(doc: QPdfDocument, page: int, text: str, match_case: bool = False) -> list[Match]:
    """Every match of `text` on one page (plain text, not a pattern), in reading order."""
    if not text:
        return []
    body = doc.getAllText(page).text()
    found = []
    for m in re.finditer(re.escape(text), body, 0 if match_case else re.IGNORECASE):
        sel = doc.getSelectionAtIndex(page, m.start(), len(text))
        rects = line_boxes([p.boundingRect() for p in sel.bounds()]) if sel.isValid() else []
        if rects:
            found.append(Match(page, m.start(), len(text), rects))
    return found


class PageView(QAbstractScrollArea):
    pageChanged = Signal(int)          # the page number shown in the page box (0-based)
    zoomChanged = Signal(float)        # the zoom in percent (what fit page / fit width came to)
    selectionChanged = Signal(bool)    # whether text is selected
    navigated = Signal()               # Back / Forward became possible or not

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: QPdfDocument | None = None
        self.sizes: list[tuple[float, float]] = []
        self.mode = layout.SINGLE
        self.continuous = True
        self.rotation = 0
        self.zoom: str | float = layout.FIT_PAGE
        self.presenting = False
        self.lay = layout.Layout([], 0, 0, 1.0)
        self.page = 0
        self.cache: OrderedDict = OrderedDict()
        self.links: dict[int, list[tuple[QRectF, QUrl, int, QPointF]]] = {}
        self.char_cache: dict[int, list[tuple[int, QRectF]]] = {}
        self.matches: list[Match] = []
        self.match = -1
        self.selection: dict[int, list[QRectF]] = {}
        self.selected_text = ""
        self.back_stack: list[tuple[int, float]] = []
        self.forward_stack: list[tuple[int, float]] = []
        self._drag = None          # ("pan", start pos, scroll x, y) or ("select", page, start point in points)
        self._press = None
        self.setFrameShape(QAbstractScrollArea.Shape.NoFrame)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.horizontalScrollBar().valueChanged.connect(lambda _: self.viewport().update())

    # ------------------------------------------------------------------ the document
    def set_document(self, doc: QPdfDocument | None, page: int = 0, top: float = 0.0) -> None:
        self.doc = doc
        self.sizes = []
        if doc is not None:
            for i in range(doc.pageCount()):
                s = doc.pagePointSize(i)
                self.sizes.append((s.width(), s.height()))
        self.cache.clear()
        self.links.clear()
        self.char_cache.clear()
        self.matches, self.match = [], -1
        self.clear_selection()
        self.back_stack.clear()
        self.forward_stack.clear()
        self.page = -1
        self.relayout(keep=False)
        self.go_to(page, top, record=False)

    def page_count(self) -> int:
        return len(self.sizes)

    # ------------------------------------------------------------------ layout and zoom
    def _dpi(self) -> float:
        return self.logicalDpiY() or 96

    def scale(self) -> float:
        vp = self.viewport()
        return layout.scale_for(self.zoom, self.sizes, self.mode, self.rotation, vp.width(), vp.height(), self._dpi())

    def zoom_percent(self) -> float:
        return layout.percent(self.lay.scale, self._dpi())

    def relayout(self, keep: bool = True, anchor: QPointF | None = None) -> None:
        """Place the pages again (after a zoom, layout, rotation or size change), keeping the reader's place."""
        where = self.position() if keep and self.lay.placed else None
        fixed = None
        if anchor is not None and self.lay.placed:
            docpt = QPointF(anchor.x() + self.horizontalScrollBar().value(), anchor.y() + self.verticalScrollBar().value())
            pl = self.lay.page_at(docpt.x(), docpt.y())
            if pl:
                fixed = (pl.page, self.lay.to_page(pl, docpt.x(), docpt.y(), self.rotation, self.sizes[pl.page]))
        vp = self.viewport()
        self.lay = layout.Layout.place(self.sizes, self.mode, self.continuous, self.rotation, self.scale(),
                                       vp.width(), vp.height(), max(self.page, 0))
        self.cache.clear()
        hs, vs = self.horizontalScrollBar(), self.verticalScrollBar()
        hs.setRange(0, max(0, int(self.lay.width - vp.width())))
        vs.setRange(0, max(0, int(self.lay.height - vp.height())))
        hs.setPageStep(vp.width()); vs.setPageStep(vp.height())
        vs.setSingleStep(40); hs.setSingleStep(40)
        if fixed is not None:
            pl = self.lay.find(fixed[0])
            if pl:
                x, y = self.lay.from_page(pl, fixed[1][0], fixed[1][1], self.rotation, self.sizes[pl.page])
                hs.setValue(int(x - anchor.x())); vs.setValue(int(y - anchor.y()))
        elif where is not None:
            self._show(*where)
        self.zoomChanged.emit(self.zoom_percent())
        self.viewport().update()

    def set_zoom(self, zoom, anchor: QPointF | None = None) -> None:
        if zoom not in (layout.FIT_PAGE, layout.FIT_WIDTH):
            zoom = min(max(float(zoom), layout.MIN_ZOOM), layout.MAX_ZOOM)
        self.zoom = zoom
        self.relayout(anchor=anchor)

    def zoom_step(self, up: bool, anchor: QPointF | None = None) -> None:
        self.set_zoom(layout.step_zoom(self.zoom_percent(), up), anchor)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.relayout()

    def set_continuous(self, on: bool) -> None:
        self.continuous = on
        self.relayout()

    def rotate(self, degrees: int) -> None:
        self.rotation = (self.rotation + degrees) % 360
        self.relayout()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.relayout()

    # ------------------------------------------------------------------ where the reader is
    def position(self) -> tuple[int, float]:
        """(page, top): the page at the window's top edge and how far down it the edge is, in points."""
        top = self.verticalScrollBar().value()
        for pl in self.lay.placed:
            if pl.y + pl.h > top + layout.MARGIN + 1:     # not a sliver of the page above in the top margin
                return pl.page, max(0.0, (top - pl.y) / self.lay.scale)
        return max(self.page, 0), 0.0

    def _show(self, page: int, top: float = 0.0) -> None:
        if not self.continuous:
            if layout.row_of(page, self.mode) != layout.row_of(max(self.page, 0), self.mode) or not self.lay.find(page):
                self.page = page
                self.relayout(keep=False)
        pl = self.lay.find(page)
        if pl is None:
            return
        self.verticalScrollBar().setValue(int(pl.y + top * self.lay.scale - (layout.MARGIN if top == 0 else 0)))
        self._scrolled()

    def go_to(self, page: int, top: float = 0.0, record: bool = True) -> None:
        """Go to a page (Go To > Page, the page box, bookmarks, links). `record` lets Back come here again."""
        if not self.sizes:
            return
        page = min(max(page, 0), len(self.sizes) - 1)
        if record and self.lay.placed:
            self.back_stack.append(self.position())
            self.forward_stack.clear()
            self.navigated.emit()
        self._show(page, top)
        self.page = page
        self.pageChanged.emit(page)
        self.viewport().update()

    def next_page(self) -> None:
        rows = layout.rows(len(self.sizes), self.mode)
        r = layout.row_of(self.current_page(), self.mode)
        if r + 1 < len(rows):
            self.go_to(next(p for p in rows[r + 1] if p is not None), record=False)

    def prev_page(self) -> None:
        rows = layout.rows(len(self.sizes), self.mode)
        r = layout.row_of(self.current_page(), self.mode)
        if r > 0:
            self.go_to(next(p for p in rows[r - 1] if p is not None), record=False)

    def current_page(self) -> int:
        return max(self.page, 0)

    def can_go_back(self) -> bool:
        return bool(self.back_stack)

    def can_go_forward(self) -> bool:
        return bool(self.forward_stack)

    def back(self) -> None:
        if self.back_stack:
            self.forward_stack.append(self.position())
            page, top = self.back_stack.pop()
            self.go_to(page, top, record=False)
            self.navigated.emit()

    def forward(self) -> None:
        if self.forward_stack:
            self.back_stack.append(self.position())
            page, top = self.forward_stack.pop()
            self.go_to(page, top, record=False)
            self.navigated.emit()

    def _scrolled(self, *_):
        vp = self.viewport()
        if self.lay.placed:
            cur = self.lay.current(self.verticalScrollBar().value(), vp.height())
            if self.continuous and cur != self.page:
                self.page = cur
                self.pageChanged.emit(cur)
        vp.update()

    # ------------------------------------------------------------------ painting
    def _image(self, page: int, w: int, h: int, clip: QRect | None) -> QImage:
        key = (page, w, h, self.rotation, None if clip is None else (clip.x(), clip.y(), clip.width(), clip.height()))
        img = self.cache.get(key)
        if img is None:
            opts = QPdfDocumentRenderOptions()
            opts.setRotation(ROTATIONS[self.rotation])
            if clip is not None:
                opts.setScaledSize(QSize(w, h))
                opts.setScaledClipRect(clip)
                img = self.doc.render(page, clip.size(), opts)
            else:
                img = self.doc.render(page, QSize(w, h), opts)
            self.cache[key] = img
            while len(self.cache) > CACHE:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(key)
        return img

    def background(self) -> QColor:
        if self.presenting:
            return QColor("#000000")
        return QColor(theme.PANEL if theme.FINISH == "obsidian" else "#D9D4D6")

    def paintEvent(self, _):
        p = QPainter(self.viewport())
        p.fillRect(self.viewport().rect(), self.background())
        if self.doc is None:
            return
        dx, dy = self.horizontalScrollBar().value(), self.verticalScrollBar().value()
        vp = QRectF(dx, dy, self.viewport().width(), self.viewport().height())
        dpr = self.devicePixelRatioF()
        p.translate(-dx, -dy)
        for pl in self.lay.placed:
            r = QRectF(pl.x, pl.y, pl.w, pl.h)
            if not r.intersects(vp):
                continue
            if not self.presenting:
                p.fillRect(r.translated(0, 3), QColor(0, 0, 0, 120 if theme.FINISH == "obsidian" else 35))
            p.fillRect(r, QColor("#FFFFFF"))   # PDFium leaves the paper transparent
            w, h = int(pl.w * dpr), int(pl.h * dpr)
            if max(w, h) <= WHOLE_PAGE_LIMIT:
                p.drawImage(r, self._image(pl.page, w, h, None))
            else:   # very high zoom: render just the part in the window
                seen = r.intersected(vp)
                clip = QRect(int((seen.x() - r.x()) * dpr), int((seen.y() - r.y()) * dpr),
                             int(seen.width() * dpr) + 1, int(seen.height() * dpr) + 1)
                p.drawImage(QRectF(seen.x(), seen.y(), clip.width() / dpr, clip.height() / dpr),
                            self._image(pl.page, w, h, clip))
            self._paint_marks(p, pl)

    def _box(self, pl: layout.Placed, rect: QRectF) -> QRectF:
        """A rectangle on the page (points) in the view."""
        size = self.sizes[pl.page]
        x1, y1 = self.lay.from_page(pl, rect.left(), rect.top(), self.rotation, size)
        x2, y2 = self.lay.from_page(pl, rect.right(), rect.bottom(), self.rotation, size)
        return QRectF(QPointF(min(x1, x2), min(y1, y2)), QPointF(max(x1, x2), max(y1, y2)))

    def _paint_marks(self, p: QPainter, pl: layout.Placed) -> None:
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for rect in self.selection.get(pl.page, []):   # selected text: the family's light wash
            c = QColor(theme.ACCENT); c.setAlphaF(.28)
            p.fillRect(self._box(pl, rect).adjusted(-1, -1, 1, 1), c)
        for i, m in enumerate(self.matches):
            if m.page != pl.page:
                continue
            for rect in m.rects:
                b = self._box(pl, rect).adjusted(-2, -1, 2, 1)
                if i == self.match:
                    c = QColor(theme.LED_ORANGE); c.setAlphaF(.42)
                    p.setBrush(c); p.setPen(QPen(QColor(theme.ACCENT), 1.5))
                else:
                    c = QColor(theme.ACCENT); c.setAlphaF(.18)
                    p.setBrush(c); p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(b, 2, 2)
        p.restore()

    # ------------------------------------------------------------------ Find
    def set_matches(self, matches: list[Match], current: int = -1) -> None:
        self.matches = matches
        self.show_match(current)

    def show_match(self, i: int) -> None:
        """Make match i the current one and scroll so it's in view (a third of the way down, as Sumatra does)."""
        self.match = i
        if 0 <= i < len(self.matches):
            m = self.matches[i]
            if not self.continuous:
                self._show(m.page)
            pl = self.lay.find(m.page)
            if pl:
                b = self._box(pl, m.rects[0])
                vs, hs = self.verticalScrollBar(), self.horizontalScrollBar()
                vp = self.viewport()
                if not (vs.value() + 40 < b.top() and b.bottom() < vs.value() + vp.height() - 40):
                    vs.setValue(int(b.top() - vp.height() / 3))
                if not (hs.value() < b.left() and b.right() < hs.value() + vp.width()):
                    hs.setValue(int(b.left() - vp.width() / 3))
                self._scrolled()
        self.viewport().update()

    # ------------------------------------------------------------------ text selection
    def clear_selection(self) -> None:
        had = bool(self.selected_text)
        self.selection, self.selected_text = {}, ""
        if had:
            self.selectionChanged.emit(False)
        self.viewport().update()

    def select_all(self) -> None:
        if self.doc is None:
            return
        self.selection, parts = {}, []
        for page in range(len(self.sizes)):
            text = self.doc.getAllText(page)
            if text.isValid() and text.text():
                sel = self.doc.getSelectionAtIndex(page, 0, len(text.text()))
                self.selection[page] = line_boxes([b.boundingRect() for b in sel.bounds()])
                parts.append(text.text())
        self.selected_text = "\r\n".join(parts)
        self.selectionChanged.emit(bool(self.selected_text))
        self.viewport().update()

    def copy(self) -> bool:
        if not self.selected_text:
            return False
        QGuiApplication.clipboard().setText(self.selected_text)
        return True

    def _chars(self, page: int) -> list[tuple[int, QRectF]]:
        """(text position, box in points) of every letter on a page, in reading order. PDFium gives boxes only for
        letters, not spaces or line ends, so they are matched to the letters of the page's text."""
        if page not in self.char_cache:
            text = self.doc.getAllText(page).text()
            boxes = self.doc.getSelectionAtIndex(page, 0, len(text)).bounds() if text else []
            out, k = [], 0
            for i, ch in enumerate(text):
                if ch.isspace():
                    continue
                if k >= len(boxes):
                    break
                out.append((i, boxes[k].boundingRect()))
                k += 1
            self.char_cache[page] = out
        return self.char_cache[page]

    def _index_at(self, page: int, pt: QPointF, forward: bool) -> int | None:
        """The text position at a point. Off the text (a margin, between lines), the nearest letter: for the start
        of a selection (`forward`) the next one in reading order, for its end the one before."""
        chars = self._chars(page)
        if not chars:
            return None
        x, y = pt.x(), pt.y()
        for i, r in chars:
            if r.adjusted(-1, -1, 1, 1).contains(pt):
                return i
        line = [(i, r) for i, r in chars if r.top() - 2 <= y <= r.bottom() + 2]
        if line:
            if forward:
                after = [i for i, r in line if r.right() >= x]
                if after:
                    return after[0]
                later = [i for i, _ in chars if i > line[-1][0]]
                return later[0] if later else line[-1][0]
            before = [i for i, r in line if r.left() <= x]
            if before:
                return before[-1]
            earlier = [i for i, _ in chars if i < line[0][0]]
            return earlier[-1] if earlier else line[0][0]
        if forward:
            below = [i for i, r in chars if r.top() > y]
            return below[0] if below else None
        above = [i for i, r in chars if r.bottom() < y]
        return above[-1] if above else None

    def _select(self, start_page: int, start: QPointF, end_page: int, end: QPointF) -> None:
        """Select the text from one point to another (each on a page, in points), across pages when needed."""
        if (end_page, end.y(), end.x()) < (start_page, start.y(), start.x()):
            start_page, start, end_page, end = end_page, end, start_page, start
        self.selection, parts = {}, []
        for page in range(start_page, end_page + 1):
            count = len(self.doc.getAllText(page).text())
            if not count:
                continue
            a = self._index_at(page, start, True) if page == start_page else 0
            b = self._index_at(page, end, False) if page == end_page else count - 1
            if a is None or b is None or b < a:
                continue
            sel = self.doc.getSelectionAtIndex(page, a, b - a + 1)
            if sel.isValid() and sel.text():
                self.selection[page] = line_boxes([q.boundingRect() for q in sel.bounds()])
                parts.append(sel.text())
        self.selected_text = "\r\n".join(parts)
        self.selectionChanged.emit(bool(self.selected_text))
        self.viewport().update()

    def _on_text(self, page: int, pt: QPointF) -> bool:
        return any(r.adjusted(-1, -1, 1, 1).contains(pt) for _, r in self._chars(page))

    # ------------------------------------------------------------------ links
    def _links(self, page: int):
        if page not in self.links:
            model = QPdfLinkModel()
            model.setDocument(self.doc)
            model.setPage(page)
            found = []
            for row in range(model.rowCount(QModelIndex())):
                idx = model.index(row, 0)
                found.append((model.data(idx, QPdfLinkModel.Role.Rectangle.value),
                              model.data(idx, QPdfLinkModel.Role.Url.value),
                              model.data(idx, QPdfLinkModel.Role.Page.value),
                              model.data(idx, QPdfLinkModel.Role.Location.value)))
            self.links[page] = found
        return self.links[page]

    def link_at(self, pos: QPointF):
        """The link under a point of the window: (url, page, location) or None."""
        hit = self._hit(pos)
        if hit is None:
            return None
        page, pt = hit
        for rect, url, target, loc in self._links(page):
            if rect is not None and rect.contains(pt):
                return url, target, loc
        return None

    def _hit(self, pos: QPointF):
        """The page under a point of the window and the point on it in points."""
        x, y = pos.x() + self.horizontalScrollBar().value(), pos.y() + self.verticalScrollBar().value()
        pl = self.lay.page_at(x, y)
        if pl is None:
            return None
        return pl.page, QPointF(*self.lay.to_page(pl, x, y, self.rotation, self.sizes[pl.page]))

    def follow(self, link) -> None:
        url, page, loc = link
        if url is not None and not url.isEmpty():
            QDesktopServices.openUrl(url)
        elif page is not None and page >= 0:
            self.go_to(page, max(0.0, loc.y() - 20) if loc is not None else 0.0)

    # ------------------------------------------------------------------ mouse and keys
    def mousePressEvent(self, e):
        if self.doc is None:
            return
        self.setFocus()
        self._press = e.position()
        hit = self._hit(e.position())
        if e.button() == Qt.MouseButton.LeftButton and hit and self.link_at(e.position()) is None \
                and self._on_text(*hit):
            self._drag = ("select", hit[0], hit[1])
            self.clear_selection()
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        elif e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._drag = ("pan", e.position(), self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self.doc is None:
            return
        if self._drag and self._drag[0] == "pan":
            d = e.position() - self._drag[1]
            self.horizontalScrollBar().setValue(int(self._drag[2] - d.x()))
            self.verticalScrollBar().setValue(int(self._drag[3] - d.y()))
            return
        if self._drag and self._drag[0] == "select":
            hit = self._hit(e.position())
            if hit:
                self._select(self._drag[1], self._drag[2], hit[0], hit[1])
            return
        link = self.link_at(e.position())
        if link:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            url = link[0]
            QToolTip.showText(e.globalPosition().toPoint(),
                              url.toString() if url is not None and not url.isEmpty() else f"Page {link[1] + 1}", self)
        else:
            hit = self._hit(e.position())
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor if hit and self._on_text(*hit)
                                      else Qt.CursorShape.ArrowCursor)
            QToolTip.hideText()

    def mouseReleaseEvent(self, e):
        moved = self._press is not None and (e.position() - self._press).manhattanLength() > 4
        if self._drag and self._drag[0] == "pan" and not moved and e.button() == Qt.MouseButton.LeftButton:
            link = self.link_at(e.position())
            if link:
                self.follow(link)
            else:
                self.clear_selection()
        self._drag, self._press = None, None
        self.viewport().unsetCursor()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = e.angleDelta().y() / 120
            if steps:
                self.zoom_step(steps > 0, e.position())
            return
        vs = self.verticalScrollBar()
        if not self.continuous:   # one spread at a time: rolling past its end turns the page
            down = e.angleDelta().y() < 0
            if down and vs.value() >= vs.maximum():
                self.next_page(); vs.setValue(0); return
            if not down and vs.value() <= 0 and self.current_page() > 0:
                self.prev_page(); vs.setValue(vs.maximum()); return
        super().wheelEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        vs, hs = self.verticalScrollBar(), self.horizontalScrollBar()
        fits = vs.maximum() == 0 or not self.continuous
        if k in (Qt.Key.Key_Down, Qt.Key.Key_J):
            vs.setValue(vs.value() + vs.singleStep())
        elif k in (Qt.Key.Key_Up, Qt.Key.Key_K):
            vs.setValue(vs.value() - vs.singleStep())
        elif k == Qt.Key.Key_Right:
            self.next_page() if (fits or hs.maximum() == 0) else hs.setValue(hs.value() + hs.singleStep())
        elif k == Qt.Key.Key_Left:
            self.prev_page() if (fits or hs.maximum() == 0) else hs.setValue(hs.value() - hs.singleStep())
        elif k in (Qt.Key.Key_PageDown, Qt.Key.Key_Space) and not e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if not self.continuous and vs.value() >= vs.maximum():
                self.next_page()
            else:
                vs.setValue(vs.value() + vs.pageStep() - 40)
        elif k in (Qt.Key.Key_PageUp, Qt.Key.Key_Space, Qt.Key.Key_Backspace):
            if not self.continuous and vs.value() <= 0:
                self.prev_page()
            else:
                vs.setValue(vs.value() - vs.pageStep() + 40)
        elif k == Qt.Key.Key_N:
            self.next_page()
        elif k == Qt.Key.Key_P:
            self.prev_page()
        elif k == Qt.Key.Key_Home:
            self.go_to(0)
        elif k == Qt.Key.Key_End:
            self.go_to(len(self.sizes) - 1)
        elif k in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_step(True)
        elif k == Qt.Key.Key_Minus:
            self.zoom_step(False)
        else:
            super().keyPressEvent(e)
