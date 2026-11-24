"""Start PR7-R.

    PR7-R.exe [file.pdf ...] [-page N]   open the files in tabs (in the PR7-R window that's open already, as SumatraPDF
                                          does: double-clicking more PDFs adds tabs instead of windows)
    PR7-R.exe -new-window file.pdf       a window of its own
    PR7-R.exe --register / --unregister  "Open with" and Default apps for PDFs (the installer runs these)
    PR7-R.exe --version
    PR7-R.exe --selftest FILE.pdf OUT.json   open the file offscreen and write what was read and drawn (CI checks
                                              the installed program with it; settings go to a temp folder)
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sys

TIMEOUT_MS = 1500


def server_name() -> str:
    """One window per user: a local socket named after the user (hashed: names must be plain)."""
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - no user name: one name for all
        user = "user"
    return "Paragon-PR7-R-" + hashlib.sha1(user.encode()).hexdigest()[:12]


def parse(argv: list[str]) -> tuple[list[str], int | None, bool]:
    """(files, page, new window) from the command line. -page N is 1-based, as in SumatraPDF."""
    files, page, new = [], None, False
    it = iter(range(len(argv)))
    skip = False
    for i in it:
        if skip:
            skip = False
            continue
        a = argv[i]
        low = a.lower().lstrip("-")
        if low == "page" and i + 1 < len(argv):
            try:
                page = max(int(argv[i + 1]) - 1, 0)
            except ValueError:
                pass
            skip = True
        elif low in ("new-window", "newwindow"):
            new = True
        elif not a.startswith("-"):
            files.append(os.path.abspath(a.strip('"')))
    return files, page, new


def hand_over(files: list[str], page: int | None) -> bool:
    """If a PR7-R window is open, give it the files and return True."""
    from PySide6.QtNetwork import QLocalSocket
    s = QLocalSocket()
    s.connectToServer(server_name())
    if not s.waitForConnected(TIMEOUT_MS):
        return False
    s.write(json.dumps({"files": files, "page": page}).encode() + b"\n")
    s.flush()
    s.waitForBytesWritten(TIMEOUT_MS)
    # The window closes the connection once it has the files: wait for that, so this process doesn't end before
    # they're delivered (a named pipe on Windows); then close our end if it hasn't.
    if not s.waitForDisconnected(TIMEOUT_MS):
        s.disconnectFromServer()
    return True


def listen(window):
    """Take files from later launches (hand_over) into this window."""
    from PySide6.QtNetwork import QLocalServer
    server = QLocalServer(window)
    QLocalServer.removeServer(server_name())   # a name left by a PR7-R that crashed
    if not server.listen(server_name()):
        return None

    def connection():
        sock = server.nextPendingConnection()
        if sock is None:
            return
        buf = bytearray()
        done = []

        def read():
            buf.extend(bytes(sock.readAll()))
            if buf.endswith(b"\n") and not done:
                done.append(True)
                try:
                    msg = json.loads(buf.decode())
                except ValueError:
                    return
                if msg.get("files"):
                    window.open_files(msg["files"], page=msg.get("page"))
                if window.isMinimized():
                    window.showNormal()
                window.raise_()
                window.activateWindow()
                sock.disconnectFromServer()
        sock.readyRead.connect(read)
        sock.disconnected.connect(read)
        if sock.bytesAvailable():      # on Windows the files can be here before readyRead is connected
            read()
    server.newConnection.connect(connection)
    window.instance_server = server
    return server


def selftest(path: str, out: str) -> int:
    import tempfile
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["PR7R_DATA"] = tempfile.mkdtemp()
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, tempfile.mkdtemp())
    result = {}
    try:
        from PySide6.QtGui import QColor, QFontDatabase

        from . import __version__, theme
        from .main_window import MainWindow, apply_look
        app = QApplication.instance() or QApplication(sys.argv[:1])
        theme.load_fonts()
        apply_look(app)
        w = MainWindow([path])
        w.show()
        app.processEvents()
        img = w.view.viewport().grab().toImage()
        inked = sum(1 for x in range(0, img.width(), 7) for y in range(0, img.height(), 7)
                    if img.pixelColor(x, y).lightness() < 100 and img.pixelColor(x, y) != QColor(theme.PANEL))
        from .pageview import find_in_page
        text = w.doc.pdf.getAllText(1)
        try:
            direct = len(find_in_page(w.doc.pdf, 1, "moon"))
        except Exception as e:  # noqa: BLE001 - reported
            direct = f"{type(e).__name__}: {e}"
        w.find_box.setText("Moon")
        w.find_next(True)
        result = {"version": __version__, "pages": w.view.page_count(), "inked": inked,
                  "matches": len(w.view.matches), "bookmarks": len(w.doc.outline),
                  "fonts": "Inter" in QFontDatabase.families(),
                  # what Find is built on, to tell which part fails if it does
                  "text_valid": text.isValid(), "text_chars": len(text.text()), "page_matches": direct,
                  "find_count": w.find_count.text()}
        w.close()
    except Exception as e:  # noqa: BLE001 - reported in the output
        result = {"error": f"{type(e).__name__}: {e}"}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
    return 0 if "pages" in result else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--version"]:
        from . import __version__
        print(__version__)
        return 0
    if argv[:1] == ["--selftest"] and len(argv) == 3:
        return selftest(argv[1], argv[2])
    if argv[:1] and argv[0] in ("--register", "--unregister"):
        from . import shell
        return shell.run(argv[0])
    files, page, new = parse(argv)
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from . import settings, theme
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setOrganizationName("Paragon")
    app.setApplicationName("PR7-R")
    if not new and hand_over(files, page):
        return 0
    theme.set_finish(settings.get("finish", "obsidian"))
    theme.load_fonts()
    from .main_window import MainWindow, apply_look
    apply_look(app)
    icon = os.path.join(os.path.dirname(__file__), "icons", "app.ico")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    w = MainWindow(files or None, page=page)
    w.show()
    if not new:
        listen(w)
    from . import update_ui
    update_ui.start(w)  # a check for updates, once a day
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
