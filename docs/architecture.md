# Architecture

Structural reference: what each module holds,
which module may import which,
and the data model facts that outlive any single module.
The reasoning behind the non-obvious choices lives in [design-notes.md](design-notes.md).

## Layering

Everything is under `src/genshin_thumbnail_studio/`.
`models.py` and `storage.py` are single modules;
`akasha/`, `renderer/` and `gui/` are sub-packages.

Dependency order:
`models` depends on nothing in the package,
`akasha` and `renderer` depend on `models` only,
`storage` depends on `models` and `renderer`,
`gui` depends on all four,
and nothing depends on `gui`.
There are no cycles, inside a package or between them.

Each sub-package's `__init__.py` is a facade
that re-exports the package's public surface with an explicit `__all__`.
Callers outside a package import from the package
(`from ..renderer import max_offset`, `from ..akasha import AkashaWebClient`);
modules inside a package import each other by relative import
(`from .geometry import panel_target_size`).
The renderer facade is wider than a minimal public surface,
re-exporting the cache dicts and their bounds as well.

The tests are the deliberate exception:
they import the module under test directly
(`genshin_thumbnail_studio.renderer.cache`, `...gui.main_window`),
because that is where a `monkeypatch.setattr()` has to land to take effect.

## Data model

`models.py` holds plain dataclasses with no external dependencies:

- `Build` — a parsed Akasha character build.
- `Asset` — a `Build` plus downloaded local file paths.
- `Placement` — per-character position/zoom/color/flip in the layout.
- `Project` — the full editable state: mode, UID, teams of `Placement`s.

Facts that the rest of the app depends on:

- `Placement.offset_x`/`offset_y` are signed fractions of the panel size,
  zero meaning centered,
  positive meaning the portrait moves right/down.
  `flip` mirrors the character art horizontally.
- `Placement.name` is the join key back to the `Asset` dict.
  A `Project` file therefore encodes placements and colors, not the fetched art,
  so re-opening a project requires re-fetching from Akasha.
- `Project.to_dict`/`from_dict` define the JSON project file format,
  `schemaVersion` currently 3.
  `storage.py` migrates pre-v3 files and presets,
  whose placements stored an `fx`/`fy` focal point in source-art space,
  into the panel-relative offsets.
- `Placement.from_dict()` reads known keys and defaults the missing ones,
  so optional additions like `flip` need no `schemaVersion` bump
  and stay readable in both directions.
- `Project.ensure_shape()` enforces the team/member counts for the mode:
  2 teams x 4 for abyss, 3 teams x 4 for stygian.

## `storage.py`

`Project` JSON save/load,
OS-appropriate app data dir resolution
(overridable via `GENSHIN_THUMBNAIL_STUDIO_DATA_DIR`),
load/save of reusable placement presets (`placements.json`),
and the pre-v3 migration above.
That migration needs render geometry,
which is why `storage.py` imports `renderer` (as `from . import renderer`).

## `akasha/`

All network and browser interaction with Akasha and Enka.

- `errors.py` — `AkashaError` and `StaleProfileError`
  (which carries the profile age and last-update time).
- `http.py` — the plain `urllib` side: `USER_AGENT`, `fetch_json()`, `download()`.
- `parsing.py` — Akasha JSON into `Build`s:
  `parse_builds()`, `timestamp()`/`profile_age_minutes()`, `refinement()`,
  the element and rarity lookups,
  and `exact_art_url()` for the Enka asset stem.
- `rarities.py` — `load_enka_rarities()` over a local cache of Enka's
  `avatars.json`/`weapons.json` (`ENKA_RARITY_CACHE_MAX_AGE_SECONDS`).
- `client.py` — `AkashaWebClient`:
  `load_profile()` checks profile freshness
  (`StaleProfileError` past `max_age_minutes`) and returns parsed `Build`s;
  `refresh_profile()` clicks Akasha's "Refresh builds" and polls for a newer timestamp;
  `close()` tears the page and profile down in order.
- `assets.py` — `download_assets()`,
  downloading and validating (dimension/format checks) character art and weapon icons
  into a local cache dir.

Import direction: `errors` imports nothing from the package;
`http` and `parsing` import `errors`;
`rarities` imports `http` and `parsing`;
`client` imports `errors`, `http`, `parsing` and `rarities`;
`assets` imports `errors` and `http`.
`client.py` is the only module that touches Qt,
so everything else in the package is testable without it.

## `renderer/`

Pure Pillow-based image compositing, no Qt or network dependency.

- `geometry.py` — panel geometry and the reachable pan range:
  `BASE_W`/`BASE_H`, `LINE`/`CARD_BORDER`/`CARD_GAP`, `BACKGROUND_COLOR`,
  `STANDARD_ART_SIZE`, `PAN_OVERSCAN`,
  `panel_metrics()`, `panel_target_size()`, `panel_origin()`, `panel_polygon()`,
  `cover_scale()`, `scaled_size()`, `resized_art_size()`,
  `offset_limits()`, `zoom_offset_limits()`, `max_offset()`.
- `colors.py` — the element and rarity palettes and the card color lookup.
- `coverage.py` — the antialiasing primitives Pillow's `ImageDraw` lacks,
  around `GEOMETRY_SUPERSAMPLE`.
- `cache.py` — `CacheKey`, the seven bounded LRU caches with their `*_CACHE_MAX` bounds,
  the lock guarding them, `cache_get()`, `cache_put()`, `clear_render_cache()`.
- `art.py` — decoding, resizing and cropping the source art:
  `MAX_PLACEMENT_ZOOM`, `GLOW_ZOOM_FACTOR`, `glow_zoom()`, `art_pixel_size()`,
  `source_art()`, `cover_resize_offset()`, `panel_art()`.
- `panels.py` — one character panel end to end:
  `GLOW_DOWNSCALE`, `panel_background()`, `apply_panel_mask()`, `make_panel()`,
  `placeholder_panel()`, `add_card_borders()`.
- `badges.py` — the C/R and weapon badges: `find_font()`, `BadgeGeometry`, `add_badges()`.
- `compose.py` — the whole canvas:
  `render_image()` builds the slanted-panel team layout at a given integer `scale`
  and downsamples to 1280x720;
  `render_preview()` (scale 1) and `export_project()` (scale 2, writes PNGs)
  are the GUI's two entry points and both first call `Project.ensure_shape()`.

Import direction: `cache`, `geometry`, `colors` and `coverage` import nothing from the package;
`art` imports `geometry` and `cache`;
`panels` imports `geometry`, `colors`, `coverage`, `cache` and `art`;
`badges` imports `colors`, `coverage` and `cache`;
`compose` imports `geometry`, `colors`, `cache`, `panels` and `badges`.

## `gui/`

The PySide6 desktop application.
It wires user input (UID entry, mode selection, drag/wheel/slider placement editing, flip toggle)
to `akasha/` for fetching,
`renderer/` for live preview and export,
and `storage.py` for persistence.

- `app.py` — `run()`, the entry point behind `pyproject.toml`'s `gui-scripts`,
  `__main__.py` and `launch.py`.
- `style.py` — `MAIN_STYLESHEET`, the whole application's QSS,
  applied once to the main window.
- `main_window.py` — `RENDER_THROTTLE_MS`, `RESOLUTION_OPTIONS` and `MainWindow`:
  profile loading, placement editing, the render throttle,
  the four project `QAction`s (`Ctrl+O`, `Ctrl+S`, `Ctrl+Shift+S`, `Ctrl+E`),
  team-slot reordering, and the close sequence.
  The largest module by far.
- `dialogs.py` — the blocking dialogs as free functions taking the parent widget:
  `confirm_discard_changes()`, `choose_stale_profile_action()`, `confirm_cache_refresh()`,
  `show_error()`, `show_export_finished()`, `ask_lineup_text()`, `ask_export_target()`.
  They return the user's choice rather than acting on it.
- `project_io.py` — `save_project()`, `save_project_as()`, `open_project()`, `export()`
  as free functions, plus the `ProjectEditor` Protocol they take.
  `MainWindow` keeps thin same-named methods delegating here,
  so every caller and test still goes through the window;
  these functions are deliberately not in `gui/__init__.py`'s `__all__`.
- `state.py` — the `EditorState` Protocol (`project`, `builds`, `assets`),
  which `MainWindow` satisfies structurally. Must stay Qt-free.
- `placement.py` — `MIN_ZOOM`, `MAX_ZOOM` and `PlacementController`:
  `offset_bounds()`, `pan()`, `zoom_by()`, `reset()`.
- `presets.py` — `preset_key()`
  (mode plus the costume id, build id or casefolded name, in that fallback order)
  and `PresetStore` on top of `storage.load_presets`/`save_presets`.
- `preview.py` — `PreviewWidget`, the canvas that renders the pixmap
  and emits selection, drag and zoom signals.
  `set_context(mode, active_team, selected, filled)` tells it which slots have art.
- `team_slots.py` — `SLOT_MIME_TYPE` and `TeamSlotWidget`,
  which emits `drag_started`, `drag_hover` and `drag_ended` across a drag gesture.
- `render_job.py` — `RenderJobSignals` and `RenderJob`,
  rendering a `Project` snapshot on a `QThreadPool` worker.
- `asset_loader.py` — `AssetJobSignals`, `AssetJob` and `AssetLoader`,
  the background character-art downloads.
  `AssetLoader.ensure()` starts one `AssetJob` for the named members
  that resolve in `builds` but are neither downloaded nor in flight,
  and emits `progress`, `asset_ready` and `failed`.
- `lineup.py` — `parse_lineup()`, splitting pasted lineup text into character names.
- `history.py` — `HISTORY_LIMIT`, `HISTORY_DEBOUNCE_MS`,
  `PlacementHistory` (Qt-free bounded undo/redo over the teams of `Placement`s)
  and `HistoryController` (`schedule()`, `commit_now()`, `reset()`, `undo()`, `redo()`,
  plus the `Ctrl+Z`/`Ctrl+Y`/`Ctrl+Shift+Z` shortcuts).

Qt-free and unit-testable on their own:
`placement.py`, `presets.py`, `state.py`, `lineup.py`,
and `history.py`'s `PlacementHistory`.
Qt-bound: everything else, including `history.py`'s `HistoryController`.

Import direction: `lineup`, `style`, `state` and `dialogs` import nothing from the package;
`placement`, `presets`, `history` and `asset_loader` import `state`
(`history` also reaches `Placement` through `..models`,
and `asset_loader` reaches `download_assets` through `..akasha`);
`preview`, `team_slots` and `render_job` import nothing from the package
(`render_job` reaches the renderer through `..renderer`);
`project_io` imports `state`, `dialogs`, `history` and `asset_loader`,
and reaches `..models`, `..storage` and `..renderer` outside the package;
`main_window` imports every sibling except `state`,
which it satisfies structurally rather than importing,
and reaches `dialogs` and `project_io` as modules (`from . import dialogs, project_io`);
`app` imports `main_window`.

## Data flow

UID entered in GUI ->
`AkashaWebClient.load_profile` ->
`Build` list ->
`AssetLoader.ensure()` ->
`download_assets` on a worker thread ->
one `asset_ready` per character into the `Asset` dict (keyed by casefolded character name) ->
`render_preview`/`export_project` consume `Project.teams` plus the `Asset` dict
to produce images.

Nothing waits for that download:
the preview renders continuously,
with a `placeholder_panel()` wherever the `Asset` has not arrived yet.
