"""Tests for `MainWindow`'s construction and its close sequence."""

from pathlib import Path

import pytest

from genshin_thumbnail_studio.gui import MainWindow

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


def test_editing_a_placement_marks_the_project_dirty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3
    assert window.is_dirty()
    close_ignoring_unsaved_changes(window, app, monkeypatch)
