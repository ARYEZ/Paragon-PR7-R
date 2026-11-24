import json

from pr7r.history import History


def make(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"%PDF-1.4")
        out.append(str(p))
    return out


def test_opening_counts_and_remembers_where_the_reader_was(tmp_path):
    a, = make(tmp_path, "a.pdf")
    h = History(tmp_path / "h.json")
    assert h.opened(a).opened == 1
    h.remember(a, page=7, zoom="fitwidth", layout="facing", continuous=False, rotation=90, top=120.5)
    h.opened(a)
    again = History(tmp_path / "h.json").get(a)      # read back from the file
    assert (again.opened, again.page, again.zoom, again.layout, again.continuous, again.rotation, again.top) == \
        (2, 7, "fitwidth", "facing", False, 90, 120.5)


def test_frequently_read_most_opened_first_without_missing_or_hidden(tmp_path):
    a, b, c, gone = make(tmp_path, "a.pdf", "b.pdf", "c.pdf", "gone.pdf")
    h = History(tmp_path / "h.json")
    for path, times in ((a, 1), (b, 3), (c, 2), (gone, 5)):
        for _ in range(times):
            h.opened(path)
    (tmp_path / "gone.pdf").unlink()
    assert [e.path for e in h.frequent()] == [b, c, a]
    h.hide(c)
    assert [e.path for e in h.frequent()] == [b, a]
    h.opened(c)                     # opened again: back on the start page
    assert c in [e.path for e in h.frequent()]
    assert h.recent()[0].path == c


def test_favorites(tmp_path):
    a, b = make(tmp_path, "b-doc.pdf", "a-doc.pdf")
    h = History(tmp_path / "h.json")
    h.opened(a)
    h.add_favorite(a, 4, "Chapter 2")
    h.add_favorite(a, 1)
    h.add_favorite(a, 4, "twice")            # one favorite a page
    h.add_favorite(b, 0)
    favs = History(tmp_path / "h.json").favorites()
    assert [(e.path, f.page, f.name) for e, f in favs] == [(b, 0, ""), (a, 1, ""), (a, 4, "Chapter 2")]
    h.remove_favorite(a, 4)
    assert [(f.page) for e, f in h.favorites() if e.path == a] == [1]


def test_renamed_keeps_the_entry_and_forget_drops_it(tmp_path):
    a, = make(tmp_path, "a.pdf")
    h = History(tmp_path / "h.json")
    h.opened(a)
    h.remember(a, page=3)
    new = str(tmp_path / "renamed.pdf")
    h.renamed(a, new)
    assert h.get(a) is None and h.get(new).page == 3
    h.forget(new)
    assert History(tmp_path / "h.json").get(new) is None


def test_a_damaged_history_file_is_ignored(tmp_path):
    f = tmp_path / "h.json"
    f.write_text("{not json")
    assert History(f).entries == {}
    f.write_text(json.dumps({"files": [{"path": "x.pdf", "page": 2}, {"bogus": 1}]}))
    assert list(e.page for e in History(f).entries.values()) == [2]
