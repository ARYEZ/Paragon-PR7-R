"""Write sample PDFs with Qt's own PDF writer (no outside files): python tools/sample_pdf.py OUT_DIR

Used by the mock-up / screenshots and by tests, so every picture and test reads a real PDF."""
from __future__ import annotations

import random
import sys
from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPageLayout, QPageSize, QPainter, QPainterPath, QPdfWriter)

LOREM = ("The night sky changes through the year as the Earth travels around the Sun. Each season brings its own "
         "constellations above the horizon after dusk, while others set in the west and wait for their turn again. "
         "A dark site, a little patience and eyes that have had twenty minutes to adapt are all that is needed to "
         "begin. Binoculars show far more than most people expect: star clusters, the craters of the Moon and the "
         "four bright moons of Jupiter lined up beside the planet.")

CHAPTERS = [
    ("1", "Before you begin", ["Dark adaptation", "Reading a star chart", "What to bring"]),
    ("2", "The winter sky", ["Orion and its nebula", "The Pleiades", "Sirius, the brightest star"]),
    ("3", "The spring sky", ["The Plough", "Leo and Regulus", "Galaxies in Virgo"]),
    ("4", "The summer sky", ["The Summer Triangle", "The Milky Way", "Scorpius low in the south"]),
    ("5", "The autumn sky", ["Andromeda", "The Square of Pegasus", "Meteor showers"]),
    ("6", "The Moon and planets", ["Phases of the Moon", "Finding planets", "Eclipses"]),
]


_FONTS: list[int] = []


def _fonts() -> None:
    """Load PR7-R's Inter fonts for the text. Without them, Qt on Windows' offscreen platform has no fonts at all
    and writes no text into the PDF (pages with pictures and no words; Find would have nothing to find)."""
    if not _FONTS:
        from PySide6.QtGui import QFontDatabase
        for ttf in (Path(__file__).resolve().parents[1] / "pr7r" / "fonts").glob("*.ttf"):
            _FONTS.append(QFontDatabase.addApplicationFont(str(ttf)))


def _sky(p: QPainter, r: QRectF, seed: int) -> None:
    """A figure in family colours: a dusk sky with stars over hills."""
    rnd = random.Random(seed)
    g = QLinearGradient(r.topLeft(), r.bottomLeft())
    g.setColorAt(0, QColor("#12060C")); g.setColorAt(.6, QColor("#5A1426")); g.setColorAt(1, QColor("#E2502A"))
    p.fillRect(r, g)
    p.setPen(Qt.NoPen)
    for _ in range(140):
        x, y, s = rnd.uniform(r.left(), r.right()), rnd.uniform(r.top(), r.top() + r.height() * .6), rnd.uniform(.6, 2.2)
        p.setBrush(QColor(255, 236, 226, rnd.randint(120, 255)))
        p.drawEllipse(QPointF(x, y), s, s)
    moon = QPointF(r.left() + r.width() * rnd.uniform(.6, .85), r.top() + r.height() * .25)
    for k in range(6, 0, -1):  # the moon's glow as rings (PDF writers flatten see-through gradients)
        p.setBrush(QColor(255, 200, 170, 18)); p.drawEllipse(moon, r.height() * .045 * k / 1.5, r.height() * .045 * k / 1.5)
    p.setBrush(QColor("#FFE7D6")); p.drawEllipse(moon, r.height() * .07, r.height() * .07)
    for layer, colour in enumerate(("#33101A", "#160A0E")):
        path = QPainterPath(QPointF(r.left(), r.bottom()))
        x = r.left()
        while x <= r.right():
            path.lineTo(x, r.bottom() - r.height() * (.28 - .1 * layer) - rnd.uniform(0, r.height() * .12))
            x += r.width() / 7
        path.lineTo(r.right(), r.bottom()); path.closeSubpath()
        p.setBrush(QColor(colour)); p.drawPath(path)


def field_guide(path: Path) -> Path:
    """An 18-page book: a cover, then chapters with headings, body text, figures and page numbers."""
    _fonts()
    w = QPdfWriter(str(path))
    w.setTitle("A Field Guide to Night Skies")
    w.setCreator("Paragon PR7-R sample")
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    w.setResolution(144)
    p = QPainter(w)
    W, H = w.width(), w.height()
    m = W * .12

    def font(px, bold=False, italic=False):
        f = QFont("Inter"); f.setPixelSize(int(px)); f.setBold(bold); f.setItalic(italic)
        return f

    def number(n):
        p.setFont(font(H * .012)); p.setPen(QColor("#77707A"))
        p.drawText(QRectF(0, H - m * .7, W, m * .4), Qt.AlignCenter, str(n))

    # cover
    _sky(p, QRectF(0, 0, W, H), 7)
    p.setPen(QColor("#FFFFFF")); p.setFont(font(H * .05, bold=True))
    p.drawText(QRectF(m, H * .62, W - 2 * m, H * .2), Qt.AlignLeft | Qt.TextWordWrap, "A Field Guide\nto Night Skies")
    p.setFont(font(H * .016)); p.drawText(QRectF(m, H * .82, W - 2 * m, H * .05), Qt.AlignLeft, "SEASONS, STARS AND PLANETS")
    page = 1
    for num, title, sections in CHAPTERS:
        for k, section in enumerate(sections):
            w.newPage(); page += 1
            y = m
            if k == 0:
                p.setPen(QColor("#C2183F")); p.setFont(font(H * .014, bold=True))
                p.drawText(QRectF(m, y, W, H * .03), Qt.AlignLeft, f"CHAPTER {num}")
                y += H * .03
                p.setPen(QColor("#1A1418")); p.setFont(font(H * .036, bold=True))
                p.drawText(QRectF(m, y, W - 2 * m, H * .06), Qt.AlignLeft, title)
                y += H * .075
            p.setPen(QColor("#1A1418")); p.setFont(font(H * .02, bold=True))
            p.drawText(QRectF(m, y, W - 2 * m, H * .04), Qt.AlignLeft, section)
            y += H * .045
            p.setFont(font(H * .0135)); p.setPen(QColor("#2A2428"))
            for para in range(2):
                r = p.boundingRect(QRectF(m, y, W - 2 * m, H), Qt.TextWordWrap, LOREM)
                p.drawText(r, Qt.TextWordWrap, LOREM)
                y = r.bottom() + H * .015
            fig = QRectF(m, y + H * .01, W - 2 * m, H * .26)
            _sky(p, fig, page)
            p.setFont(font(H * .012, italic=True)); p.setPen(QColor("#77707A"))
            p.drawText(QRectF(m, fig.bottom() + H * .008, W - 2 * m, H * .03), Qt.AlignLeft,
                       f"Figure {num}.{k + 1}  {section}")
            y = fig.bottom() + H * .05
            p.setFont(font(H * .0135)); p.setPen(QColor("#2A2428"))
            r = p.boundingRect(QRectF(m, y, W - 2 * m, H - m - y), Qt.TextWordWrap, LOREM)
            p.drawText(r, Qt.TextWordWrap, LOREM)
            number(page)
    p.end()
    return path


def short(path: Path, title: str, seed: int, pages: int = 3) -> Path:
    """A few pages with a title and a figure (the home page's other recent documents)."""
    _fonts()
    w = QPdfWriter(str(path))
    w.setTitle(title)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    w.setResolution(96)
    p = QPainter(w)
    W, H = w.width(), w.height()
    for n in range(pages):
        if n:
            w.newPage()
        f = QFont("Inter"); f.setPixelSize(int(H * .04)); f.setBold(True)
        p.setFont(f); p.setPen(QColor("#1A1418"))
        p.drawText(QRectF(W * .1, H * .08, W * .8, H * .12), Qt.AlignLeft | Qt.TextWordWrap, title)
        _sky(p, QRectF(W * .1, H * .22, W * .8, H * .3), seed + n)
        f.setPixelSize(int(H * .014)); f.setBold(False); p.setFont(f); p.setPen(QColor("#2A2428"))
        p.drawText(QRectF(W * .1, H * .56, W * .8, H * .35), Qt.TextWordWrap, LOREM + "\n\n" + LOREM)
    p.end()
    return path


def page_of(chapter: int, section: int) -> int:
    """The page (0-based) of a chapter's section in field_guide: the cover, then one page per section."""
    return 1 + chapter * 3 + section


def book(path: Path, password: str | None = None) -> Path:
    """field_guide with what Qt's PDF writer can't make, added by pypdf (a test-only dependency): bookmarks (the
    outline: Cover, each chapter, its sections), a link on page 2 to the Moon chapter and one to a web page, and
    optionally a password."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Link
    plain = field_guide(path.with_name(path.stem + "-plain.pdf"))
    writer = PdfWriter(clone_from=PdfReader(str(plain)))
    writer.add_outline_item(title="Cover", page_number=0)
    for c, (num, title, sections) in enumerate(CHAPTERS):
        parent = writer.add_outline_item(title=f"{num}  {title}", page_number=page_of(c, 0))
        for k, section in enumerate(sections):
            writer.add_outline_item(title=section, page_number=page_of(c, k), parent=parent)
    h = float(writer.pages[1].mediabox.height)
    writer.add_annotation(page_number=1, annotation=Link(rect=(72, h - 72, 300, h - 40),
                                                          target_page_index=page_of(5, 0)))
    writer.add_annotation(page_number=1, annotation=Link(rect=(320, h - 72, 520, h - 40), url="https://example.com/"))
    if password:
        writer.encrypt(password, algorithm="AES-256")
    with open(path, "wb") as fh:
        writer.write(fh)
    plain.unlink()
    return path


if __name__ == "__main__":
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication([])
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    print(field_guide(out / "Night Skies.pdf"))
