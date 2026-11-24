import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor
from PySide6.QtPdf import QPdfDocument

import sample_pdf
from pr7r import layout, theme
from pr7r.pageview import PageView, find_in_page, line_boxes


@pytest.fixture
def view(qapp, pdfs):
    doc = QPdfDocument()
    assert doc.load(str(pdfs["book"])) == QPdfDocument.Error.None_
    v = PageView()
    v.resize(900, 700)
    v.show()
    v.set_document(doc)
    qapp.processEvents()
    yield v
    v.close()


def dark_pixels(v, rect=None):
    img = v.viewport().grab().toImage()
    r = rect or img.rect()
    return sum(1 for x in range(r.left(), r.right(), 3) for y in range(r.top(), r.bottom(), 3)
               if img.pixelColor(x, y).lightness() < 90 and img.pixelColor(x, y) != QColor(theme.PANEL))


def test_pages_are_drawn(view, qapp):
    assert view.page_count() == 19
    view.set_zoom(layout.FIT_WIDTH)
    view.go_to(1, record=False)
    qapp.processEvents()
    pl = view.lay.find(1)
    # The page is white paper with dark text on it (PDFium leaves paper transparent: we paint it).
    img = view.viewport().grab().toImage()
    top = int(pl.y - view.verticalScrollBar().value())
    assert img.pixelColor(int(pl.x - view.horizontalScrollBar().value()) + 5, max(top, 0) + 5) == QColor("#FFFFFF")
    assert dark_pixels(view) > 200


def test_zoom_and_place(view):
    view.set_zoom(layout.FIT_WIDTH)
    pl = view.lay.find(0)
    assert pl.w == pytest.approx(view.viewport().width() - 2 * layout.MARGIN, abs=1)
    view.set_zoom(100)
    assert view.zoom_percent() == pytest.approx(100)
    view.zoom_step(True)
    assert view.zoom_percent() == pytest.approx(125)
    view.set_zoom(layout.FIT_PAGE)
    pl = view.lay.find(0)
    assert pl.h <= view.viewport().height() - 2 * layout.MARGIN + 1


def test_go_to_and_position(view):
    view.set_zoom(layout.FIT_WIDTH)
    view.go_to(5, top=200)
    page, top = view.position()
    assert page == 5 and top == pytest.approx(200, abs=2)
    assert view.current_page() == 5
    view.set_zoom(150)                # zooming keeps the reader's place
    assert view.position()[0] == 5 and view.position()[1] == pytest.approx(200, abs=3)
    view.back()
    assert view.position()[0] == 0
    view.forward()
    assert view.current_page() == 5


def test_facing_book_and_one_page_at_a_time(view):
    view.set_mode(layout.FACING)
    a, b = view.lay.placed[:2]
    assert a.y == b.y and b.x > a.x
    view.set_mode(layout.BOOK)
    assert view.lay.placed[1].y > view.lay.placed[0].y
    view.set_mode(layout.SINGLE)
    view.set_continuous(False)
    assert [p.page for p in view.lay.placed] == [0]
    view.next_page()
    assert [p.page for p in view.lay.placed] == [1] and view.current_page() == 1
    view.prev_page()
    assert view.current_page() == 0


def test_rotation_turns_the_pages(view, qapp):
    view.set_zoom(50)
    w, h = view.lay.find(0).w, view.lay.find(0).h
    view.rotate(90)
    pl = view.lay.find(0)
    assert (pl.w, pl.h) == pytest.approx((h, w))
    view.rotate(-90)
    assert view.rotation == 0


def test_find_matches_and_their_boxes(view):
    doc = view.doc
    page = sample_pdf.page_of(0, 0)
    loose = find_in_page(doc, page, "moon")
    exact = find_in_page(doc, page, "Moon", match_case=True)
    assert len(loose) > len(exact) > 0          # "moons" too, without Match case
    w, h = view.sizes[page]
    for m in loose:
        assert len(m.rects) == 1                # one box a word, not one a letter
        r = m.rects[0]
        assert 0 < r.left() < r.right() < w and 0 < r.top() < r.bottom() < h
        assert doc.getAllText(page).text()[m.start:m.start + m.length].lower() == "moon"
    view.set_matches(exact, 0)
    assert view.match == 0


def test_line_boxes_join_letters_by_line():
    from PySide6.QtCore import QRectF
    boxes = line_boxes([QRectF(10, 10, 5, 8), QRectF(16, 12, 4, 6), QRectF(10, 30, 5, 8)])
    assert len(boxes) == 2 and boxes[0] == QRectF(10, 10, 10, 8)


def test_select_and_copy_text(view, qapp):
    page = sample_pdf.page_of(0, 0)
    view._select(page, QPointF(30, 205), page, QPointF(570, 300))   # from the left margin into the right
    assert "The night sky changes" in view.selected_text and view.selection[page]
    assert view.copy() and qapp.clipboard().text() == view.selected_text
    view.select_all()
    assert "Before you begin" in view.selected_text and "Phases of the Moon" in view.selected_text
    view.clear_selection()
    assert view.selected_text == "" and not view.selection


def test_links_go_to_their_page_and_back_returns(view, qapp):
    view.set_zoom(layout.FIT_WIDTH)
    view.go_to(1, record=False)
    qapp.processEvents()
    pl = view.lay.find(1)
    # The test PDF links its page 2 (72,40 - 300,72 points) to the Moon chapter.
    x, y = view.lay.from_page(pl, 150, 55, 0, view.sizes[1])
    pos = QPointF(x - view.horizontalScrollBar().value(), y - view.verticalScrollBar().value())
    link = view.link_at(pos)
    assert link is not None and link[1] == sample_pdf.page_of(5, 0)
    view.follow(link)
    assert view.current_page() == sample_pdf.page_of(5, 0)
    view.back()
    assert view.current_page() == 1
    x2, y2 = view.lay.from_page(view.lay.find(1), 400, 55, 0, view.sizes[1])
    web = view.link_at(QPointF(x2 - view.horizontalScrollBar().value(), y2 - view.verticalScrollBar().value()))
    assert web is not None and web[0].toString() == "https://example.com/"
