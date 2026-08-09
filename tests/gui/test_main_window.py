"""Tests for `MainWindow`'s construction and its close sequence."""

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from genshin_thumbnail_studio.enka import Catalog
from genshin_thumbnail_studio.gui import MainWindow, main_window

from .helpers import close_ignoring_unsaved_changes, qapp


def test_main_window_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    assert window.windowTitle() == "Genshin Thumbnail Studio"
    assert len(window.team_fields.combos) == 2
    window.close()
    app.processEvents()


def test_new_window_has_no_unsaved_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    assert not window.is_dirty()
    window.close()
    app.processEvents()


def test_the_catalog_is_loaded_once_and_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Loading it costs a download, so it happens on the first "Edit ..." and
    never again for the life of the window."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    roots: list[Path] = []

    def fake_load_catalog(asset_root: Path) -> Catalog:
        roots.append(asset_root)
        return Catalog({}, {}, {})

    monkeypatch.setattr(main_window, "load_catalog", fake_load_catalog)

    first = window.catalog()
    second = window.catalog()

    assert first is second
    assert roots == [window._enka_asset_root]
    window.close()
    app.processEvents()


def test_a_failing_catalog_load_still_restores_the_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`load_catalog()` promises never to raise, but a wait cursor left behind
    by a broken promise would freeze the pointer for the rest of the session."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    def failing_load_catalog(asset_root: Path) -> Catalog:
        raise OSError("no catalog today")

    monkeypatch.setattr(main_window, "load_catalog", failing_load_catalog)

    with pytest.raises(OSError):
        window.catalog()

    assert QApplication.overrideCursor() is None
    window.close()
    app.processEvents()


def test_editing_a_placement_marks_the_project_dirty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3
    assert window.is_dirty()
    close_ignoring_unsaved_changes(window, app, monkeypatch)
