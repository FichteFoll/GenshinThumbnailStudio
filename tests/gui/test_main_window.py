"""Tests for `MainWindow`'s webengine teardown on close."""

import gc
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from genshin_thumbnail_studio.gui import MainWindow

from .helpers import close_ignoring_unsaved_changes, qapp


def test_closing_window_does_not_warn_about_webengine_profile_teardown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    window.close()
    # ``close()`` alone does not destroy the underlying C++ widget (no
    # ``WA_DeleteOnClose``), and its child widgets' signal connections hold
    # closures referencing ``window`` that plain ``del``/``gc.collect()``
    # cannot reclaim (the connection storage is on the C++ side and is not
    # traversable by Python's cyclic GC). Explicitly tearing the widget down
    # and spinning one real event loop iteration lets Qt actually destroy it,
    # which is what exercises the GC-order-dependent page/profile teardown.
    window.deleteLater()
    loop = QEventLoop()
    QTimer.singleShot(0, loop.quit)
    loop.exec()
    del window
    gc.collect()

    captured = capfd.readouterr()
    assert "Release of profile" not in captured.err

    app.processEvents()


def test_main_window_starts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    assert window.windowTitle() == "Genshin Thumbnail Studio"
    assert len(window.team_combos) == 2
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
