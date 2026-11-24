"""Check a real install of PR7-R-Setup.exe (CI, Windows): python tools/verify_install.py installed|uninstalled

`installed` runs the installed PR7-R.exe offscreen on a real PDF (--selftest) and checks what it read and drew, so
the frozen program is shown to start with Qt, QtPdf (PDFium), its plugins and the Inter fonts; it also checks the
"Open with" and Default apps registration. `uninstalled` checks all of it is gone."""
import json
import os
import subprocess
import sys
import tempfile
import time
import winreg
from pathlib import Path

HKCU = winreg.HKEY_CURRENT_USER
APP = Path(os.environ["LOCALAPPDATA"]) / "Programs" / "PR7-R"
SHORTCUT = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Paragon PR7-R.lnk"
UNINSTALL = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{1BC53F2C-70E7-45EA-B97E-FC9294E87FC3}_is1"
PROGID = r"Software\Classes\Paragon.PR7R.PDF"


def value(path, name=""):
    try:
        with winreg.OpenKey(HKCU, path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def check(ok, what, p):
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        p.append(what)


def installed():
    p = []
    exe = APP / "PR7-R.exe"
    for f in (exe, APP / "unins000.exe", APP / "_internal" / "pr7r" / "fonts" / "Inter-Regular.ttf",
              APP / "_internal" / "pr7r" / "icons" / "app.ico"):
        check(f.is_file(), f"file {f}", p)
    check(SHORTCUT.is_file(), "Start menu shortcut", p)
    check(value(UNINSTALL, "DisplayName") == "Paragon PR7-R", "Installed apps entry", p)
    cmd = value(PROGID + r"\shell\open\command") or ""
    check(str(exe).lower() in cmd.lower() and cmd.endswith('"%1"'), f"PDF open command: {cmd}", p)
    check(value(r"Software\Classes\.pdf\OpenWithProgids", "Paragon.PR7R.PDF") is not None, "Open with lists PR7-R", p)
    check(value(r"Software\RegisteredApplications", "Paragon PR7-R") == r"Software\Paragon\PR7-R\Capabilities",
          "Default apps lists PR7-R", p)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication(["x", "-platform", "offscreen"])
    import sample_pdf
    with tempfile.TemporaryDirectory() as d:
        pdf = sample_pdf.book(Path(d) / "Night Skies.pdf")
        out = Path(d) / "out.json"
        subprocess.run([str(exe), "--selftest", str(pdf), str(out)], timeout=120, check=False)
        got = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        check(got.get("pages") == 19 and got.get("inked", 0) > 50 and got.get("matches", 0) > 10
              and got.get("bookmarks") == 25 and got.get("fonts") is True, f"PR7-R.exe reads and draws a PDF ({got})", p)
    del app
    return p


def uninstalled():
    deadline = time.time() + 60
    while True:
        p = []
        check(not (APP / "PR7-R.exe").exists(), "program files removed", p)
        check(not SHORTCUT.exists(), "Start menu shortcut removed", p)
        check(value(UNINSTALL, "DisplayName") is None, "Installed apps entry removed", p)
        check(value(PROGID) is None, "PDF type removed", p)
        check(value(r"Software\RegisteredApplications", "Paragon PR7-R") is None, "Default apps entry removed", p)
        if not p or time.time() > deadline:
            return p
        print("... waiting for the uninstaller to finish")
        time.sleep(3)


if __name__ == "__main__":
    problems = {"installed": installed, "uninstalled": uninstalled}[sys.argv[1]]()
    print("\nALL OK" if not problems else f"\n{len(problems)} problem(s)")
    sys.exit(1 if problems else 0)
