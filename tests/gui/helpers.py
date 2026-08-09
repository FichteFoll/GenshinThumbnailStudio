"""Helpers shared by more than one of the gui test modules."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication, QMessageBox

from genshin_thumbnail_studio.gui import MainWindow, dialogs
from genshin_thumbnail_studio.models import Asset, Build


def qapp() -> QApplication:
    """The running `QApplication`, or a fresh one if none exists yet.

    `QApplication.instance()` is typed as returning the base `QCoreApplication`
    even when called on the `QApplication` subclass, a PySide6 stub gap; the
    isinstance narrowing works around it instead of widening every test's
    `app` to that base type."""
    instance = QApplication.instance()
    if isinstance(instance, QApplication):
        return instance
    return QApplication([])


TEAM_NAMES = ["Furina", "Nahida", "Xilonen", "Neuvillette", "Kazuha", "Bennett", "Xiangling", "Zhongli"]


def create_test_assets(directory: Path, names: list[str]) -> dict[str, Asset]:
    directory.mkdir(parents=True, exist_ok=True)
    assets: dict[str, Asset] = {}
    for index, name in enumerate(names):
        art_path = directory / f"art-{index}.png"
        weapon_path = directory / f"weapon-{index}.png"
        art = Image.new("RGBA", (1200, 900), (25 + index * 10, 70, 100, 255))
        ImageDraw.Draw(art).ellipse((250, 80, 950, 850), fill=(130 + index * 8, 180, 220, 255))
        art.save(art_path)
        weapon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        ImageDraw.Draw(weapon).polygon([(128, 10), (190, 220), (128, 190), (66, 220)], fill="white")
        weapon.save(weapon_path)
        build = Build(
            name=name,
            constellation=index % 7,
            refinement=index % 5 + 1,
            weapon_name="Weapon",
            costume_id=None,
            build_id=str(index),
            art_url="https://example.invalid/art.png",
            weapon_url="https://example.invalid/weapon.png",
        )
        assets[name.casefold()] = Asset(build, art_path, weapon_path)
    return assets


def fill_window_teams(window: MainWindow, names: list[str]) -> None:
    members = [member for team in window.project.teams for member in team]
    for member, name in zip(members, names, strict=False):
        member.name = name


class DiscardMessageBox:
    """Minimal `QMessageBox` stub that always reports the Discard button clicked.

    Lets `window.close()` proceed past the unsaved-changes prompt in tests
    that dirty the project incidentally and don't otherwise care about the
    save/discard/cancel choice.
    """

    ButtonRole = QMessageBox.ButtonRole
    StandardButton = QMessageBox.StandardButton

    def __init__(self, parent: object = None) -> None:
        self._discard_button = object()

    def setWindowTitle(self, title: str) -> None:
        pass

    def setText(self, text: str) -> None:
        pass

    def addButton(self, *args: object) -> object:
        button = object()
        if args and isinstance(args[0], str) and "discard" in args[0].casefold():
            self._discard_button = button
        return button

    def exec(self) -> None:
        return None

    def clickedButton(self) -> object:
        return self._discard_button


def close_ignoring_unsaved_changes(window: MainWindow, app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """Close `window`, auto-discarding any unsaved changes so the confirmation
    dialog added by `closeEvent` doesn't block a headless test that doesn't
    care about that prompt."""
    monkeypatch.setattr(dialogs, "QMessageBox", DiscardMessageBox)
    window.close()
    app.processEvents()


def wait_for_render(window: MainWindow, app: QApplication) -> None:
    """Block until the background render job dispatched by the window has finished."""
    for _ in range(200):
        if not window._render.running:
            return
        window._thread_pool.waitForDone(50)
        app.processEvents()
    raise AssertionError("render job did not finish in time")
