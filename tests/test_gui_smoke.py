import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication

from genshin_thumbnail_studio.gui import MainWindow
from genshin_thumbnail_studio.models import Asset, Build


def test_main_window_starts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Genshin Thumbnail Studio"
    assert len(window.team_combos) == 2
    window.close()
    app.processEvents()


def _create_test_assets(directory: Path, names: list[str]) -> dict[str, Asset]:
    directory.mkdir(parents=True, exist_ok=True)
    assets = {}
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


def _fill_window_teams(window: MainWindow, names: list[str]) -> None:
    members = [member for team in window.project.teams for member in team]
    for member, name in zip(members, names):
        member.name = name


def test_dispatch_render_marks_stale_while_job_running(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    started_jobs = []
    monkeypatch.setattr(window._thread_pool, "start", lambda job: started_jobs.append(job))

    window._render_job_running = True
    window._dispatch_render()

    assert window._render_stale is True
    assert started_jobs == []

    window.close()
    app.processEvents()


def test_stale_token_result_does_not_update_preview(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    baseline_pixmap = window.preview._pixmap

    # Simulate a render dispatched at an older token, with newer state having
    # since been requested (token bumped past the in-flight job's token).
    window._render_token = 5
    stale_token = 3
    fake_image = Image.new("RGB", (1280, 720), (200, 40, 40))
    window._on_render_finished(stale_token, fake_image, None)

    assert window.preview._pixmap is baseline_pixmap

    window.close()
    app.processEvents()


def test_dispatch_render_end_to_end_sets_preview_pixmap(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    names = [
        "Furina",
        "Nahida",
        "Bennett",
        "Xingqiu",
        "Raiden Shogun",
        "Kazuha",
        "Ganyu",
        "Zhongli",
    ]
    _fill_window_teams(window, names)
    window.assets = _create_test_assets(tmp_path / "assets", names)

    window._dispatch_render()

    for _ in range(200):
        if not window._render_job_running:
            break
        window._thread_pool.waitForDone(50)
        app.processEvents()
    else:
        raise AssertionError("render job did not finish in time")

    assert window.preview._pixmap is not None
    assert not window.preview._pixmap.isNull()

    window.close()
    app.processEvents()


def test_swap_slots_exchanges_placements(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    first = window.project.teams[0][0]
    second = window.project.teams[1][3]
    first.name = "Furina"
    first.fx = 0.42
    first.zoom = 1.20
    second.name = "Nahida"
    second.fx = 0.61
    second.zoom = 0.95

    window.swap_slots((0, 0), (1, 3))

    swapped_first = window.project.teams[0][0]
    swapped_second = window.project.teams[1][3]
    assert swapped_first.name == "Nahida"
    assert swapped_first.fx == 0.61
    assert swapped_first.zoom == 0.95
    assert swapped_second.name == "Furina"
    assert swapped_second.fx == 0.42
    assert swapped_second.zoom == 1.20

    window.close()
    app.processEvents()
