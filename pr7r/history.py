"""SumatraPDF's file history (no Qt): every document opened, how often, when, and where the reader left it (page,
zoom, layout, rotation), so it reopens there; the start page's "Frequently read"; favorites (a page with a name).

Kept as JSON in %APPDATA%\\Paragon\\PR7-R\\history.json (PR7R_DATA points elsewhere: tests always set it). Paths
are compared case-insensitively on Windows, as the file system does."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

KEEP = 500           # how many documents are remembered (oldest forgotten first)
FREQUENT = 10        # how many the start page shows


def data_dir() -> Path:
    env = os.environ.get("PR7R_DATA")
    if env:
        return Path(env)
    base = os.environ.get("APPDATA") or os.path.join(Path.home(), ".config")
    return Path(base) / "Paragon" / "PR7-R"


def _key(path: str) -> str:
    p = os.path.abspath(path)
    return os.path.normcase(p)


@dataclass
class Favorite:
    page: int
    name: str = ""


@dataclass
class Entry:
    path: str
    page: int = 0
    zoom: str = ""            # "fitpage", "fitwidth" or a percentage as text; "" = the default
    layout: str = ""          # "single", "facing", "book"; "" = the default
    continuous: bool = True
    rotation: int = 0
    top: float = 0.0          # where in the page the window's top was, in points
    opened: int = 0           # how many times
    last: float = 0.0         # time.time() when last opened
    favorites: list[Favorite] = field(default_factory=list)
    hidden: bool = False      # taken off the start page ("Remove from history" keeps nothing)


class History:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "history.json"
        self.entries: dict[str, Entry] = {}
        self.load()

    # ------------------------------------------------------------------ storage
    def load(self) -> None:
        self.entries = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for d in raw.get("files", []) if isinstance(raw, dict) else []:
            try:
                favs = [Favorite(**f) for f in d.pop("favorites", [])]
                e = Entry(**{k: v for k, v in d.items() if k in Entry.__dataclass_fields__}, favorites=favs)
            except TypeError:
                continue
            self.entries[_key(e.path)] = e

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        files = sorted(self.entries.values(), key=lambda e: -e.last)[:KEEP]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"files": [asdict(e) for e in files]}, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ------------------------------------------------------------------ documents
    def get(self, path: str) -> Entry | None:
        return self.entries.get(_key(path))

    def opened(self, path: str) -> Entry:
        """A document was opened: counted, dated, shown on the start page again. Returns its entry (where it was)."""
        e = self.entries.get(_key(path))
        if e is None:
            e = self.entries[_key(path)] = Entry(os.path.abspath(path))
        e.opened += 1
        e.last = time.time()
        e.hidden = False
        self.save()
        return e

    def remember(self, path: str, **state) -> None:
        """Where the reader is (page, zoom, layout ...), kept for the next time."""
        e = self.entries.get(_key(path))
        if e is None:
            e = self.entries[_key(path)] = Entry(os.path.abspath(path), last=time.time())
        for k, v in state.items():
            if k in Entry.__dataclass_fields__ and k not in ("path", "favorites"):
                setattr(e, k, v)
        self.save()

    def frequent(self, n: int = FREQUENT, exists=os.path.exists) -> list[Entry]:
        """The start page: most opened first, then most recent; documents that are gone or hidden are left out."""
        es = [e for e in self.entries.values() if not e.hidden and e.opened and exists(e.path)]
        es.sort(key=lambda e: (-e.opened, -e.last))
        return es[:n]

    def recent(self, n: int = 10, exists=os.path.exists) -> list[Entry]:
        """File menu's recent files: the last opened first."""
        es = [e for e in self.entries.values() if e.opened and exists(e.path)]
        es.sort(key=lambda e: -e.last)
        return es[:n]

    def hide(self, path: str) -> None:
        e = self.get(path)
        if e:
            e.hidden = True
            self.save()

    def forget(self, path: str) -> None:
        if self.entries.pop(_key(path), None) is not None:
            self.save()

    def renamed(self, old: str, new: str) -> None:
        e = self.entries.pop(_key(old), None)
        if e:
            e.path = os.path.abspath(new)
            self.entries[_key(new)] = e
            self.save()

    # ------------------------------------------------------------------ favorites
    def add_favorite(self, path: str, page: int, name: str = "") -> None:
        e = self.get(path) or self.entries.setdefault(_key(path), Entry(os.path.abspath(path), last=time.time()))
        if not any(f.page == page for f in e.favorites):
            e.favorites.append(Favorite(page, name))
            e.favorites.sort(key=lambda f: f.page)
        self.save()

    def remove_favorite(self, path: str, page: int) -> None:
        e = self.get(path)
        if e:
            e.favorites = [f for f in e.favorites if f.page != page]
            self.save()

    def favorites(self, exists=os.path.exists) -> list[tuple[Entry, Favorite]]:
        """Every favorite, by document name then page (the Favorites menu)."""
        out = [(e, f) for e in self.entries.values() if exists(e.path) for f in e.favorites]
        out.sort(key=lambda ef: (os.path.basename(ef[0].path).lower(), ef[1].page))
        return out
