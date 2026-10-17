# Changelog

All notable changes since the initial import.

## Unreleased

### Added

- **Showcase as a lineup.**
  Loading a profile whose live showcase holds exactly as many characters
  as the mode has slots (eight for abyss, twelve for stygian)
  offers to fill the teams with it,
  in the order Enka returned the showcase.
  The slots are then dragged into their intended teams and positions.
- **Automatic refresh of the cached Enka data files.**
  They are re-downloaded once they are a week old,
  and immediately, on demand,
  whenever a profile load runs into a character or weapon
  the cached files do not describe.
- **Console and file logging with full tracebacks.**
  Every exception that reaches an error popup is also logged,
  with its traceback,
  to the console and to a rotating log file under the app data directory.

### Changed

- **Linux and Windows packages are attached to each GitHub release.**
- **The package archive names carry the version,**
  for example `GenshinThumbnailStudio-0.2.0-windows-x64.zip`.
- **The Linux package is built on Ubuntu 22.04**
  and runs on distributions with glibc 2.35 or newer.
- **Smaller packages,**
  since the unused Qt Quick, QML,
  virtual keyboard and PDF modules are no longer bundled.
  The unpacked Linux package shrinks from 268 MiB to 248 MiB.
- **No confirmation popup after a successful export.**
  The status bar still reports how many thumbnails were written.

### Fixed

- **Profile loads that failed with
  `'NoneType' object is not subscriptable`**
  on Enka data files older than the patch the profile was recorded under.
  The affected files are now refreshed and the load retried automatically.
- **Project saves that failed without an error popup.**
  A failed save is now reported,
  and the project stays marked as unsaved.

## 0.2.0 - 2026-08-09

### Added

- **Enka Network as the data source.**
  Profiles are fetched directly through the `enka` PyPI package,
  and the profile field accepts either a Genshin UID or an Enka profile username.
- **Per-character build picker.**
  Each team slot has a build menu listing that character's builds,
  rendered as radio buttons,
  with the selected build shown on the slot's button
  and every entry that came from the opened project file labelled `(project)`.
  When no showcase is reachable,
  the live builds are taken from the builds endpoint instead.
- **Custom builds.**
  An "Edit ..." item at the bottom of a slot's build menu
  opens a per-character popup for skin, weapon, constellation and refinement
  (plus element, for the Traveler),
  seeded with the build the slot is currently framed with.
  The result joins the slot's menu as a "Custom" build,
  is saved in the project file,
  and has its art and weapon icon downloaded like any other build's.
  The choices come from a new Enka costume and weapon catalog.
- **Always-on preview.**
  The window renders from the moment it opens and keeps itself up to date;
  the "Generate preview" button is gone.
  Slots without downloaded art render as inert placeholder panels,
  and character art is downloaded in the background so the editor never blocks on the network.
- **Undo and redo** over each character's offsets, zoom and flip,
  and over which character sits in which slot.
  Snapshots are debounced,
  so a drag or a slider sweep is one undoable step.
  Bound to `Ctrl+Z`, with `Ctrl+Y` and `Ctrl+Shift+Z` for redo,
  over a bounded history.
- **Unsaved-changes prompt** with Save / Discard / Cancel,
  shown before closing the window and before switching between Spiral Abyss and Stygian Onslaught mode.
- **Keyboard shortcuts for the project actions**:
  `Ctrl+N` new project, `Ctrl+O` open, `Ctrl+S` save,
  `Ctrl+Shift+S` save as, `Ctrl+E` export.
  Every bound button names its shortcut in its tooltip.
- **Horizontal portrait flip**,
  toggled per placement slot next to the X/Y/zoom controls,
  saved in the project file and remembered per character in the placement presets.
- **Configurable output resolution** from 720p to 2160p, defaulting to 1080p.
- **Element-inspired card colors**,
  with the element and rarity parsed from the profile data,
  the C/R text runs colored by character and weapon rarity,
  and the weapon badge outline drawn in the element color.
- **Drag-and-drop slot reordering** in the team overview,
  which reorders the list and re-renders the preview live while the drag is in progress,
  using insert/shift semantics,
  and reverts if the drag ends without a drop.
- **Profile cache per UID**, persisted after every fetch,
  so opening a project restores its builds and preview without a network round trip.
  The profile identifier is also remembered across sessions.
- `|` accepted as a team-lineup separator in the paste dialog.
- `docs/` with the architecture inventory, design notes and testing guide.

### Changed

- Export goes through a save-file dialog defaulting to the opened project's folder,
  and writes PNG instead of JPG.
- Saving overwrites the current project file,
  asking for a path only when there is none;
  "Save as" stays reachable via `Ctrl+Shift+S` and a dropdown on the save button.
  A saved project becomes the current project file.
- The X/Y placement sliders are signed offsets centered on zero,
  measured in fractions of the character panel,
  pointing in the direction the portrait actually moves
  and truncated to the reachable range.
  Dragging moves the portrait one canvas pixel per mouse pixel on both axes,
  and art may be panned slightly past its edges.
- Zoom scales both art dimensions by the same factor, so portraits are never stretched,
  and abyss placements default to 100% instead of 106%.
- Slanted card separators replaced by card gaps and per-card borders.
- Badge C/R text is centered with measured, content-driven geometry.
- The whole GUI is in English,
  with the profile timestamp in a locale-neutral format.
- The panel glow follows the portrait's scaling and pan range,
  clamped against the same shared limits.

### Removed

- The Akasha browser client and the `akasha/` sub-package;
  QtWebEngine is no longer on the runtime path.
- The "Generate preview" button and the manual preview step behind it.
- The `Asset` dataclass, `Build.key`, `Placement.asset_key` and the asset dict;
  a build now resolves its own cached art and weapon paths from a cache root.

### Fixed

- Stale panel-color cache:
  the panel cache was keyed on `member.color`
  while the panel was painted with the resolved card color,
  so an element change could serve a wrongly colored panel.
- Weapon icons are centered on their visible art rather than their padded source canvas,
  so asymmetrically padded PNGs no longer sit off-center in the badge circle.
- `find_font()`'s shared font object is thread-safe.
- Export-scale cache entries are cleared when `export_project()` finishes,
  instead of growing for the rest of the session.
- The `Release of profile requested but WebEnginePage still not deleted` warning,
  by ordering the `QWebEnginePage`/profile teardown.
- Redo survives a restore and is not left behind by a cancelled slot drag.
- Art requested again when an undo brings a slot back,
  and no requests issued while the window is closing.
- The rounded C/R box corners, the weapon circle border
  and the slanted panel edges and card borders are antialiased.
- Stale drag-handle tooltip corrected to match the reorder behavior.

### Technical / Internal

- **Dependency management migrated to uv**,
  replacing `requirements.txt`.
- **Preview render performance.**
  Rendering runs on a background thread pool with stale requests dropped,
  and is throttled so the preview updates during a drag.
  Decoded character art, a preview-sized working copy,
  per-panel output, weapon icons and per-slot badge overlays are cached behind a lock;
  only the visible source region is resampled;
  the glow renders at reduced resolution;
  and compositing works on panel-sized rather than full-canvas layers.
  The measured drag frame went from roughly 90 ms to a fraction of it.
- **Module layout split.**
  `akasha.py`, `renderer.py` and `gui.py` became sub-packages
  of one cohesive concern per module,
  each with a facade `__init__.py` and an explicit `__all__`,
  with the test suite split to mirror them.
  `MainWindow`'s placement and preset logic moved into Qt-free collaborators.
- **GUI panel decomposition.**
  The window layout split into `ControlsPanel` and `EditorPanel` widgets,
  with the render pipeline, project file flows, team fields, profile loading
  and project actions each moved into their own module and constructed as collaborators.
- `tests/test_package_layout.py` asserts the module set, the import direction,
  the facade `__all__`s and a per-module line-count tripwire.
- **basedpyright in strict mode** across sources and tests,
  introduced with an ignore list that later commits shrank to nothing.
- **ruff** added as a dev dependency, configured in `pyproject.toml`,
  wired into CI, and the repository made clean under it.
- Project dirty state tracked via a saved-snapshot comparison.
- `Build.to_dict`/`from_dict` round trip, and typed model and migration code.
- Module docstrings added throughout.
- `CLAUDE.md`, `README.md` and `docs/` reformatted with semantic linefeeds,
  with the detail moved out of `CLAUDE.md` into `docs/`.
- A `test-runner` agent, and notes on sharing one uv environment across plan worktrees.
