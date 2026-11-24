# Paragon PR7-R: notes for Claude

**Paragon PR7-R** is the owner's personal PDF reader: Python (**PySide6** + **QtPdf**, i.e. PDFium) that **works the
way SumatraPDF works**, in the Paragon family look (the PR7 plugins, Paragon Photo, PR7-Z `ARYEZ/Paragon-PR7-Z`,
PR7-W, PR7-L, PR7-F, PR7-E `ARYEZ/Paragon-PR7-E`). Windows 10/11 x64 is the target; it runs on Linux for tests. The
owner writes Python; explain the why of changes.

## How it's built

- `pr7r/layout.py` (no Qt): where pages go. `rows` (single / facing / book: the cover alone on the right),
  `scale_for` (fit page, fit width, a percent; 100% = real size at the screen's dpi), `Layout.place` (continuous or
  one spread), `current` (the page covering most of the window), `to_page` / `from_page` (view pixels <-> page
  points, all four rotations). MARGIN = GAP so a page scrolled to the top hides the one above.
- `pr7r/pageview.py`: **our own page widget, not QPdfView** (QPdfView paints search marks blue / cyan, which the
  family forbids, and has no facing / book / rotation / presentation). QPdfDocument.render per page (cached; PDFium
  leaves the paper transparent, so white is painted under it; above WHOLE_PAGE_LIMIT only the visible part is
  rendered). Find = `find_in_page` (getAllText + getSelectionAtIndex, `line_boxes` joins letter boxes per line).
  Selection uses `_chars` (one getSelectionAtIndex call gives boxes for letters only, matched to the non-space
  characters) and `_index_at` (nearest letter off the text), so drags into the margin work. Links via QPdfLinkModel
  (`rowCount(QModelIndex())`); Back / Forward stacks of `position()` = (page, top in points).
- `pr7r/history.py` (no Qt): Sumatra's file history in `%APPDATA%\Paragon\PR7-R\history.json` (**PR7R_DATA**
  overrides; tests always set it): open counts, the page / zoom / layout / rotation per document, Frequently read,
  favorites. Thumbnails for the start page are PNGs in `<data>/thumbnails`.
- `pr7r/main_window.py`: menus via `_act(..., key=)` into `actions_by_key`; `Doc` per tab (path, QPdfDocument,
  PageView, outline from QPdfBookmarkModel); `Home` (start page); `_sync` sets toolbar and menus from the current
  view; `_ask(kind)` for every dialog (tests: `window.answers`); `print_pages` renders to the printer;
  `PropertiesDialog`, `OptionsDialog`. QFileSystemWatcher reloads a changed file at the same place.
- `pr7r/app.py`: one window per user: `hand_over` sends a later launch's files over a QLocalSocket (`server_name`,
  hashed user name), `listen` takes them. `-page N`, `-new-window`, `--register` / `--unregister` (shell.py: Open with,
  Capabilities, RegisteredApplications, HKCU only), `--selftest PDF OUT.json` (CI runs it on the installed exe).
- `tools/sample_pdf.py`: test PDFs written by QPdfWriter (`field_guide`, `short`); `book` adds bookmarks, links and a
  password with **pypdf** (a test-only dependency).
- Installer `installer/pr7r.iss` (Inno Setup 6, per user, AppId {1BC53F2C-70E7-45EA-B97E-FC9294E87FC3} permanent);
  CI installs it, runs `tools/verify_install.py installed`, uninstalls, `... uninstalled`. Spec: file details, no
  UPX, PyInstaller's bootloader built in CI, Defender scan (PR7-F's false-positive fix).
- Updates: `pr7r/updates.py` (no Qt; GitHub's public releases/latest, User-Agent names only the app, installer asset `PR7-R-Setup-*.exe`, run with /SILENT /relaunch=1) and `update_ui.py` (once-a-day check from app.py, the menu's Check for Updates, UpdateDialog; settings updates/auto|last|skip; `notify` for tests). The installer's [Code] Relaunch starts PR7-R again only for /relaunch=1. Same files in every family app (PR7-W's update_ui imports PyQt6): keep them in step. `family.py`: the other family apps by their permanent AppIds (uninstall InstallLocation).

## The look (family rules)

- Theme is PR7-E's (OBSIDIAN + AURORA via `theme.set_finish`; `main_window.stylesheet()` adds tabs and bookmarks).
  Colours: the family's only (hues ~318 -> 0 -> 42 deg, pearl and onyx greys), find and selection marks included;
  Inter; labels UPPER CASE; file names keep their case.
- The PR7-R mark: PR7 `Logo.cpp` geometry plus an R (`widgets.R_BOWL/R_COUNTER/R_LEG`); icon by
  `tools/make_icon.py`, wizard art by `tools/make_installer_art.py`. Check visuals with
  `QT_SCALE_FACTOR=2 python tools/screenshots.py OUT`.

## Rules

- Behaviour questions: do what SumatraPDF does (menus, shortcuts, defaults).
- Tests: `python -m pytest` (offscreen) on real PDFs from `tools/sample_pdf.py`. Never the real settings or data
  folder (conftest), or, outside CI, the registry.
- Releases: bump `__version__` in `pr7r/__init__.py`, add a `## x.y.z` section to CHANGELOG.md; Run workflow with
  "Publish a release" (or a `v*` tag) publishes.
