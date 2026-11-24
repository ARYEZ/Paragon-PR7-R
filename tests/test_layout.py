import pytest

from pr7r import layout
from pr7r.layout import BOOK, FACING, FIT_PAGE, FIT_WIDTH, GAP, MARGIN, SINGLE, Layout

A4 = (595.0, 842.0)


def test_rows_for_each_view():
    assert layout.rows(5, SINGLE) == [[0], [1], [2], [3], [4]]
    assert layout.rows(5, FACING) == [[0, 1], [2, 3], [4]]
    assert layout.rows(5, BOOK) == [[None, 0], [1, 2], [3, 4]]     # the cover alone, on the right
    assert layout.rows(0, BOOK) == []
    assert [layout.row_of(p, BOOK) for p in range(5)] == [0, 1, 1, 2, 2]
    assert [layout.row_of(p, FACING) for p in range(5)] == [0, 0, 1, 1, 2]


def test_zoom_modes():
    sizes = [A4] * 3
    # 100% is the real size: 96 px an inch, 72 points an inch.
    assert layout.scale_for(100, sizes, SINGLE, 0, 1000, 800) == pytest.approx(96 / 72)
    assert layout.percent(96 / 72) == pytest.approx(100)
    w = layout.scale_for(FIT_WIDTH, sizes, SINGLE, 0, 1000, 800)
    assert A4[0] * w == pytest.approx(1000 - 2 * MARGIN)
    p = layout.scale_for(FIT_PAGE, sizes, SINGLE, 0, 1000, 800)
    assert A4[1] * p == pytest.approx(800 - 2 * MARGIN) and p < w
    # Facing: two pages and the gap fill the width.
    f = layout.scale_for(FIT_WIDTH, sizes, FACING, 0, 1000, 800)
    assert 2 * A4[0] * f + GAP == pytest.approx(1000 - 2 * MARGIN)
    # Rotated a quarter turn, the page is landscape: fit width uses its height.
    r = layout.scale_for(FIT_WIDTH, sizes, SINGLE, 90, 1000, 800)
    assert A4[1] * r == pytest.approx(1000 - 2 * MARGIN)


def test_zoom_steps_follow_sumatras_menu():
    assert layout.step_zoom(100, True) == 125
    assert layout.step_zoom(100, False) == 50
    assert layout.step_zoom(110, True) == 125 and layout.step_zoom(110, False) == 100
    assert layout.step_zoom(6400, True) == layout.MAX_ZOOM
    assert layout.step_zoom(8.33, False) == layout.MIN_ZOOM


def test_single_continuous_stacks_pages_centred():
    lay = Layout.place([A4, A4, (842, 595)], SINGLE, True, 0, 1.0, 1200, 600)
    assert [p.page for p in lay.placed] == [0, 1, 2]
    a, b, c = lay.placed
    assert a.y == MARGIN and b.y == a.y + a.h + GAP and c.y == b.y + b.h + GAP
    assert a.x + a.w / 2 == pytest.approx(600)          # centred in the window
    assert c.w == 842 and c.x + c.w / 2 == pytest.approx(600)
    assert lay.height == pytest.approx(c.y + c.h + MARGIN)


def test_facing_and_book_view():
    lay = Layout.place([A4] * 3, FACING, True, 0, 1.0, 1400, 600)
    a, b, c = lay.placed
    assert a.y == b.y and b.x == pytest.approx(a.x + a.w + GAP) and c.y > a.y
    assert c.x == pytest.approx(a.x)                       # a last page alone sits on the left
    book = Layout.place([A4] * 3, BOOK, True, 0, 1.0, 1400, 600)
    cover, p1, p2 = book.placed
    assert cover.x == pytest.approx(p2.x)                  # the cover is on the right, like a book's
    assert p1.y == p2.y > cover.y and p1.x < p2.x


def test_one_spread_at_a_time():
    lay = Layout.place([A4] * 6, FACING, False, 0, 0.5, 1200, 800, current=3)
    assert [p.page for p in lay.placed] == [2, 3]
    assert lay.height >= 800
    # centred up and down when it fits
    top = lay.placed[0].y
    assert top == pytest.approx((800 - A4[1] * 0.5) / 2)


def test_current_page_is_the_one_filling_the_window():
    lay = Layout.place([A4] * 4, SINGLE, True, 0, 1.0, 800, 600)
    assert lay.current(0, 600) == 0
    second = lay.placed[1]
    assert lay.current(second.y - 50, 600) == 1          # mostly page 2 in view
    assert lay.current(lay.height - 600, 600) == 3


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_page_points_and_view_points_round_trip(rotation):
    lay = Layout.place([A4], SINGLE, True, rotation, 1.5, 1600, 1600)
    pl = lay.placed[0]
    for u, v in ((10, 20), (500, 800), (300, 421)):
        x, y = lay.from_page(pl, u, v, rotation, A4)
        assert pl.contains(x, y)
        assert lay.to_page(pl, x, y, rotation, A4) == pytest.approx((u, v))
    # The page's top left corner turns with the page: a quarter turn right puts it at the top right.
    x, y = lay.from_page(pl, 0, 0, rotation, A4)
    corner = {0: (pl.x, pl.y), 90: (pl.x + pl.w, pl.y), 180: (pl.x + pl.w, pl.y + pl.h), 270: (pl.x, pl.y + pl.h)}
    assert (x, y) == pytest.approx(corner[rotation])
