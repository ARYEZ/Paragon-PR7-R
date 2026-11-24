import json
import os
import sys
import time

import pytest

from pr7r import __version__, app


def test_version(capsys):
    assert app.main(["--version"]) == 0 and capsys.readouterr().out.strip() == __version__


def test_command_line():
    files, page, new = app.parse(["a.pdf", "-page", "12", "--new-window", "b.pdf"])
    assert files == [os.path.abspath("a.pdf"), os.path.abspath("b.pdf")] and page == 11 and new
    assert app.parse(["x.pdf"]) == ([os.path.abspath("x.pdf")], None, False)


def test_a_second_launch_hands_its_files_to_the_open_window(window, pdfs, qapp):
    """Double-clicking another PDF while PR7-R is open adds a tab to that window (SumatraPDF's way)."""
    assert app.listen(window) is not None
    assert app.hand_over([str(pdfs["book"])], 3)
    deadline = time.time() + 5
    while not window.docs and time.time() < deadline:
        qapp.processEvents()
    assert window.doc and window.doc.name == "Night Skies.pdf" and window.view.current_page() == 3
    window.instance_server.close()


def test_no_window_open_means_no_hand_over(qapp, monkeypatch):
    monkeypatch.setattr(app, "server_name", lambda: "Paragon-PR7-R-test-nobody-listens")
    assert not app.hand_over(["x.pdf"], None)


def test_selftest(pdfs, tmp_path, qapp):
    out = tmp_path / "out.json"
    assert app.selftest(str(pdfs["book"]), str(out)) == 0
    got = json.loads(out.read_text())
    assert got["pages"] == 19 and got["inked"] > 50 and got["matches"] > 10 and got["bookmarks"] == 25
    assert got["fonts"] is True and got["version"] == __version__
