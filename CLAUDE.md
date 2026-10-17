# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code)
when working with code in this repository.

## Project

Standalone PySide6 desktop app that builds Genshin Impact team thumbnails
(Spiral Abyss or Stygian Onslaught)
from character builds on Enka Network,
by Genshin UID or by profile username,
without any AI image generation.
Fetches character/weapon art via Enka,
lets the user drag-position each character in a preview,
and exports supersampled PNGs.

## Commands

Dependency management uses [uv](https://docs.astral.sh/uv/).

```bash
uv run genshin-thumbnail-studio   # run the app (auto-installs deps on first use)
uv sync                           # install the app and its dev dependency group
uv run pytest                     # run the test suite
uv run pytest tests/renderer/test_geometry.py::test_name   # run a single test
uv run basedpyright               # strict type check (configured in pyproject.toml)
uv run ruff check                 # lint the source and tests
```

Headless/CI runs need an offscreen Qt platform:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest
```

A fresh git worktree gets its own `.venv`,
so each one pays a full `uv sync` before the first check.
When several worktrees run the same dependency set,
as they do while executing a plan whose commits do not touch `pyproject.toml`,
point them at one environment instead:

```bash
export UV_PROJECT_ENVIRONMENT=/path/to/shared/.venv
```

Only under that condition, and only for one worktree at a time.
The project itself is installed into the environment as an editable pointer
to whichever worktree synced last,
so two worktrees alternating against a shared `.venv`
would silently run the tests against the other one's sources.
A commit that changes a dependency needs its own environment as well.

Packaging, driven by the PyInstaller spec `packaging/GenshinThumbnailStudio.spec`:

```bash
uv run python packaging/build.py   # tests, PyInstaller, smoke test, archive into release/
```

`--skip-tests` skips the test suite.
Each OS builds its own package, on that OS,
since native Qt binaries aren't portable across OSes.

## Architecture

A small layered pipeline, one concern per module,
all under `src/genshin_thumbnail_studio/`:

- `models.py` — the dataclasses (`Build`, `Placement`, `Project`)
  and the JSON project file format.
- `storage.py` — project/preset persistence and the app data dir.
- `enka/` — all network interaction with Enka Network, over the `enka` PyPI package.
  Its `catalog.py` is the costume and weapon catalog
  the build editor popup offers its choices from.
- `renderer/` — pure Pillow compositing, no Qt or network.
- `gui/` — the PySide6 application.

Dependency order:
`models` depends on nothing in the package,
`enka` and `renderer` depend on `models` only,
`storage` depends on `models` and `renderer`,
`gui` depends on all four,
and nothing depends on `gui`.
There are no cycles, inside a package or between them.

Data flow: UID or username entered in the GUI ->
`EnkaClient.load_profile` ->
a `Profile` holding each character's builds, live first ->
`AssetLoader.ensure()` ->
`download_assets` on a worker thread,
publishing each build's character art and weapon icon
to the paths that build itself derives from the art root ->
`render_preview`/`export_project` consume `Project.teams` and that same art root,
each `Placement.build` resolving its own cached files from it,
to produce images.
Nothing waits for that download:
the preview renders continuously,
with a `placeholder_panel()` wherever a slot's derived file has not arrived yet.

### Rules

- Each sub-package's `__init__.py` is a facade with an explicit `__all__`.
  Import across packages through the facade (`from ..renderer import max_offset`),
  and within a package by relative import (`from .geometry import panel_target_size`).
  Tests are the deliberate exception:
  they import the module under test directly, so `monkeypatch.setattr()` lands.
- `tests/test_package_layout.py` asserts the module set, the import direction,
  the facade `__all__`s and a per-module line-count tripwire.
  Read it before moving or adding a module, since it is the test that will fail.
- `gui/state.py` must stay Qt-free; `EditorState` is what the Qt-free collaborators depend on.
- A build resolves its own art: `Build.art_path(root)` and `Build.weapon_path(root)`
  derive a slot's cached character and weapon files from nothing but the build
  and an art root, so `Placement.build` is the only join key a slot needs,
  while `Placement.name` only names the character.
  The renderer takes that root beside the `Project`
  (`render_preview(project, art_root)`, `export_project(project, art_root, directory)`),
  and a download's only job is to put the file where the build says it goes,
  publishing it atomically once it is validated.
  A project file still encodes the selected build's details,
  so it reopens with the framing *and* the C/R and weapon badges it was saved with,
  while the art itself is still re-fetched from Enka.
  A build the slot's own "Edit ..." popup produced is that same snapshot,
  named `CUSTOM_BUILD_NAME`, so it needs no field and no format change:
  the project file stays at `schemaVersion` 4.

## Docs

Detail that matters while touching a specific module lives in `docs/`:

- [docs/architecture.md](docs/architecture.md) —
  per-module inventory, the import direction of each package, the data model.
  Read before adding to or moving something inside a package.
- [docs/design-notes.md](docs/design-notes.md) —
  why the non-obvious parts are the way they are.
  Read the entry for a module before changing it.
- [docs/testing.md](docs/testing.md) —
  test layout, the layout guard, and which tests need the offscreen platform.

When a change invalidates something in `docs/`, update that file rather than this one.

User-visible changes go into [CHANGELOG.md](CHANGELOG.md),
under an `## Unreleased` heading
that a release renames to the version and date.
The version itself lives in `pyproject.toml` and `src/genshin_thumbnail_studio/__init__.py`,
which have to be bumped together.
