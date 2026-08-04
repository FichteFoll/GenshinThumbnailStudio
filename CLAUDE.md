# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Standalone PySide6 desktop app that builds 1280x720 Genshin Impact team thumbnails (Spiral Abyss or Stygian Onslaught) from a player's public Akasha profile, without any AI image generation. Fetches character/weapon art via Akasha/Enka, lets the user drag-position each character in a preview, and exports supersampled PNGs.

## Commands

Dependency management uses [uv](https://docs.astral.sh/uv/).

```bash
uv run genshin-thumbnail-studio   # run the app (auto-installs deps on first use)
uv sync --extra dev               # install dev deps (pytest, PyInstaller)
uv run pytest                     # run the test suite
uv run pytest tests/test_renderer.py::test_name   # run a single test
```

Headless/CI test runs need an offscreen Qt platform and a sandbox-free QtWebEngine, since Akasha access goes through a real `QWebEnginePage`:

```bash
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox uv run pytest
```

Packaging (runs the test suite first, then builds a standalone package into `release/`):

```bash
packaging/build_linux.sh          # Linux tarball via PyInstaller
packaging/build_windows.ps1       # Windows package via PyInstaller
packaging/create_source_package.ps1  # clean source ZIP
```

Windows and Linux packages are built separately since native Qt binaries aren't portable across OSes.

## Architecture

The app is a small layered pipeline, one module per concern, all under `src/genshin_thumbnail_studio/`:

- **`models.py`** — plain dataclasses with no external dependencies: `Build` (a parsed Akasha character build), `Asset` (a `Build` plus downloaded local file paths), `Placement` (per-character position/zoom/color/flip in the layout), and `Project` (the full editable state: mode, UID, teams of `Placement`s). A `Placement`'s `offset_x`/`offset_y` are signed fractions of the panel size, zero meaning centered and positive meaning the portrait moves right/down; `flip` mirrors the character art horizontally. `Project.to_dict`/`from_dict` define the JSON project file format (`schemaVersion`, currently 3); `ensure_shape()` enforces the team/member counts for the given mode (2 teams x 4 for abyss, 3 teams x 4 for stygian). `Placement.from_dict()` reads known keys and defaults the missing ones, so optional additions like `flip` need no `schemaVersion` bump and stay readable in both directions.
- **`akasha.py`** — all network/browser interaction. `AkashaWebClient` drives an offscreen `QWebEnginePage` (not plain HTTP) to load `akasha.cv` API endpoints and read back JSON, because Akasha requires a real browser context. Key flow: `load_profile()` checks profile freshness (`StaleProfileError` if the Akasha profile update is older than `max_age_minutes`) and returns parsed `Build`s; `refresh_profile()` can programmatically click Akasha's "Refresh builds" button and poll until the profile timestamp advances. `exact_art_url()` reconstructs the exact Enka asset stem (including costume/skin IDs) from the Akasha character icon URL — this is the part most likely to break if Akasha/Enka change their asset naming. `download_assets()` downloads and validates (dimension/format checks) character art and weapon icons into a local cache dir.
- **`renderer.py`** — pure Pillow-based image compositing, no Qt/network dependency. `render_image()` builds the slanted-panel team layout (background glow, cover-fit character art panned by the placement offsets, shading, separators, C/R + weapon badges) at a given integer `scale`, then downsamples to 1280x720 for supersampled quality. `panel_metrics`/`panel_target_size` are the single source of the panel geometry; `max_offset()` exposes the reachable offset range (cover-fit slack plus `PAN_OVERSCAN`) that `cover_resize_offset()` clamps with, so the GUI sliders and the renderer cannot disagree. `panel_art()` wraps `cover_resize_offset()` to honor `Placement.flip`; it crops at the negated horizontal offset and mirrors the panel-sized crop, which equals cropping mirrored source art at the original offset but leaves the shared, read-only `source_art()` cache untouched. Both the glow layer and the sharp portrait go through it so they cannot disagree about the mirroring. `render_preview()` (scale 1) and `export_project()` (scale 2, writes PNGs) are the two entry points used by the GUI; both first call `Project.ensure_shape()`.
- **`storage.py`** — `Project` JSON save/load, OS-appropriate app data dir resolution (overridable via `GENSHIN_THUMBNAIL_STUDIO_DATA_DIR`), and load/save of reusable placement presets (`placements.json`). It also migrates pre-v3 files and presets, whose placements stored an `fx`/`fy` focal point in source-art space, into the panel-relative offsets; that conversion needs render geometry, so `storage.py` imports `renderer`.
- **`gui.py`** — the PySide6 `QMainWindow` and `PreviewWidget`. Wires user input (UID entry, mode selection, drag/wheel/slider placement editing, flip toggle) to `akasha.py` for fetching, `renderer.py` for live preview and export, and `storage.py` for persistence. This is the largest module and the one most tests exercise via `test_gui_smoke.py`.

Data flow: UID entered in GUI → `AkashaWebClient.load_profile` → `Build` list → `download_assets` → `Asset` dict (keyed by casefolded character name) → `render_preview`/`export_project` consume `Project.teams` (list of `Placement`) + the `Asset` dict to produce images. `Placement.name` is the join key back to the `Asset` dict, so a `Project` file only encodes placements/colors, not the fetched art — re-opening a project requires re-fetching from Akasha.
