# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code)
when working with code in this repository.

## Project

Standalone PySide6 desktop app that builds Genshin Impact team thumbnails
(Spiral Abyss or Stygian Onslaught)
from a player's public Akasha profile,
without any AI image generation.
Fetches character/weapon art via Akasha/Enka,
lets the user drag-position each character in a preview,
and exports supersampled PNGs.

## Commands

Dependency management uses [uv](https://docs.astral.sh/uv/).

```bash
uv run genshin-thumbnail-studio   # run the app (auto-installs deps on first use)
uv sync --extra dev               # install dev deps (pytest, PyInstaller, basedpyright)
uv run pytest                     # run the test suite
uv run pytest tests/renderer/test_geometry.py::test_name   # run a single test
uv run basedpyright               # strict type check (configured in pyproject.toml)
uv run ruff check                 # lint the source and tests
```

Headless/CI runs need an offscreen Qt platform and a sandbox-free QtWebEngine,
since Akasha access goes through a real `QWebEnginePage`:

```bash
QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox uv run pytest
```

Packaging (runs the test suite first, then builds into `release/`):

```bash
packaging/build_linux.sh          # Linux tarball via PyInstaller
packaging/build_windows.ps1       # Windows package via PyInstaller
packaging/create_source_package.ps1  # clean source ZIP
```

Windows and Linux packages are built separately,
since native Qt binaries aren't portable across OSes.

## Architecture

A small layered pipeline, one concern per module,
all under `src/genshin_thumbnail_studio/`:

- `models.py` — the dataclasses (`Build`, `Asset`, `Placement`, `Project`)
  and the JSON project file format.
- `storage.py` — project/preset persistence and the app data dir.
- `akasha/` — all network and browser interaction with Akasha and Enka.
- `renderer/` — pure Pillow compositing, no Qt or network.
- `gui/` — the PySide6 application.

Dependency order:
`models` depends on nothing in the package,
`akasha` and `renderer` depend on `models` only,
`storage` depends on `models` and `renderer`,
`gui` depends on all four,
and nothing depends on `gui`.
There are no cycles, inside a package or between them.

Data flow: UID entered in GUI ->
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
- `Placement.name` is the join key to the `Asset` dict.
  A project file encodes placements and colors, not art,
  so re-opening a project requires re-fetching from Akasha.

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
