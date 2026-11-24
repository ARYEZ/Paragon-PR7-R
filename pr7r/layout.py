"""Where every page goes (no Qt): SumatraPDF's layouts (single page, facing, book view; continuous or one spread at
a time), its zoom modes (fit page, fit width, a percentage) and rotation, as plain arithmetic.

Sizes are PDF points (1/72 inch). `scale` is screen pixels per point: 100% is the real size on the screen, so 96 dpi
gives 96/72 pixels a point. Everything the view draws or scrolls to comes from `Layout.place`, so it is tested here
without a window."""

from __future__ import annotations

from dataclasses import dataclass

MARGIN = 14        # around the pages, in pixels (= GAP: a page scrolled to the top hides the one above)
GAP = 14           # between pages, both ways
SINGLE, FACING, BOOK = "single", "facing", "book"
FIT_PAGE, FIT_WIDTH = "fitpage", "fitwidth"
ZOOMS = [6400, 3200, 1600, 800, 400, 200, 150, 125, 100, 50, 25, 12.5, 8.33]   # Sumatra's zoom menu
MIN_ZOOM, MAX_ZOOM = 8.33, 6400


@dataclass
class Placed:
    page: int
    x: float
    y: float
    w: float
    h: float

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


def rotated(size: tuple[float, float], rotation: int) -> tuple[float, float]:
    w, h = size
    return (h, w) if rotation % 180 else (w, h)


def rows(count: int, mode: str) -> list[list[int | None]]:
    """The pages in each row. Book view puts the first page (the cover) alone on the right, as a printed book does;
    the slot on its left is None."""
    if mode == SINGLE:
        return [[i] for i in range(count)]
    if mode == FACING:
        return [list(range(i, min(i + 2, count))) for i in range(0, count, 2)]
    if count == 0:
        return []
    out: list[list[int | None]] = [[None, 0]]
    out += [list(range(i, min(i + 2, count))) for i in range(1, count, 2)]
    return out


def row_of(page: int, mode: str) -> int:
    if mode == SINGLE:
        return page
    if mode == FACING:
        return page // 2
    return 0 if page == 0 else (page + 1) // 2


def scale_for(zoom, sizes: list[tuple[float, float]], mode: str, rotation: int, view_w: float, view_h: float,
              dpi: float = 96) -> float:
    """Pixels per point for a zoom: FIT_PAGE, FIT_WIDTH or a percentage."""
    if not sizes:
        return dpi / 72
    if zoom not in (FIT_PAGE, FIT_WIDTH):
        return float(zoom) / 100 * dpi / 72
    cols = 1 if mode == SINGLE else 2
    pw = max(rotated(s, rotation)[0] for s in sizes)
    ph = max(rotated(s, rotation)[1] for s in sizes)
    by_width = (view_w - 2 * MARGIN - (cols - 1) * GAP) / (pw * cols)
    if zoom == FIT_WIDTH:
        return max(by_width, 0.01)
    return max(min(by_width, (view_h - 2 * MARGIN) / ph), 0.01)


def percent(scale: float, dpi: float = 96) -> float:
    return scale * 72 / dpi * 100


def step_zoom(current_percent: float, up: bool) -> float:
    """Zoom in / out goes to the next of Sumatra's steps."""
    steps = sorted(ZOOMS)
    if up:
        bigger = [z for z in steps if z > current_percent + 0.01]
        return bigger[0] if bigger else MAX_ZOOM
    smaller = [z for z in steps if z < current_percent - 0.01]
    return smaller[-1] if smaller else MIN_ZOOM


@dataclass
class Layout:
    """The pages placed for one view: `placed` (pixels, document coordinates), `width` / `height` of the whole."""
    placed: list[Placed]
    width: float
    height: float
    scale: float

    @classmethod
    def place(cls, sizes: list[tuple[float, float]], mode: str = SINGLE, continuous: bool = True, rotation: int = 0,
              scale: float = 1.0, view_w: float = 800, view_h: float = 600, current: int = 0) -> "Layout":
        """`sizes` in points (unrotated); `current` is the page whose spread is shown when not continuous."""
        all_rows = rows(len(sizes), mode)
        if not continuous and all_rows:
            all_rows = [all_rows[min(row_of(current, mode), len(all_rows) - 1)]]
        cols = 1 if mode == SINGLE else 2
        slot_w = max((rotated(s, rotation)[0] for s in sizes), default=0) * scale
        content_w = cols * slot_w + (cols - 1) * GAP
        width = max(view_w, content_w + 2 * MARGIN)
        left = (width - content_w) / 2
        placed, y = [], MARGIN
        for row in all_rows:
            heights = [rotated(sizes[p], rotation)[1] * scale for p in row if p is not None]
            row_h = max(heights, default=0)
            for col, p in enumerate(row):
                if p is None:
                    continue
                w, h = (v * scale for v in rotated(sizes[p], rotation))
                if cols == 1:
                    x = left + (slot_w - w) / 2
                elif col == 0:
                    x = left + slot_w - w            # the left page sits against the spine
                else:
                    x = left + slot_w + GAP
                if mode != SINGLE and len(row) == 1:     # a last page alone in facing view: left slot
                    x = left + slot_w - w
                placed.append(Placed(p, x, y + (row_h - h) / 2, w, h))
            y += row_h + GAP
        height = max(y - GAP + MARGIN, view_h if not continuous else 0)
        if not continuous and placed:                     # one spread: centred in the window when it fits
            extra = max(0.0, view_h - (y - GAP + MARGIN))
            for pl in placed:
                pl.y += extra / 2
        return cls(placed, width, max(height, 0), scale)

    def find(self, page: int) -> Placed | None:
        for pl in self.placed:
            if pl.page == page:
                return pl
        return None

    def page_at(self, x: float, y: float) -> Placed | None:
        for pl in self.placed:
            if pl.contains(x, y):
                return pl
        return None

    def current(self, top: float, view_h: float) -> int:
        """The page the reader is on: the one covering most of the window (Sumatra's page number)."""
        best, best_cover = 0, -1.0
        for pl in self.placed:
            cover = min(pl.y + pl.h, top + view_h) - max(pl.y, top)
            if cover > best_cover + 0.5:
                best, best_cover = pl.page, cover
        return best

    def to_page(self, pl: Placed, x: float, y: float, rotation: int, size: tuple[float, float]) -> tuple[float, float]:
        """A point in the view (document pixels) as a point on the unrotated page, in points."""
        u, v = (x - pl.x) / self.scale, (y - pl.y) / self.scale
        w, h = size
        r = rotation % 360
        if r == 90:
            return v, h - u
        if r == 180:
            return w - u, h - v
        if r == 270:
            return w - v, u
        return u, v

    def from_page(self, pl: Placed, u: float, v: float, rotation: int, size: tuple[float, float]) -> tuple[float, float]:
        """A point on the unrotated page (points) in the view (document pixels)."""
        w, h = size
        r = rotation % 360
        if r == 90:
            x, y = h - v, u
        elif r == 180:
            x, y = w - u, h - v
        elif r == 270:
            x, y = v, w - u
        else:
            x, y = u, v
        return pl.x + x * self.scale, pl.y + y * self.scale
