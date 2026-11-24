import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtPdf import QPdfDocument

import sample_pdf
from pr7r import history, layout, settings, theme
from pr7r.main_window import MainWindow


def test_starts_on_the_start_page(window):
    assert window.doc is None and window.stack.currentWidget() is window.home
    assert not window.tabwrap.isVisible() and not window.find_box.isEnabled()
    assert window.windowTitle() == "Paragon PR7-R"


def test_open_a_document(window, pdfs):
    window.open_files([str(pdfs["book"])])
    d = window.doc
    assert d and d.view.page_count() == 19 and window.stack.currentWidget() is d.view
    assert window.windowTitle() == "Night Skies.pdf - Paragon PR7-R"
    assert window.tabs.count() == 1 and window.tabs.tabText(0) == "Night Skies.pdf"
    assert window.page_box.text() == "1" and window.page_total.text() == "/ 19"
    # Bookmarks: the outline as a tree (Cover and six chapters, each with three sections).
    assert window.side.isVisible() and window.tree.topLevelItemCount() == 7
    assert window.tree.topLevelItem(2).childCount() == 3
    # The same file again: its tab, not a second one.
    window.open_files([str(pdfs["book"])])
    assert window.tabs.count() == 1
    window.open_files([str(pdfs["short"])])
    assert window.tabs.count() == 2 and window.doc.name == "Inverter manual.pdf"
    assert not window.side.isVisible()          # no outline: no Bookmarks panel
    window.tabs.setCurrentIndex(0)
    assert window.doc.name == "Night Skies.pdf" and window.side.isVisible()


def test_bookmarks_and_page_box_go_to_pages(window, pdfs, qapp):
    window.open_files([str(pdfs["book"])])
    moon = window.tree.topLevelItem(6)
    assert moon.text(0) == "6  The Moon and planets"
    window._bookmark_clicked(moon)
    assert window.view.current_page() == sample_pdf.page_of(5, 0)
    assert window.page_box.text() == str(sample_pdf.page_of(5, 0) + 1)
    window.page_box.setText("3")
    window._page_entered()
    assert window.view.current_page() == 2
    assert window.tree.currentItem().text(0) == "Reading a star chart"    # follows the page being read
    window.answers["page"] = 10
    window.go_to_page_dialog()
    assert window.view.current_page() == 9
    window.actions_by_key["back"].trigger()
    assert window.view.current_page() == 2


def test_find(window, pdfs):
    window.open_files([str(pdfs["book"])])
    window.find_box.setText("moon")
    window.find_next(True)
    v = window.view
    total = len(v.matches)
    assert total > 10 and window.find_count.text() == f"1 of {total}"
    first = v.matches[v.match]
    window.find_next(True)
    assert window.find_count.text() == f"2 of {total}"
    window.find_next(False)
    window.find_next(False)
    assert window.find_count.text() == f"{total} of {total}"          # wraps around
    assert v.current_page() == v.matches[-1].page
    window.k_case.setChecked(True)
    window._find_edited()
    window.find_box.setText("Moon")
    window.find_next(True)
    assert len(v.matches) < total
    window.find_box.setText("no such words")
    window.find_next(True)
    assert window.find_count.text() == "No matches" and not v.matches
    assert first.page >= 0


def test_reopens_where_the_reader_was(qapp, clean_settings, pdfs):
    w = MainWindow()
    w.open_files([str(pdfs["book"])])
    w.set_zoom(layout.FIT_WIDTH)
    w.set_mode(layout.FACING)
    w.view.go_to(8)
    w.close_tab(0)
    assert w.stack.currentWidget() is w.home and w.home.items        # back on the start page, listed there
    w.open_files([str(pdfs["book"])])
    v = w.view
    assert v.zoom == layout.FIT_WIDTH and v.mode == layout.FACING and v.current_page() in (8, 9)
    w.close()


def test_session_comes_back(qapp, clean_settings, pdfs):
    w = MainWindow()
    w.open_files([str(pdfs["book"]), str(pdfs["short"])])
    w.tabs.setCurrentIndex(0)
    w.close()
    w2 = MainWindow()
    assert [d.name for d in w2.docs] == ["Night Skies.pdf", "Inverter manual.pdf"]
    assert w2.doc.name == "Night Skies.pdf"
    w2.close()
    settings.set("restore_session", False)
    w3 = MainWindow()
    assert not w3.docs
    w3.close()


def test_password_and_bad_files(window, pdfs, tmp_path):
    window.answers["password"] = "wrong"
    errors = []
    window.answers["error"] = lambda text: errors.append(text)
    window.open_files([str(pdfs["locked"])])
    assert not window.docs and "password" in errors[-1]
    window.answers["password"] = "secret"
    window.open_files([str(pdfs["locked"])])
    assert window.doc and window.view.page_count() == 19
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf at all")
    window.open_files([str(junk)])
    assert len(window.docs) == 1 and "couldn't open" in errors[-1]
    window.open_files([str(tmp_path / "missing.pdf")])
    assert "doesn't exist" in errors[-1]


def test_rename_and_save_as(window, pdfs, tmp_path):
    window.open_files([str(pdfs["book"])])
    window.view.go_to(4)
    before = pdfs["book"].read_bytes()
    window.answers["rename"] = "Stars"
    window.rename()
    renamed = tmp_path / "Stars.pdf"
    assert renamed.exists() and not pdfs["book"].exists() and renamed.read_bytes() == before
    assert window.tabs.tabText(0) == "Stars.pdf" and window.view.current_page() == 4
    assert window.hist.get(str(renamed)) is not None
    copy = tmp_path / "copy.pdf"
    window.answers["save_as"] = str(copy)
    window.save_as()
    assert copy.read_bytes() == before


def test_print_to_a_pdf_file(window, pdfs, tmp_path):
    from PySide6.QtPrintSupport import QPrinter
    window.open_files([str(pdfs["book"])])
    out = tmp_path / "printed.pdf"
    printer = QPrinter(QPrinter.PrinterMode.ScreenResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(out))
    printer.setPrintRange(QPrinter.PrintRange.PageRange)
    printer.setFromTo(2, 4)
    window.answers["print"] = printer
    window.print_document()
    printed = QPdfDocument()
    assert printed.load(str(out)) == QPdfDocument.Error.None_ and printed.pageCount() == 3
    printed.close()


def test_properties(window, pdfs):
    window.answers["properties"] = True
    window.open_files([str(pdfs["book"])])
    window.properties()
    v = window.properties_dialog.values()
    assert v["Title"] == "A Field Guide to Night Skies" and v["Number of pages"] == "19"
    assert v["Page size"].startswith("210 x 297 mm")     # A4


def test_presentation_and_back(window, pdfs):
    window.open_files([str(pdfs["book"])])
    v = window.view
    v.go_to(5)
    window.set_fullscreen("presentation")
    assert window.fullscreen == "presentation" and v.presenting and not v.continuous
    assert v.zoom == layout.FIT_PAGE and not window.menuBar().isVisible()
    assert [p.page for p in v.lay.placed] == [5]
    v.next_page()
    window._escape()
    assert window.fullscreen is None and not v.presenting and v.continuous and window.menuBar().isVisible()
    assert v.current_page() == 6


def test_finish_and_favorites(window, pdfs):
    window.open_files([str(pdfs["book"])])
    window.set_finish("aurora")
    assert theme.FINISH == "aurora" and settings.get("finish") == "aurora"
    window.set_finish("obsidian")
    window.view.go_to(3)
    window.add_favorite()
    window._fill_favorites()
    names = [a.text() for a in window.fav_menu.actions()]
    assert "Night Skies.pdf: page 4" in names
    window.view.go_to(0)
    fav = next(a for a in window.fav_menu.actions() if a.text() == "Night Skies.pdf: page 4")
    fav.trigger()
    assert window.view.current_page() == 3


def test_reload_when_the_file_changes(window, pdfs):
    window.open_files([str(pdfs["book"])])
    window.view.go_to(2)
    sample_pdf.short(pdfs["book"], "Rewritten", 5, pages=4)     # another program rewrites the file
    window.reload(str(pdfs["book"]))
    assert window.view.page_count() == 4 and window.view.current_page() == 2
    assert not window.doc.outline


def test_copy_and_select_all(window, pdfs, qapp):
    window.open_files([str(pdfs["book"])])
    assert not window.actions_by_key["copy"].isEnabled()
    window.actions_by_key["select_all"].trigger()
    assert window.actions_by_key["copy"].isEnabled()
    window.view.setFocus()
    window.copy()
    assert "Before you begin" in qapp.clipboard().text()


def test_the_file_is_not_kept_open(window, pdfs, tmp_path):
    """SumatraPDF doesn't lock documents: another program can rewrite or rename the PDF while it's shown. (QtPdf would
    keep a file it loaded open, and Windows refuses to overwrite or rename an open file.)"""
    window.open_files([str(pdfs["book"])])
    path = pdfs["book"]
    if os.path.isdir("/proc/self/fd"):
        held = [os.path.realpath(f"/proc/self/fd/{fd}") for fd in os.listdir("/proc/self/fd")]
        assert str(path.resolve()) not in held
    new = tmp_path / "new.pdf"
    sample_pdf.short(new, "New", 9, pages=2)
    os.replace(new, path)                          # overwrite it in place, as an exporter does
    moved = tmp_path / "moved.pdf"
    os.rename(path, moved)                         # and rename it
    os.rename(moved, path)
    window.reload(str(path))
    assert window.view.page_count() == 2
