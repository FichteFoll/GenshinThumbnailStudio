"""Tests for the Save/Discard/Cancel prompt on window close and mode switch."""

from pathlib import Path
from typing import ClassVar

import pytest
from PySide6.QtWidgets import QMessageBox

from genshin_thumbnail_studio.gui import MainWindow, dialogs, project_io

from .helpers import qapp


class DecisionMessageBox:
    """Records the dialog shown and simulates clicking one fixed button.

    `choice` selects which button `clickedButton()` reports as clicked:
    "save", "discard", or "cancel".
    """

    ButtonRole = QMessageBox.ButtonRole
    StandardButton = QMessageBox.StandardButton
    choice: ClassVar[str] = "cancel"
    instances: ClassVar[list["DecisionMessageBox"]] = []

    def __init__(self, parent: object = None) -> None:
        self.title = ""
        self.text = ""
        self._buttons: dict[str, object] = {}
        type(self).instances.append(self)

    def setWindowTitle(self, title: str) -> None:
        self.title = title

    def setText(self, text: str) -> None:
        self.text = text

    def addButton(self, *args: object) -> object:
        button = object()
        label = args[0]
        key = "save" if isinstance(label, str) and "save" in label.casefold() else (
            "discard" if isinstance(label, str) else "cancel"
        )
        self._buttons[key] = button
        return button

    def exec(self) -> None:
        return None

    def clickedButton(self) -> object | None:
        return self._buttons.get(type(self).choice)


class ForbiddenMessageBox(DecisionMessageBox):
    def __init__(self, parent: object = None) -> None:
        raise AssertionError("unexpected message box")


def test_closing_a_clean_window_does_not_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window = MainWindow()

    assert window.close() is True

    app.processEvents()


def test_closing_a_dirty_window_and_cancelling_keeps_it_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    DecisionMessageBox.instances = []
    DecisionMessageBox.choice = "cancel"
    monkeypatch.setattr(dialogs, "QMessageBox", DecisionMessageBox)
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3

    assert window.close() is False
    assert len(DecisionMessageBox.instances) == 1

    DecisionMessageBox.choice = "discard"
    window.close()
    app.processEvents()


def test_closing_a_dirty_window_and_discarding_closes_without_saving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    DecisionMessageBox.choice = "discard"
    monkeypatch.setattr(dialogs, "QMessageBox", DecisionMessageBox)
    monkeypatch.setattr(
        project_io.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: pytest.fail("must not be called")),
    )
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3

    assert window.close() is True

    app.processEvents()


def test_closing_a_dirty_window_and_saving_writes_the_project_then_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    DecisionMessageBox.choice = "save"
    monkeypatch.setattr(dialogs, "QMessageBox", DecisionMessageBox)
    path = tmp_path / "thumbnail-project.json"
    monkeypatch.setattr(
        project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(path), ""))
    )
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3

    assert window.close() is True
    assert path.exists()

    app.processEvents()


def test_closing_and_choosing_save_but_cancelling_the_file_dialog_keeps_the_window_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    DecisionMessageBox.choice = "save"
    monkeypatch.setattr(dialogs, "QMessageBox", DecisionMessageBox)
    monkeypatch.setattr(
        project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: ("", ""))
    )
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3

    assert window.close() is False

    DecisionMessageBox.choice = "discard"
    window.close()
    app.processEvents()


def test_switching_mode_on_a_clean_window_does_not_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window = MainWindow()

    window.stygian_radio.setChecked(True)

    assert window.project.mode == "stygian"

    window.close()
    app.processEvents()


def test_switching_mode_with_unsaved_changes_and_cancelling_keeps_the_previous_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    DecisionMessageBox.choice = "cancel"
    monkeypatch.setattr(dialogs, "QMessageBox", DecisionMessageBox)
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3
    original_project = window.project

    window.stygian_radio.setChecked(True)

    assert window.project is original_project
    assert window.project.mode == "abyss"
    assert window.abyss_radio.isChecked()
    assert not window.stygian_radio.isChecked()

    DecisionMessageBox.choice = "discard"
    window.close()
    app.processEvents()


def test_switching_mode_with_unsaved_changes_and_discarding_switches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    DecisionMessageBox.choice = "discard"
    monkeypatch.setattr(dialogs, "QMessageBox", DecisionMessageBox)
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3

    window.stygian_radio.setChecked(True)

    assert window.project.mode == "stygian"
    assert not window.is_dirty()

    window.close()
    app.processEvents()


def test_switching_mode_with_unsaved_changes_and_saving_saves_then_switches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    DecisionMessageBox.choice = "save"
    monkeypatch.setattr(dialogs, "QMessageBox", DecisionMessageBox)
    path = tmp_path / "thumbnail-project.json"
    monkeypatch.setattr(
        project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(path), ""))
    )
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3

    window.stygian_radio.setChecked(True)

    assert path.exists()
    assert window.project.mode == "stygian"

    window.close()
    app.processEvents()
