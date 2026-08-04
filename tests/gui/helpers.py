from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from genshin_thumbnail_studio.gui import MainWindow
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
            build_md5=str(index),
            last_build_update=None,
            art_url="https://example.invalid/art.png",
            weapon_url="https://example.invalid/weapon.png",
        )
        assets[name.casefold()] = Asset(build, art_path, weapon_path)
    return assets


def fill_window_teams(window: MainWindow, names: list[str]) -> None:
    members = [member for team in window.project.teams for member in team]
    for member, name in zip(members, names, strict=False):
        member.name = name


def wait_for_render(window: MainWindow, app: QApplication) -> None:
    """Block until the background render job dispatched by the window has finished."""
    for _ in range(200):
        if not window._render_job_running:
            return
        window._thread_pool.waitForDone(50)
        app.processEvents()
    raise AssertionError("render job did not finish in time")
