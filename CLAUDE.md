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
uv run pytest tests/renderer/test_geometry.py::test_name   # run a single test
uv run basedpyright               # strict type check
uv run ruff check                 # lint the source and tests
```

The `dev` extra also carries `basedpyright` (configured in `pyproject.toml`'s `[tool.basedpyright]`, strict mode).

`tests/` mirrors the package layout:
`tests/akasha/`, `tests/renderer/` and `tests/gui/`,
alongside the flat `tests/test_models.py` and `tests/test_storage.py`.
Each of those three directories is a package (`__init__.py`) with its own `helpers.py`
for the helpers more than one of its test modules needs;
helpers used by a single file stay in that file.
There is no `tests/__init__.py`.

`tests/test_package_layout.py` guards this layout itself.
It is purely static (it walks the tree and parses sources with `ast`,
importing neither the package nor PySide6),
and it asserts the exact set of modules,
that sibling modules are reached by relative import,
that each facade's `__all__` only names things it binds,
and that no module has grown past a line-count tripwire.
Read it before moving or adding a module,
since it is the test that will fail.

Headless/CI test runs need an offscreen Qt platform and a sandbox-free QtWebEngine, since Akasha access goes through a real `QWebEnginePage`:

```bash
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox uv run pytest
```

`tests/akasha/conftest.py` and `tests/gui/conftest.py` each contain only those two
`os.environ.setdefault()` calls,
because they have to run before PySide6 is imported
and pytest imports a package's `conftest.py` before any of its test modules.
`tests/renderer/` has no `conftest.py`:
the renderer is Qt-free and its test modules share nothing but `helpers.py`,
so `uv run pytest tests/renderer` runs without the offscreen environment.
So do `tests/gui/test_lineup.py`, `tests/gui/test_placement_controller.py`
and `tests/gui/test_presets.py`,
because the modules they exercise construct no widget and need no display.
`tests/gui/test_history.py` is not among them:
`PlacementHistory` itself needs no display,
but the same module's `HistoryController` tests build a `QWidget` and a `QShortcut`.
Neither is `tests/gui/test_undo.py`,
which drives the same undo/redo through a real `MainWindow`
and therefore needs the offscreen platform throughout.
PySide6 still gets imported for those files
(reaching any `gui` submodule executes the package facade, which imports `MainWindow`),
so the Qt-free property is about not needing a display, not about the import graph.

Packaging (runs the test suite first, then builds a standalone package into `release/`):

```bash
packaging/build_linux.sh          # Linux tarball via PyInstaller
packaging/build_windows.ps1       # Windows package via PyInstaller
packaging/create_source_package.ps1  # clean source ZIP
```

Windows and Linux packages are built separately since native Qt binaries aren't portable across OSes.

## Architecture

The app is a small layered pipeline, one concern per module, all under `src/genshin_thumbnail_studio/`.
`models.py` and `storage.py` are single modules, small enough to read at a glance;
`akasha/`, `renderer/` and `gui/` are sub-packages.

Dependency order, which is also the order of the subsections below:
`models` depends on nothing in the package,
`akasha` and `renderer` depend on `models` only,
`storage` depends on `models` and `renderer`,
`gui` depends on all four,
and nothing depends on `gui`.
There are no cycles, inside a package or between them.

Each sub-package's `__init__.py` is a facade
that re-exports the package's public surface with an explicit `__all__`.
Callers outside a package import from the package
(`from ..renderer import max_offset`, `from ..akasha import AkashaWebClient`)
rather than reaching into its modules,
so the internal layout can change without touching anything outside;
modules inside a package import each other by relative import
(`from .geometry import panel_target_size`).
The renderer facade re-exports everything the pre-split flat `renderer.py` exposed,
including the cache dicts and their bounds,
so it is wider than a minimal public surface would be.
The tests are the deliberate exception to the rule:
they import the module under test directly
(`genshin_thumbnail_studio.renderer.cache`, `...gui.main_window`),
because that is where a `monkeypatch.setattr()` has to land to take effect.

### `models.py`

Plain dataclasses with no external dependencies: `Build` (a parsed Akasha character build), `Asset` (a `Build` plus downloaded local file paths), `Placement` (per-character position/zoom/color/flip in the layout), and `Project` (the full editable state: mode, UID, teams of `Placement`s). A `Placement`'s `offset_x`/`offset_y` are signed fractions of the panel size, zero meaning centered and positive meaning the portrait moves right/down; `flip` mirrors the character art horizontally. `Project.to_dict`/`from_dict` define the JSON project file format (`schemaVersion`, currently 3); `ensure_shape()` enforces the team/member counts for the given mode (2 teams x 4 for abyss, 3 teams x 4 for stygian). `Placement.from_dict()` reads known keys and defaults the missing ones, so optional additions like `flip` need no `schemaVersion` bump and stay readable in both directions.

### `storage.py`

`Project` JSON save/load, OS-appropriate app data dir resolution (overridable via `GENSHIN_THUMBNAIL_STUDIO_DATA_DIR`), and load/save of reusable placement presets (`placements.json`). It also migrates pre-v3 files and presets, whose placements stored an `fx`/`fy` focal point in source-art space, into the panel-relative offsets; that conversion needs render geometry, so `storage.py` imports `renderer` (through the facade, as `from . import renderer`).

### `akasha/`

All network and browser interaction with Akasha and Enka.

- `errors.py` — `AkashaError` and `StaleProfileError` (which carries the profile age and last-update time).
- `http.py` — the plain `urllib` side: `USER_AGENT`, `fetch_json()` and `download()`.
- `parsing.py` — turning Akasha's JSON into `Build`s: `parse_builds()`, `timestamp()`/`profile_age_minutes()`, `refinement()`, the element and rarity lookups, and the Enka URL reconstruction. `exact_art_url()` reconstructs the exact Enka asset stem (including costume/skin IDs) from the Akasha character icon URL — this is the part most likely to break if Akasha/Enka change their asset naming.
- `rarities.py` — `load_enka_rarities()` and its two distill helpers, over a local cache of Enka's `avatars.json`/`weapons.json` (`ENKA_RARITY_CACHE_MAX_AGE_SECONDS`).
- `client.py` — `AkashaWebClient`, which drives an offscreen `QWebEnginePage` (not plain HTTP) to load `akasha.cv` API endpoints and read back JSON, because Akasha requires a real browser context. Key flow: `load_profile()` checks profile freshness (`StaleProfileError` if the Akasha profile update is older than `max_age_minutes`) and returns parsed `Build`s; `refresh_profile()` can programmatically click Akasha's "Refresh builds" button and poll until the profile timestamp advances. `close()` releases the `QWebEnginePage` before its `QWebEngineProfile` in a fixed order (Qt does not do this automatically, since the profile passed to the page's constructor is not its Qt parent), spinning the event loop between the two so QtWebEngine's deferred cleanup completes before teardown proceeds.
- `assets.py` — `download_assets()` and its path helper, downloading and validating (dimension/format checks) character art and weapon icons into a local cache dir.

Import direction: `errors` imports nothing from the package; `http` and `parsing` import `errors`; `rarities` imports `http` and `parsing`; `client` imports `errors`, `http`, `parsing` and `rarities`; `assets` imports `errors` and `http`. `client.py` is the only module that touches Qt, so everything else in the package is testable without it.

### `renderer/`

Pure Pillow-based image compositing, no Qt or network dependency.

- `geometry.py` — the panel geometry and the reachable pan range: `BASE_W`/`BASE_H`, `LINE`/`CARD_BORDER`/`CARD_GAP`, `BACKGROUND_COLOR`, `STANDARD_ART_SIZE`, `PAN_OVERSCAN`, `panel_metrics()`, `panel_target_size()`, `panel_origin()`, `panel_polygon()`, `cover_scale()`, `scaled_size()`, `resized_art_size()`, `offset_limits()`, `zoom_offset_limits()` and `max_offset()`. `panel_metrics`/`panel_target_size` are the single source of the panel geometry; `zoom_offset_limits()` composes `cover_scale()`/`scaled_size()`/`offset_limits()` into the one formula for the reachable +/- offset per axis of a source size cover-fit into a target at a zoom, so it exists once instead of being computed inline everywhere it is needed; `max_offset()` is `zoom_offset_limits()` applied to a panel's own target size, and is what `cover_resize_offset()` clamps with by default, so the GUI sliders and the renderer cannot disagree. The cover fit (`scaled_size()`) scales both art axes by the same factor, so a zoom below 100% never stretches the portrait and instead leaves a transparent margin that the panel background and glow show through. `scaled_size()` and `offset_limits()` are helpers rather than part of the intended public surface, but carry no leading underscore, because basedpyright's strict mode rejects cross-module use of underscore-prefixed module-level names.
- `colors.py` — `ELEMENT_COLORS`, `RARITY_COLORS`, `rarity_color()`, `hex_to_rgba()` and `card_color()`.
- `coverage.py` — the antialiasing primitives Pillow's `ImageDraw` lacks: `GEOMETRY_SUPERSAMPLE`, `supersampled_coverage_for()`, `supersampled_coverage()`, `supersampled_box()` and `paint_through_coverage()`.
- `cache.py` — `CacheKey`, the seven bounded LRU caches with their `*_CACHE_MAX` bounds, the lock guarding them, `cache_get()`, `cache_put()` and `clear_render_cache()`.
- `art.py` — decoding, resizing and cropping the source art: `MAX_PLACEMENT_ZOOM`, `GLOW_ZOOM_FACTOR`, `glow_zoom()`, `art_pixel_size()`, `source_art()`, `cover_resize_offset()` and `panel_art()`. `glow_zoom()` is strictly proportional to the placement zoom (`zoom * GLOW_ZOOM_FACTOR`, with the factor currently `1.0`, i.e. equal to the portrait's own zoom), so the glow's framing tracks the portrait's at every zoom instead of freezing below a threshold, and covers the panel at both default zooms; `cover_resize_offset()` and `panel_art()` both take an optional `limits` that, when given, replaces the self-computed clamp, which is how the glow and the portrait are made to pan by the same panel-relative distance and stop at the same offset. `panel_art()` wraps `cover_resize_offset()` to honor `Placement.flip`; it crops at the negated horizontal offset and mirrors the panel-sized crop, which equals cropping mirrored source art at the original offset but leaves the shared, read-only `source_art()` cache untouched. Both the glow layer and the sharp portrait go through it so they cannot disagree about the mirroring.
- `panels.py` — one character panel end to end: `GLOW_DOWNSCALE`, `panel_background()`, `apply_panel_mask()`, `make_panel()`, `placeholder_panel()` and `add_card_borders()`. `make_panel()` computes the portrait's reachable offset range once (`zoom_offset_limits(art.size, target, member.zoom)`) and passes it as `limits` to both `panel_art()` calls, the glow one and the sharp-crop one, so the two layers clamp against the same range instead of each capping at its own, differently zoomed one.
- `badges.py` — the C/R and weapon badges: `find_font()` and its lock, `BadgeGeometry`, `badge_geometry()`, `badge_tile_origin()`, `badge_tile()` and `add_badges()`.
- `compose.py` — the whole canvas: `safe_name()`, `render_image()`, `render_preview()` and `export_project()`. `render_image()` builds the slanted-panel team layout (background glow, cover-fit character art panned by the placement offsets, shading, separators, C/R + weapon badges) at a given integer `scale`, then downsamples to 1280x720 for supersampled quality. `render_preview()` (scale 1) and `export_project()` (scale 2, writes PNGs) are the two entry points used by the GUI; both first call `Project.ensure_shape()`. `compose.py` reaches `make_panel()`/`placeholder_panel()` through `from . import panels`, deliberately, rather than binding them into its own globals: that is what lets the panel-cache tests patch them on `renderer.panels` and intercept a render already in flight.

Import direction: `cache`, `geometry`, `colors` and `coverage` import nothing from the package; `art` imports `geometry` and `cache`; `panels` imports `geometry`, `colors`, `coverage`, `cache` and `art`; `badges` imports `colors`, `coverage` and `cache`; `compose` imports `geometry`, `colors`, `cache`, `panels` and `badges`.

### `gui/`

The PySide6 desktop application. It wires user input (UID entry, mode selection, drag/wheel/slider placement editing, flip toggle) to `akasha/` for fetching, `renderer/` for live preview and export, and `storage.py` for persistence.

- `app.py` — `run()`, the entry point behind `pyproject.toml`'s `gui-scripts`, `__main__.py` and `launch.py`.
- `style.py` — `MAIN_STYLESHEET`, the whole application's QSS, applied once to the main window.
- `main_window.py` — `RENDER_THROTTLE_MS`, `RESOLUTION_OPTIONS` and `MainWindow`. At 744 lines this is still the largest module, and the one most of `tests/gui/` exercises: its remaining flows (`load_profile`, `open_project`, `export`) are Qt-bound throughout, so they were not decomposed further beyond moving their blocking dialogs to `dialogs.py`. `MainWindow.closeEvent` first confirms discarding any unsaved project changes, through the same `dialogs.confirm_discard_changes()` `_mode_changed` uses before replacing the project, then calls `AkashaWebClient.close()` during shutdown so the page/profile teardown order is respected before the window closes. The window owns a `HistoryController` (`self._history`, created right after `self._placement`) and snapshots through it: debounced (`schedule()`) from the continuous edits `_placement_slider_changed`, `drag_placement`, `change_zoom`, `_flip_toggled` and the per-keystroke `_member_changed`; immediate (`commit_now()`) from the discrete `reset_placement`, from `_on_slot_drag_ended`, and at the end of `_generate_preview_from_builds`, where applying the stored presets reframes every member outside any edit handler; and history-clearing (`reset()`) in `_mode_changed` and at both of `open_project`'s exits, since both replace `self.project` wholesale and an older snapshot would let `Ctrl+Z` resurrect a lineup from a different document. `_history_restored()` is the callback the controller invokes after a restore: it rebuilds the team fields, syncs the controls, re-saves the selected character's preset so `PresetStore` and the visible framing do not disagree, and schedules a render. `reorder_slots()` moves a `Placement` from one `(team, slot)` position to another by insert/shift over the flattened, team-major sequence of all slots, replacing the pairwise swap the feature used to do; `_on_slot_drag_started`, `_on_slot_drag_hover` and `_on_slot_drag_ended` connect to `TeamSlotWidget`'s three drag signals and call `reorder_slots()` once per slot the drag passes over, so the reorder happens live rather than only on drop. `_on_slot_drag_started` deep-copies `self.project.teams` into `self._drag_snapshot`; if the drag ends without a drop, `_on_slot_drag_ended` restores that snapshot, reverting every live reorder step of the gesture back to the arrangement that existed when the drag began. Those live steps are the one place `reorder_slots()` snapshots nothing at all (it checks `self._drag_position`), so a whole drag-and-drop is a single undo step that `_on_slot_drag_ended` commits; after a cancelled drag its restore has already put the teams back, which makes that same commit a no-op. Nothing may be *scheduled* mid-gesture either, which is why `_on_slot_drag_started` calls `commit_now()` to settle any edit still pending from before the drag: a debounce firing while the user rests over a slot would snapshot a half-finished arrangement, and a cancelled drag would then leave the reorder it just reverted one `Ctrl+Z` away.
- `dialogs.py` — the blocking dialogs the window puts up, as free functions taking the parent widget: `confirm_discard_changes()`, `choose_stale_profile_action()`, `confirm_cache_refresh()`, `show_error()`, `show_export_finished()`, `ask_lineup_text()` and `ask_export_target()`. They return the user's choice rather than acting on it (`confirm_discard_changes()` takes the dirty check and the save as callables), so nothing here imports `MainWindow` and there is no cycle. This is where the `QMessageBox`/`QInputDialog` construction lives, and therefore what the gui tests monkeypatch (`monkeypatch.setattr(dialogs, "QMessageBox", ...)`); the `QFileDialog` calls in `save_project`/`open_project` stayed in the window.
- `state.py` — the `EditorState` Protocol (`project`, `builds`, `assets`), which `MainWindow` satisfies structurally.
- `placement.py` — `MIN_ZOOM`, `MAX_ZOOM` and `PlacementController`: the drag, wheel, slider and reset math (`offset_bounds()`, `pan()`, `zoom_by()`, `reset()`). `MAX_ZOOM` *is* the renderer's `MAX_PLACEMENT_ZOOM`, not a copy of its value, because the renderer sizes its cached working copy of the source art for exactly that ceiling; a placement zoomed past it would be upsampled.
- `presets.py` — `preset_key()` (mode plus the costume id, build id or casefolded name, in that fallback order) and `PresetStore`, the reusable per-character framing presets on top of `storage.load_presets`/`save_presets`.
- `preview.py` — `PreviewWidget`, the canvas that renders the pixmap and emits selection, drag and zoom signals.
- `team_slots.py` — `SLOT_MIME_TYPE`, `TeamSlotWidget` and its private drag handle. `TeamSlotWidget` emits three signals across a drag gesture, `drag_started`, `drag_hover` and `drag_ended`, which let `MainWindow` reorder the team list live while the drag is still in progress, rather than only once the mouse button is released.
- `render_job.py` — `RenderJobSignals` and `RenderJob`, which renders a `Project` snapshot on a `QThreadPool` worker.
- `lineup.py` — `parse_lineup()`, splitting pasted lineup text into character names.
- `history.py` — `HISTORY_LIMIT`, `HISTORY_DEBOUNCE_MS`, `PlacementHistory` and `HistoryController`. `PlacementHistory` is the Qt-free bounded undo/redo history over the teams of `Placement`s. A state is a deep copy of `Project.teams`, so it carries every member's name, framing, color and order; the rest of the `Project` (mode, uid, output settings, active team) is deliberately excluded, since undoing must not switch the mode and thereby discard all teams. Every state stored or handed out is deep-copied, so a caller cannot reach a stored state through the live `Placement` objects, and `commit()` is a no-op returning `False` when the teams equal the current state. `HistoryController` is the editor-facing half: `schedule()` restarts a single-shot `QTimer` at `HISTORY_DEBOUNCE_MS` (600 ms), a debounce rather than the throttle `MainWindow.schedule_render()` is, so a whole drag or slider sweep becomes one undo step; `commit_now()` snapshots immediately; `reset()` re-seeds the baseline; `undo()`/`redo()` restore a state onto `state.project.teams` and call the `on_restored` callback the window passes in, then `replace_current()` the result: `_history_restored()` runs `_sync_controls()`, which quantizes every offset to per-mille, and without recording that normalized form the next `commit_now()` would read the quantization as a fresh edit and truncate the redo tail. It installs `Ctrl+Z` (undo), `Ctrl+Y` and `Ctrl+Shift+Z` (redo) as `QShortcut`s on its parent widget, and since those window-level shortcuts are dispatched before a focused `QLineEdit` sees the key, `undo()`/`redo()` first check `QApplication.focusWidget()` and delegate to that widget's own undo stack when it is one — so text fields, including the editable team combos, keep their own undo. Like the other collaborators it reads `state.project` freshly on every call.

`placement.py`, `presets.py`, `state.py` and `lineup.py` are Qt-free and unit-testable on their own; so is `history.py`'s `PlacementHistory`, though `HistoryController` in the same module is Qt-bound, as is all of `dialogs.py`. `PlacementController` and `PresetStore` read the window's `project`/`builds`/`assets` through `EditorState` on *every* call instead of capturing them at construction time, because `_mode_changed`, `open_project`, `load_profile`, `_generate_preview_from_builds` and `_member_changed` all replace those attributes wholesale; a captured reference would go stale, and a stale `assets` would silently fall back to `STANDARD_ART_SIZE` and compute the wrong offset bounds.

Import direction: `lineup`, `style`, `state` and `dialogs` import nothing from the package; `placement`, `presets` and `history` import `state` (`history` also reaches `Placement` through `..models`); `preview`, `team_slots` and `render_job` import nothing from the package (`render_job` reaches the renderer through `..renderer`); `main_window` imports every sibling except `state`, which it satisfies structurally rather than importing, and reaches `dialogs` as a module (`from . import dialogs`) so the dialog constructors stay patchable in one place; `app` imports `main_window`. `TeamSlotWidget`'s three drag signals and the `_on_slot_drag_*` handlers that consume them are new signals and methods on classes already listed here, not a new module or dependency, so they leave this import direction unchanged.

Data flow: UID entered in GUI → `AkashaWebClient.load_profile` → `Build` list → `download_assets` → `Asset` dict (keyed by casefolded character name) → `render_preview`/`export_project` consume `Project.teams` (list of `Placement`) + the `Asset` dict to produce images. `Placement.name` is the join key back to the `Asset` dict, so a `Project` file only encodes placements/colors, not the fetched art — re-opening a project requires re-fetching from Akasha.
