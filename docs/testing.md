# Testing

## Layout

`tests/` mirrors the package layout:
`tests/enka/`, `tests/renderer/` and `tests/gui/`,
alongside the flat `tests/test_models.py`, `tests/test_storage.py`
and `tests/test_version.py`,
which keeps `__version__` in step with the version in `pyproject.toml`.
Each of the three subdirectories is a package (`__init__.py`) with its own `helpers.py`
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

## Test helpers

`tests/renderer/helpers.py`'s `create_assets()` and `tests/gui/helpers.py`'s
`create_test_assets()` no longer build a mapping to key into.
Both write each generated character and weapon image straight to
`build.art_path(root)`/`build.weapon_path(root)`, creating the parent
directories as needed, which is the same place `download_assets()` would
publish it, and return the `Build`s they created.
A caller names the build it wants and reads its files back off that build,
so no test spells an asset key out as a literal string any more
(`"furina|live"`, `"nahida|live"` and friends are gone):
a `Build`'s identity is its own name and URLs, not a name assigned to it
by a test.

## The layout guard

`tests/test_package_layout.py` guards the layout itself.
It is purely static:
it walks the tree and parses sources with `ast`,
importing neither the package nor PySide6.
It asserts the exact set of modules,
that sibling modules are reached by relative import,
that each facade's `__all__` only names things it binds,
and that no module has grown past a line-count tripwire (450 lines).
That bound was raised from 400 once, deliberately,
when the build editor's wiring landed in `gui/main_window.py`:
see the note on `catalog()` in [design-notes.md](design-notes.md).

Read it before moving or adding a module,
since it is the test that will fail.

## Timers

Tests assert what a timer does,
for example that the render throttle dispatches during a burst of `schedule()` calls,
rather than what `QTimer.remainingTime()` reports
for a timer that may have come due by the time it is sampled:
one started before the test's own setup,
or sampled later than its interval after starting.
A test runs no event loop between its statements,
so a timer that comes due stays active, undelivered,
and its remaining time is clamped to 0 from then on,
by both dispatchers:
`QEventDispatcherWin32::remainingTime()` in `src/corelib/kernel/qeventdispatcher_win.cpp`
(`return timeoutMs > currentTimeMs ? ... : 0ms;`)
and `QTimerInfoList::remainingDuration()` in `src/corelib/kernel/qtimerinfo_unix.cpp`,
both at `qtbase` tag `v6.11.1`.
The offscreen platform on Windows uses the Win32 dispatcher,
whose due time comes from the same `steady_clock` it compares against,
so the value is not a quirk of the Win32 dispatcher
but a race against wall-clock time.
That race is how the throttle test sampling `remainingTime()`
failed on `windows-latest` with `[0, 0, 0, 0, 0, 0]` and passed on Linux:
its timer was started by `MainWindow.__init__`, not by the test,
and an all-zero result with an active timer can only come from an overdue timer.
So on the Windows runner the interval between that start and the first sample,
returning from the constructor, `fill_window_teams()`
and mostly writing the test's PNG assets,
exceeded the 80 ms throttle
(inferred from the Qt source, not measured).
The throttle itself was intact:
a restarting `schedule()` would have reported about 80 ms after every call.

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
`tests/enka/test_catalog.py` is part of that package:
it builds `Catalog` from small literal dicts and monkeypatches
`catalog.download`, so it touches neither the network nor Qt.

`tests/renderer/` has no `conftest.py` either:
the renderer is Qt-free,
so `uv run pytest tests/renderer` runs without the offscreen environment.
So do the `tests/gui/` modules whose subjects construct no widget
(`test_lineup.py`, `test_placement_controller.py`, `test_presets.py`,
`test_asset_loader.py`, `test_build_choices.py`;
`AssetLoader` is a `QObject`, not a widget,
and its tests run jobs inline through a `QThreadPool` stand-in).
Everything else in `tests/gui/` needs the offscreen platform,
including `test_history.py`, whose `HistoryController` tests build a `QWidget` and a `QShortcut`,
and `test_build_editor.py`, which constructs `BuildEditorDialog` directly
against a `Catalog` built from literal dicts, driving its widgets
rather than `exec()`ing the dialog.

PySide6 still gets imported for all of these
(reaching any `gui` submodule executes the package facade, which imports `MainWindow`),
so the Qt-free property is about not needing a display, not about the import graph.
