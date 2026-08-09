# Testing

## Layout

`tests/` mirrors the package layout:
`tests/enka/`, `tests/renderer/` and `tests/gui/`,
alongside the flat `tests/test_models.py` and `tests/test_storage.py`.
Each of those three directories is a package (`__init__.py`) with its own `helpers.py`
for the helpers more than one of its test modules needs;
helpers used by a single file stay in that file.
`tests/__init__.py` exists and is load-bearing:
without it pytest's prepend import mode puts `tests/` on `sys.path`,
where `tests/enka/` shadows the installed `enka` distribution
and `enka/client.py` can no longer import the library at all.

Tests import the module under test directly
(`genshin_thumbnail_studio.renderer.cache`, `...gui.main_window`)
rather than through the package facade,
because that is where a `monkeypatch.setattr()` has to land to take effect.
This is the one place the facade rule is deliberately broken.

## The layout guard

`tests/test_package_layout.py` guards the layout itself.
It is purely static:
it walks the tree and parses sources with `ast`,
importing neither the package nor PySide6.
It asserts the exact set of modules,
that sibling modules are reached by relative import,
that each facade's `__all__` only names things it binds,
and that no module has grown past a line-count tripwire.

Read it before moving or adding a module,
since it is the test that will fail.

## Headless runs

Profile data comes over plain HTTP now, with no embedded browser involved,
so headless/CI runs need only an offscreen Qt platform:

```bash
QT_QPA_PLATFORM=offscreen uv run pytest
```

`tests/gui/conftest.py` sets just that one `os.environ.setdefault()` call,
because it has to run before PySide6 is imported
and pytest imports a package's `conftest.py` before any of its test modules.

`tests/enka/` needs no `conftest.py` at all:
nothing in that package imports Qt.

`tests/renderer/` has no `conftest.py` either:
the renderer is Qt-free,
so `uv run pytest tests/renderer` runs without the offscreen environment.
So do the `tests/gui/` modules whose subjects construct no widget
(`test_lineup.py`, `test_placement_controller.py`, `test_presets.py`,
`test_asset_loader.py`, `test_build_choices.py`;
`AssetLoader` is a `QObject`, not a widget,
and its tests run jobs inline through a `QThreadPool` stand-in).
Everything else in `tests/gui/` needs the offscreen platform,
including `test_history.py`, whose `HistoryController` tests build a `QWidget` and a `QShortcut`.

PySide6 still gets imported for all of these
(reaching any `gui` submodule executes the package facade, which imports `MainWindow`),
so the Qt-free property is about not needing a display, not about the import graph.
