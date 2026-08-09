"""Helpers shared by more than one of the gui test modules."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication, QMessageBox

from genshin_thumbnail_studio.gui import MainWindow, dialogs
from genshin_thumbnail_studio.models import Build


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


def live_build(name: str) -> Build:
    """The minimal live build a placement carries in these tests.

    `Placement.build` is what the renderer and the editor resolve a slot's art
    through, so a member filled in by hand needs one; the paths it derives are
    where `create_test_assets()` writes that character's files.
    """
    return Build(
        name=name,
        constellation=0,
        refinement=1,
        weapon_name="Weapon",
        costume_id=None,
        art_url="https://example.invalid/art.png",
        weapon_url="https://example.invalid/weapon.png",
    )


def write_build_files(root: Path, build: Build) -> None:
    """Write art and weapon images where `build` says they belong under `root`.

    That is all "this slot has its art" means now, so a test that wants a filled
    slot publishes the files rather than filling a dict.
    """
    art_path = build.art_path(root)
    art_path.parent.mkdir(parents=True, exist_ok=True)
    art = Image.new("RGBA", (1200, 900), (25, 70, 100, 255))
    ImageDraw.Draw(art).ellipse((250, 80, 950, 850), fill=(130, 180, 220, 255))
    art.save(art_path)
    weapon_path = build.weapon_path(root)
    weapon_path.parent.mkdir(parents=True, exist_ok=True)
    weapon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(weapon).polygon([(128, 10), (190, 220), (128, 190), (66, 220)], fill="white")
    weapon.save(weapon_path)


def create_test_assets(root: Path, names: list[str]) -> list[Build]:
    """Publish each name's live build under the cache root `root`.

    The window's `art_root` is what a test passes here, because that is the root
    the editor and the renderer resolve every slot's files under; the returned
    builds are the ones `fill_window_teams()` puts on the placements.
    """
    builds = [live_build(name) for name in names]
    for build in builds:
        write_build_files(root, build)
    return builds


def fill_window_teams(window: MainWindow, names: list[str]) -> None:
    """Write the names straight onto the placements, with their live build.

    Bypasses `member_changed()`, so the build the editor would resolve there has
    to be put on the placement here.
    """
    members = [member for team in window.project.teams for member in team]
    for member, name in zip(members, names, strict=False):
        member.name = name
        member.build = live_build(name)


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
