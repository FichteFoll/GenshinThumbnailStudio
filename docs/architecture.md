# Architecture

Structural reference: what each module holds,
which module may import which,
and the data model facts that outlive any single module.
The reasoning behind the non-obvious choices lives in [design-notes.md](design-notes.md).

## Layering

Everything is under `src/genshin_thumbnail_studio/`.
`models.py` and `storage.py` are single modules;
`enka/`, `renderer/` and `gui/` are sub-packages.

Dependency order:
`models` depends on nothing in the package,
`enka` and `renderer` depend on `models` only,
`storage` depends on `models` and `renderer`,
`gui` depends on all four,
and nothing depends on `gui`.
There are no cycles, inside a package or between them.

Each sub-package's `__init__.py` is a facade
that re-exports the package's public surface with an explicit `__all__`.
Callers outside a package import from the package
(`from ..renderer import max_offset`, `from ..enka import EnkaClient`);
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

- `Build` — a parsed Enka character build,
  either the live showcase build or one of a profile's saved builds.
  It also resolves its own cached files: `art_path(root)` and `weapon_path(root)`
  derive the character art and weapon icon paths under an art root
  from nothing but the build's own name and URLs.
- `Placement` — per-character position/zoom/color/flip in the layout,
  plus the `Build` it was framed with.
- `Profile` — the result of loading an identifier: its UID and username,
  the `dict[str, list[Build]]` of builds keyed by casefolded character name,
  and when it was fetched.
- `Project` — the full editable state: mode, UID, profile name, teams of `Placement`s.

Facts that the rest of the app depends on:

- `Placement.offset_x`/`offset_y` are signed fractions of the panel size,
  zero meaning centered,
  positive meaning the portrait moves right/down.
  `flip` mirrors the character art horizontally.
- `Placement.build` is the single source of truth for a slot's art,
  and the only join key a slot needs: `Placement.name` only names the character.
  A `Project` file therefore encodes placements, colors and the build's details,
  not the fetched art,
  so re-opening a project requires re-fetching from Enka.
  `Build.details()` is the four user-visible fields
  (costume id, weapon name, constellation, refinement)
  a project's snapshotted build is compared against a live one by.
- `CUSTOM_BUILD_NAME = "Custom"` is the name a build carries
  once the slot's "Edit ..." popup has produced it.
  Such a build is the placement's snapshot like any other,
  stored in `Placement.build` and saved with it;
  the name needs no uniquifying,
  since a build resolves its own art,
  and nothing keys on it beyond the menu label.
- `Build.art_path(root)`/`Build.weapon_path(root)` are a pure function
  of the build and the root, so two slots holding different builds of one
  character never share a weapon icon or a skin, and two builds that are
  otherwise identical but differ in weapon or constellation still resolve
  to different files, which a name-based key could not tell apart.
  The renderer takes only a `Project` and that same art root,
  never the editor's `builds` map,
  so it resolves each slot's art through `Placement.build` alone,
  calling those two methods directly.
  That is why the editor assigns `Placement.build`
  as soon as a build is resolvable, rather than resolving one where it is needed.
- `Project.profile_name` and `Project.identifier`
  (`profile_name or uid`) are the "a profile name takes priority
  over the UID when a project is opened" rule in one place.
- `Project.to_dict`/`from_dict` define the JSON project file format,
  `schemaVersion` currently 4.
  `storage.migrate_project_data()` is the single entry point
  for project migrations, called before `Project.from_dict()`:
  it carries the pre-v3 `fx`/`fy` conversion below,
  and the v3 -> v4 step of defaulting `profileName` and every placement's `build`.
  A file already at 4 passes through untouched.
  The build editor needed no format change:
  a build its popup produces is the same snapshot the format already carries.
- `storage.py`'s pre-v3 migration, still part of the same entry point,
  turns placements and presets that stored an `fx`/`fy` focal point
  in source-art space into the panel-relative offsets.
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
the profile cache (`profile_cache_path()`, `save_profile_cache()`,
`load_profile_cache()`), keyed by the sanitized profile identifier,
the remembered profile identifier (`settings_path()`,
`load_last_profile()`, `save_last_profile()`, in `settings.json`),
and `migrate_project_data()`, the single entry point for project migrations.
That migration needs render geometry,
which is why `storage.py` imports `renderer` (as `from . import renderer`).

## `enka/`

All network interaction with Enka Network, over the `enka` PyPI package.

- `errors.py` — `EnkaError`, the single error type everything in the package raises.
- `http.py` — the plain `urllib` side: `USER_AGENT`, `fetch_json()`, `download()`.
- `freshness.py` — how old a cached Enka data file may get:
  `DATA_MAX_AGE_DAYS` (seven days, the one threshold every cached data file shares),
  `is_fresh(path, max_age_days=DATA_MAX_AGE_DAYS)`,
  which is `False` for a missing file,
  and `any_stale(paths)`.
- `parsing.py` — the library's models into our `Build`s,
  against `CharacterLike`, `WeaponLike`, `CostumeLike` and `SavedBuildLike` Protocols
  rather than the library's own types:
  `element_name()`, `art_url()`, `weapon_display_name()`, `constellation_level()`
  and `build_from_character()`.
- `profile.py` — identifier handling over plain HTTP:
  `is_uid()`, the `Hoyo` dataclass and `resolve_genshin_hoyo()`,
  which turns an Enka username into a hash and, when public, a UID.
- `client.py` — `EnkaClient`, the synchronous facade:
  `load_profile(identifier)` runs the async work through `asyncio.run()`,
  fetching the live showcase build when a UID is known,
  falling back to the builds endpoint's `live: true` entries otherwise
  (or when the showcase itself yields no characters),
  and the saved builds when a username resolves to a hash,
  and returns a `Profile`.
  `redirect_asset_files()` rewrites the third-party library's private,
  CWD-relative asset paths before the first client starts,
  and returns those redirected paths so the client can age them:
  a stale set makes the next load call the library's `update_assets()`
  before it fetches anything,
  which is the only way to re-download data files
  the library otherwise downloads once and keeps forever.
  A load refreshes them once more, and fetches a second time,
  when the first fetch names a character or weapon they do not describe
  or the library trips over them
  (`STALE_ASSET_ERRORS`, `_describes_unknown_data()`),
  which includes the library's own `AssetKeyError` data-miss report,
  but not its network and API failures, which a refresh cannot fix;
  at most one refresh happens per load, since it costs a download.
  A refresh drops the weapon catalog beside those files
  (`catalog.invalidate_weapon_data()`),
  which ages on the same schedule and describes the same patch.
  `EnkaError` still covers everything that leaves the package,
  including a stale-data failure that survived the refresh.
- `assets.py` — `download_assets(builds, root, progress=None, on_build=None)`,
  downloading and validating (dimension/format checks) character art and weapon icons
  to the paths each `Build` derives from `root`,
  publishing each file atomically (a validated temp file, then `os.replace()`)
  so a file only ever exists at its final path once it is complete,
  and calling `on_build(build)` once both of a build's files are published.
  It returns `None`: there is nothing left to key, since the paths are the identity.
- `catalog.py` — the costume and weapon catalog the build editor popup
  offers its choices from: `Catalog` (`skins(build)`, `weapons_for(build)`,
  `element_is_variable(build)`), the `SkinOption` and `WeaponOption`
  dataclasses, `WEAPON_TYPE_IDS` and `load_catalog(asset_root)`.
  `load_catalog()` reads the `enka` library's already-downloaded
  `characters.json` and `text_map.json` from the asset root,
  and downloads `WEAPON_DATA_URL` (Enka's own weapon catalog) into
  `weapons.json` there, refreshing it after `DATA_MAX_AGE_DAYS`;
  a missing or unreadable file degrades to an empty catalog
  and a failed download falls back to whatever is already on disk.
  `load_catalog()` never raises.
  `invalidate_weapon_data(asset_root)` removes that `weapons.json`,
  so the next `load_catalog()` re-fetches it;
  it is a cache drop and never fails.

Only `client.py` imports the third-party `enka` package,
and it imports it as `enka_api`:
`genshin_thumbnail_studio.enka` does not shadow the installed `enka`,
since Python resolves by full dotted name,
but a bare `import enka` inside our own `enka/client.py`
would read as a self-import.

Import direction: `errors` and `freshness` import nothing from the package;
`http` and `parsing` import `errors`;
`profile` imports `errors` and `http`;
`assets` imports `errors` and `http`;
`catalog` imports `errors`, `freshness`, `http` and `parsing`, and reaches `Build`
through `..models`;
`client` imports `catalog`, `errors`, `freshness`, `http`, `parsing` and `profile`
(no cycle: `catalog` does not import `client`).
Only `client.py` imports the third-party library,
so everything else in the package is testable without it.

## `renderer/`

Pure Pillow-based image compositing, no Qt or network dependency.

- `geometry.py` — panel geometry and the reachable pan range:
  `BASE_W`/`BASE_H`, `LINE`/`CARD_BORDER`/`CARD_GAP`, `BACKGROUND_COLOR`,
  `STANDARD_ART_SIZE`, `PAN_OVERSCAN`,
  `panel_metrics()`, `panel_target_size()`, `panel_origin()`, `panel_polygon()`,
  `cover_scale()`, `scaled_size()`, `resized_art_size()`,
  `offset_limits()`, `zoom_offset_limits()`, `max_offset()`.
- `colors.py` — the element and rarity palettes and the card color lookup:
  `card_color(member)` reads `member.build.element` when there is a build
  with a known element, falling back to the placement's own `color` otherwise.
- `coverage.py` — the antialiasing primitives Pillow's `ImageDraw` lacks,
  around `GEOMETRY_SUPERSAMPLE`.
- `cache.py` — `CacheKey`, the seven bounded LRU caches with their `*_CACHE_MAX` bounds,
  the lock guarding them, `cache_get()`, `cache_put()`, `clear_render_cache()`.
- `art.py` — decoding, resizing and cropping the source art:
  `MAX_PLACEMENT_ZOOM`, `GLOW_ZOOM_FACTOR`, `glow_zoom()`, `art_pixel_size()`,
  `source_art(art_path, target, zoom, scale)`, `cover_resize_offset()`, `panel_art()`.
  The cache keys on `str(art_path)`, which is already the derived, content-identified path.
- `panels.py` — one character panel end to end:
  `GLOW_DOWNSCALE`, `panel_background()`, `apply_panel_mask()`,
  `make_panel(width, member, art_path, index, row, num_rows, row_height, step, slant, scale, compact)`,
  `placeholder_panel()`,
  `add_card_borders(canvas, teams, row_height, step, slant, scale)`.
  `make_panel()` calls `source_art(art_path, ...)` and `card_color(member)` directly;
  neither takes an `Asset` any more.
- `badges.py` — the C/R and weapon badges: `find_font()`, `BadgeGeometry`,
  `badge_tile(geometry, build, weapon_path, color, font, scale, compact)`
  (reading `build.constellation`, `.refinement`, `.rarity`, `.weapon_rarity`
  directly off the `Build`),
  `add_badges(canvas, teams, art_root, row_height, step, scale, compact)`,
  which resolves each member's `build.weapon_path(art_root)` itself.
- `compose.py` — the whole canvas:
  `render_image(teams, art_root, compact, scale=1, output_size=..., require_complete=True)`
  builds the slanted-panel team layout at a given integer `scale`
  and downsamples to 1280x720, resolving each member's `build.art_path(art_root)`
  once and passing it down rather than re-deriving or re-checking it;
  a member is filled when that path is not `None` and exists on disk,
  and `require_complete` raises for a slot that is not;
  `render_preview(project, art_root)` (scale 1) and
  `export_project(project, art_root, directory)` (scale 2, writes PNGs)
  are the GUI's two entry points and both first call `Project.ensure_shape()`.
  The panel cache key is `str(art_path)` in place of the old
  `member.asset_key or member.name.casefold()`:
  the path is the identity now, character and content included.
  It is `None` for a slot with no art yet,
  whose placeholder panel depends on nothing but the placement's own color
  and the geometry, both of which the key already carries.
  `renderer/` imports no `Asset`; there is none left to import.

Import direction: `cache`, `geometry`, `colors` and `coverage` import nothing from the package;
`art` imports `geometry` and `cache`;
`panels` imports `geometry`, `colors`, `coverage`, `cache` and `art`;
`badges` imports `colors`, `coverage` and `cache`;
`compose` imports `geometry`, `colors`, `cache`, `panels` and `badges`.

## `gui/`

The PySide6 desktop application.
It wires user input (UID/username entry, build selection, mode selection,
drag/wheel/slider placement editing, flip toggle)
to `enka/` for fetching,
`renderer/` for live preview and export,
and `storage.py` for persistence.

- `app.py` — `run()`, the entry point behind `pyproject.toml`'s `gui-scripts`,
  `__main__.py` and `launch.py`.
  With `--smoke-test` among the arguments it starts as usual,
  then closes the window and returns `0` once the first preview render arrives
  (`MainWindow.preview_rendered`),
  or `1` when that render fails (`MainWindow.preview_failed`)
  or nothing arrives within 30 seconds,
  logging the reason with `logger.error`,
  so a packaged binary can be checked without user interaction.
- `logging_setup.py` — `configure_logging()`, called first in `run()`:
  a console `StreamHandler` at INFO and a rotating file handler at DEBUG
  writing `app_data_dir() / "logs" / "app.log"`,
  both on the root logger,
  degrading to the console alone when the file cannot be opened.
  It also replaces `loguru`'s default sink,
  which the `enka` library logs through,
  with one that forwards into `logging` at WARNING.
  Idempotent: a second call attaches nothing.
- `style.py` — `MAIN_STYLESHEET`, the whole application's QSS,
  applied once to the main window.
- `main_window.py` — `MainWindow`:
  the splitter holding the two panels,
  placement editing and selection, `build_selected()`
  (assigning a chosen build onto a member and re-running the same tail
  `member_changed()` does), the asset-arrival handlers,
  the close sequence,
  and thin delegates to the collaborators below.
  It constructs every widget through the two panels
  and owns no child widget of its own.
  It also owns the `Catalog` the way it owns its `EnkaClient`:
  `catalog()` loads it lazily on first use, from the same
  `cache_dir() / "enka"` asset root the client already reads,
  wrapped in the same wait-cursor pattern `ProfileLoader.load()` uses,
  and caches it for later calls;
  `invalidate_catalog()` drops that cache,
  which `ProfileLoader.load()` calls after every successful profile load,
  since the load may have refreshed the data the catalog was built from.
  A build the editor popup produces reaches the model through the existing
  `build_selected()`; it is not a different kind of thing from the builds
  already in that menu, so it needs no model write of its own.
- `actions.py` — `ProjectActions`
  and the `ProjectActionHost` Protocol it dispatches through.
  Owns the five project `QAction`s
  (`new`, `open`, `save`, `save_as`, `export`,
  bound to `Ctrl+N`, `Ctrl+O`, `Ctrl+S`, `Ctrl+Shift+S` and `Ctrl+E`)
  and the "Save as..." menu,
  registering each action on the window so its shortcut is window-wide.
  `bind_buttons(panel)` makes the panel's four project buttons trigger them;
  `set_project_path(path)` decides the save action's caption, tooltip and menu
  and pushes them onto the panel through `ControlsPanel.apply_save_action()`.
  Constructed once in `MainWindow.__init__` with the window
  and the window as `ProjectActionHost`.
- `controls_panel.py` — `RESOLUTION_OPTIONS` and `ControlsPanel`,
  the window's left column:
  the mode radios, the `profile_edit` entry
  (a Genshin UID or an Enka username) with its load button and profile status,
  the paste-lineup button, the scrolling `team_container`/`team_layout`,
  the output name and resolution fields,
  and the new, open, save and export buttons.
  All of them stay public attributes,
  which is what `project_io.ProjectEditor`, `profile_io.ProfileEditor`
  and the tests reach through;
  user intent leaves the panel as
  `mode_changed`, `profile_requested`, `paste_requested`,
  `output_name_changed` and `resolution_changed`.
  `align_save_button_height()` is called by the window
  once its stylesheet is applied,
  and `apply_save_action(text, tooltip, menu)` writes the save button's face
  as `actions.ProjectActions` decides it.
- `editor_panel.py` — `EditorPanel`, the window's right column:
  the preview toolbar with `preview_team_label` and the `boss_combo`
  (hidden outside stygian mode),
  the `PreviewWidget` as `preview`,
  and the placement row
  (`selected_label`, the X/Y/zoom sliders with their value labels,
  `flip_check` and `reset_button`).
  All of them stay public attributes,
  which is what `project_io.ProjectEditor` and the tests reach through;
  user intent leaves the panel as
  `active_team_changed`, `placement_changed`, `flip_toggled`
  and `reset_requested`.
  `preview`'s own `slot_selected`, `placement_dragged` and `zoom_requested`
  are not re-exposed: the window connects to `editor_panel.preview` directly.
- `build_editor.py` — `BuildEditorDialog`, the per-character build editor
  popup an "Edit ..." menu item opens, and `ask_custom_build(parent, build,
  catalog, custom_name)`, which constructs it, `exec()`s it,
  and returns `result_build()` on acceptance, else `None`.
  The dialog seeds a skin combo, a weapon combo and constellation/refinement
  spin boxes from a `Catalog`'s options for the build passed in,
  plus an `element_combo` (`ELEMENT_CHOICES`) added only when
  `catalog.element_is_variable(build)` is true,
  so `element_combo` is `None` for every character but the Traveler
  and the form has no element row at all.
  `result_build()` is a copy of the seed build (`dataclasses.replace`)
  with the chosen skin, weapon, constellation, refinement and, where there is
  a row for it, element, plus `build_name=custom_name` and `build_id=""`.
- `dialogs.py` — the blocking dialogs as free functions taking the parent widget:
  `confirm_discard_changes()`, `confirm_cache_refresh()`,
  `show_error()`, `show_export_finished()`, `confirm_showcase_lineup()`,
  `ask_lineup_text()`, `ask_export_target()`.
  They return the user's choice rather than acting on it.
- `project_io.py` — `ProjectFiles` (`new()`, `save()`, `save_as()`, `open()`, `export()`)
  plus the `ProjectEditor` Protocol it works through.
  Constructed once in `MainWindow.__init__` with the window, the window as
  `ProjectEditor`, and the window's `HistoryController`.
  `MainWindow` keeps thin `save_project()`, `save_project_as()`, `open_project()`
  and `export()` methods delegating here,
  so every caller and test still goes through the window.
- `profile_io.py` — `ProfileLoader` (`load()`, `paste_lineup()`, `validate_team()`)
  and, behind `load()`, the offer to fill the teams from a showcase
  that holds exactly one lineup,
  plus the `ProfileEditor` Protocol it works through.
  Constructed once in `MainWindow.__init__` with the window and the window as
  `ProfileEditor`. `MainWindow` keeps thin `load_profile()`, `paste_teams()`
  and `validate_team()` methods delegating here, the first and third of which
  `project_io.ProjectEditor` requires.
- `state.py` — the `EditorState` Protocol (`project`, `builds`, `art_root`),
  which `MainWindow` satisfies structurally. Must stay Qt-free.
- `build_choices.py` — Qt-free: `selected_build()`
  (the `Placement.build` snapshot, or the character's first/live build,
  or `None`), `resolve_build()` (`selected_build()`, also assigning the result
  onto the member), `BuildChoice` and `build_choices(profile_builds, stored)`,
  which merges a profile's builds with a project's stored one
  into the labelled, ordered list the build menu renders.
  Exactly those entries that carry the project's snapshot get a trailing
  `" (project)"` on its label, display-only and never written back onto
  `Build.build_name`; the profile's own entries keep their bare build names,
  including the merged entry whose details match the snapshot,
  which carries the profile's fresher `Build` and is indistinguishable from it.
  A snapshot the slot's own "Edit ..." popup produced is the exception:
  it carries `CUSTOM_BUILD_NAME` and keeps its bare name,
  since it comes from the project by definition
  and the suffix would say nothing.
  It needs no argument of its own:
  it is the stored build, so the merge already appends it last
  and already marks it as the selected entry.
- `placement.py` — `MIN_ZOOM`, `MAX_ZOOM` and `PlacementController`:
  `offset_bounds()` (reading the member's art size through its build's
  derived art path when that file exists, `STANDARD_ART_SIZE` otherwise),
  `pan()`, `zoom_by()`, `reset()`.
- `presets.py` — `preset_key()`
  (mode plus the costume id or casefolded name, in that fallback order)
  and `PresetStore` on top of `storage.load_presets`/`save_presets`.
- `preview.py` — `PreviewWidget`, the canvas that renders the pixmap
  and emits selection, drag and zoom signals.
  `set_context(mode, active_team, selected, filled)` tells it which slots have art.
- `team_slots.py` — `SLOT_MIME_TYPE` and `TeamSlotWidget`,
  which emits `drag_started`, `drag_hover` and `drag_ended` across a drag gesture,
  and `build_menu_requested` when its `build_button`
  (the arrow button next to the combo) is clicked.
  `build_button` now carries the selected build's label beside its arrow,
  set through `set_build_caption()`, which elides the label to
  `MAX_BUILD_CAPTION_WIDTH` and puts the full label in the tooltip.
  Its width is pinned to `BUILD_BUTTON_WIDTH` for every slot,
  so the combos beside the buttons end at one edge
  rather than each row breaking where its caption happens to;
  it is styled by the `QToolButton#buildButton` rule in `gui/style.py`.
- `team_fields.py` — `clear_layout()`, `TeamFieldsController`
  and the `TeamFieldsEditor` Protocol it works through.
  The controller fills `ControlsPanel.team_layout` with one `TeamSlotWidget`
  per slot (`rebuild()`), keeps their combos in step with the project
  (`refresh_display()`, `populate_items()`, the public `combos`),
  turns a drag gesture into a live reorder plus one undo step
  (`on_drag_started()`, `on_drag_hover()`, `on_drag_ended()`, `reorder()`,
  and `dragging`, which `MainWindow._on_asset_ready` reads),
  and answers each slot's `build_menu_requested`
  with `build_menu()` (the menu of that character's `build_choices()`,
  each action checked exactly when selected,
  and all of them sharing one exclusive `QActionGroup`,
  which is what makes Qt draw them as radio buttons rather than check boxes,
  plus a separator and a non-checkable "Edit ..." action below them,
  outside that group, added only when the slot has at least one build choice)
  and `show_build_menu()` (popping it up under the slot's button).
  `refresh_build_buttons()` also sets each slot's button caption to the
  label of its currently selected build choice.
  `_edit_build(team, slot)` takes the slot's currently selected build
  (falling back to its first choice) as the seed, opens
  `ask_custom_build()` against `self._editor.catalog()`,
  and on a build back from it goes through `_select_build()`,
  the same path an entry of the menu takes.
  `TeamFieldsEditor` gains `catalog() -> Catalog` for this,
  alongside its existing `build_selected()`.
  Constructed once in `MainWindow.__init__` with the window as
  `TeamFieldsEditor`, the panel's layout and the window's `HistoryController`.
  `MainWindow` keeps thin `rebuild_team_fields()` and `populate_combo_items()`
  methods delegating here, which `project_io.ProjectEditor` requires.
- `render_job.py` — `RenderJobSignals` and `RenderJob`,
  rendering a `Project` snapshot on a `QThreadPool` worker.
- `render_pipeline.py` — `RENDER_THROTTLE_MS` and `RenderPipeline`,
  the throttled preview loop:
  `schedule()`, `dispatch()`, `stop()`,
  the public `timer`, `token`, `running`, `stale` and `closing`,
  and the `rendered`/`failed` signals the window connects
  to the preview and the status bar.
- `asset_loader.py` — `AssetJobSignals`, `AssetJob` and `AssetLoader`,
  the background character-art downloads.
  `AssetLoader.ensure()` starts one `AssetJob` for the named members
  that resolve in `builds` but whose `(art_url, weapon_url)` pair is
  neither already in flight nor already downloaded under `self._root`,
  and emits `progress`, `asset_ready(build)` (carrying the `Build` that just
  finished downloading, so nothing needs its paths) and `failed`.
- `lineup.py` — `parse_lineup()`, splitting pasted lineup text into character names.
- `history.py` — `HISTORY_LIMIT`, `HISTORY_DEBOUNCE_MS`,
  `PlacementHistory` (Qt-free bounded undo/redo over the teams of `Placement`s)
  and `HistoryController` (`schedule()`, `commit_now()`, `reset()`, `undo()`, `redo()`,
  plus the `Ctrl+Z`/`Ctrl+Y`/`Ctrl+Shift+Z` shortcuts).

Qt-free and unit-testable on their own:
`build_choices.py`, `placement.py`, `presets.py`, `state.py`, `lineup.py`,
and `history.py`'s `PlacementHistory`.
Qt-bound: everything else, including `history.py`'s `HistoryController`.

Import direction:
`build_editor`, `controls_panel`, `dialogs`, `lineup`, `preview`, `render_job`, `state`,
`style` and `team_slots` import nothing from the package
(`render_job` reaches the renderer through `..renderer`,
and `build_editor` reaches `Build` through `..models` and `Catalog` through `..enka`);
`asset_loader`, `build_choices`, `history`, `placement` and `presets` import `state`
(`history` also reaches `Placement` through `..models`,
and `asset_loader` reaches `download_assets` through `..enka`);
`actions` imports `controls_panel`;
`editor_panel` imports `preview`;
`render_pipeline` imports `state` and `render_job`,
and reaches `Project` through `..models`;
`team_fields` imports `state`, `history`, `build_choices`, `build_editor` and `team_slots`,
and reaches `Placement` through `..models` and `Catalog` through `..enka`;
`project_io` imports `state`, `dialogs`, `history`, `asset_loader`, `build_choices`,
`controls_panel` and `editor_panel`,
and reaches `..models`, `..storage` and `..renderer` outside the package;
`profile_io` imports `state`, `dialogs`, `lineup`, `asset_loader`, `build_choices`,
`controls_panel` and `team_fields`,
and reaches `..enka` and `..storage` outside the package;
`main_window` imports `actions`, `asset_loader`, `build_choices`, `controls_panel`,
`dialogs`, `editor_panel`, `history`, `placement`, `presets`, `profile_io`, `project_io`,
`render_pipeline`, `style` and `team_fields`,
and reaches `Catalog`/`load_catalog` through `..enka`.
It imports neither `app` nor `state`, `lineup`, `preview`, `render_job`,
`team_slots` or `build_editor`:
`state` it satisfies structurally,
`build_editor` it reaches through `team_fields`,
and the other four it reaches through the panel or the collaborator that owns them.
`dialogs` and `profile_io` it imports as modules
(`from . import dialogs, profile_io`) and the rest by name,
for the reason design-notes' "Where the tests patch" gives.
`logging_setup` imports nothing from the package
except `app_data_dir()` through `..storage`;
`app` imports `main_window` and `logging_setup`.

## Data flow

UID or username entered in the GUI ->
`EnkaClient.load_profile` ->
a `Profile` holding each character's builds, live first ->
`AssetLoader.ensure()` ->
`download_assets` on a worker thread,
publishing each build's character art and weapon icon
to the paths that build derives from the art root ->
`render_preview`/`export_project` consume `Project.teams` and that same art root,
each `Placement.build` resolving its own cached files from it,
to produce images.

Nothing waits for that download:
the preview renders continuously,
with a `placeholder_panel()` wherever a slot's derived file has not arrived yet.
