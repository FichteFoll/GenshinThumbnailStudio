"""Tests for the project actions' key bindings and the save button's two faces.

These build a real `MainWindow`, so they need the offscreen platform that
`tests/gui/conftest.py` sets.
"""

from pathlib import Path
from typing import cast

import pytest
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QAbstractButton, QToolButton

from genshin_thumbnail_studio.gui import MainWindow, dialogs, project_io

from . import helpers
from .helpers import close_ignoring_unsaved_changes, qapp


def _action_for(window: MainWindow, sequence: str) -> QAction:
    """The window-level action bound to `sequence`.

    Looked up by sequence rather than by attribute name, so dropping a binding
    fails the test instead of silently passing on the attribute alone.
    """
    return next(action for action in window.actions() if action.shortcut() == QKeySequence(sequence))


@pytest.mark.parametrize(
    ("sequence", "method"),
    [
        ("Ctrl+O", "open_project"),
        ("Ctrl+S", "save_project"),
        ("Ctrl+Shift+S", "save_project_as"),
        ("Ctrl+E", "export"),
    ],
)
def test_each_project_shortcut_triggers_the_action_it_names(
    sequence: str, method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    calls: list[str] = []

    def record() -> None:
        calls.append(method)

    # Triggering the action rather than posting a key event, for the reason
    # `tests/gui/test_undo.py:_activate` documents: an offscreen window never
    # gains the focus real key delivery needs.
    monkeypatch.setattr(window, method, record)
    _action_for(window, sequence).trigger()

    assert calls == [method]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


@pytest.mark.parametrize(
    ("button", "method"),
    [("open_button", "open_project"), ("save_button", "save_project"), ("export_button", "export")],
)
def test_each_project_button_runs_the_flow_its_action_names(
    button: str, method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    calls: list[str] = []

    def record() -> None:
        calls.append(method)

    monkeypatch.setattr(window, method, record)
    # The save button's main section has to save rather than drop the menu,
    # which is what MenuButtonPopup buys over InstantPopup.
    assert window.controls_panel.save_button.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup
    cast(QAbstractButton, getattr(window.controls_panel, button)).click()

    assert calls == [method]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_the_save_button_offers_save_as_only_once_a_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    assert window.controls_panel.save_button.text() == "Save project as..."
    assert window.controls_panel.save_button.menu() is None

    monkeypatch.setattr(
        project_io.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(tmp_path / "project.json"), "")),
    )
    window.save_project()

    assert window.controls_panel.save_button.text() == "Save project"
    menu = window.controls_panel.save_button.menu()
    assert menu is not None
    assert [action.shortcut() for action in menu.actions()] == [QKeySequence("Ctrl+Shift+S")]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_switching_the_mode_puts_the_save_button_back_to_save_as(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    monkeypatch.setattr(
        project_io.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(tmp_path / "project.json"), "")),
    )
    window.save_project()
    assert window.controls_panel.save_button.menu() is not None

    monkeypatch.setattr(dialogs, "QMessageBox", helpers.DiscardMessageBox)
    window.controls_panel.stygian_radio.setChecked(True)

    assert window.project_path is None
    assert window.controls_panel.save_button.text() == "Save project as..."
    assert window.controls_panel.save_button.menu() is None

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_the_project_buttons_name_their_shortcut_in_the_tooltip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    assert "Ctrl+O" in window.controls_panel.open_button.toolTip()
    assert "Ctrl+S" in window.controls_panel.save_button.toolTip()
    assert "Ctrl+E" in window.controls_panel.export_button.toolTip()

    close_ignoring_unsaved_changes(window, app, monkeypatch)
