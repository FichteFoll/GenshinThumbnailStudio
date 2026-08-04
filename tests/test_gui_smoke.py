import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication, QMessageBox

from genshin_thumbnail_studio import gui
from genshin_thumbnail_studio.gui import MainWindow
from genshin_thumbnail_studio.models import Asset, Build, Project
from genshin_thumbnail_studio.renderer import art_pixel_size, max_offset, panel_target_size
from genshin_thumbnail_studio.storage import load_profile_cache, save_profile_cache, save_project


def make_build(name: str) -> Build:
    return Build(
        name=name,
        constellation=1,
        refinement=2,
        weapon_name="Splendor of Tranquil Waters",
        costume_id=None,
        build_id=f"{name}-build",
        build_md5="0123456789abcdef",
        last_build_update="2026-08-01T12:00:00+00:00",
        art_url=f"https://enka.network/ui/{name}.png",
        weapon_url="https://enka.network/ui/weapon.png",
        element="Hydro",
        rarity=5,
        weapon_rarity=5,
        raw={"name": name},
    )


TEAM_NAMES = ["Furina", "Nahida", "Xilonen", "Neuvillette", "Kazuha", "Bennett", "Xiangling", "Zhongli"]


def write_project(path: Path, uid: str) -> None:
    project = Project.blank("abyss", uid)
    for index, member in enumerate(member for team in project.teams for member in team):
        member.name = TEAM_NAMES[index]
    save_project(project, path)


class StubMessageBox:
    """Records dialogs instead of showing them; ``clickedButton`` always simulates Cancel."""

    ButtonRole = QMessageBox.ButtonRole
    StandardButton = QMessageBox.StandardButton
    instances: list["StubMessageBox"] = []

    def __init__(self, parent=None) -> None:  # noqa: ANN001 - Qt parent
        self.title = ""
        self.text = ""
        self.executed = False
        type(self).instances.append(self)

    def setWindowTitle(self, title: str) -> None:
        self.title = title

    def setText(self, text: str) -> None:
        self.text = text

    def addButton(self, *args) -> object:
        return object()

    def exec(self) -> None:
        self.executed = True

    def clickedButton(self) -> object | None:
        return None

    @staticmethod
    def critical(parent, title, text) -> None:  # noqa: ANN001 - Qt parent
        raise AssertionError(f"unexpected error dialog: {title}: {text}")

    @staticmethod
    def information(parent, title, text) -> None:  # noqa: ANN001 - Qt parent
        return None


class ForbiddenMessageBox(StubMessageBox):
    def __init__(self, parent=None) -> None:  # noqa: ANN001 - Qt parent
        raise AssertionError("unexpected message box")

    @staticmethod
    def information(parent, title, text) -> None:  # noqa: ANN001 - Qt parent
        raise AssertionError(f"unexpected info dialog: {title}: {text}")


def prepare_cached_open(tmp_path, monkeypatch, last_update: datetime) -> tuple[MainWindow, str]:
    uid = "700000042"
    builds = [make_build(name) for name in TEAM_NAMES]
    save_profile_cache(uid, builds, last_update)
    project_path = tmp_path / "project.json"
    write_project(project_path, uid)
    window = MainWindow()
    assets = _create_test_assets(tmp_path / "assets", TEAM_NAMES)
    monkeypatch.setattr(gui, "download_assets", lambda *args, **kwargs: assets)
    monkeypatch.setattr(
        gui.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )
    return window, uid


def wait_for_render(window: MainWindow, app: QApplication) -> None:
    """Block until the background render job dispatched by the window has finished."""
    for _ in range(200):
        if not window._render_job_running:
            return
        window._thread_pool.waitForDone(50)
        app.processEvents()
    raise AssertionError("render job did not finish in time")


def test_open_project_loads_cached_profile_and_previews(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, "QMessageBox", ForbiddenMessageBox)
    window, uid = prepare_cached_open(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(minutes=5))

    window.open_project()
    wait_for_render(window, app)

    assert window.project.uid == uid
    assert sorted(window.builds) == sorted(name.casefold() for name in TEAM_NAMES)
    assert window.preview._pixmap is not None

    window.close()
    app.processEvents()


def test_open_project_with_stale_cache_offers_refresh(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    StubMessageBox.instances = []
    monkeypatch.setattr(gui, "QMessageBox", StubMessageBox)
    window, _ = prepare_cached_open(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(hours=2))
    refreshed = []
    monkeypatch.setattr(window.client, "refresh_profile", lambda *args, **kwargs: refreshed.append(True))
    monkeypatch.setattr(
        window.client, "load_profile", lambda *args, **kwargs: pytest.fail("live profile load must not happen")
    )

    window.open_project()
    wait_for_render(window, app)

    assert len(StubMessageBox.instances) == 1
    assert "2.0 hours" in StubMessageBox.instances[0].text
    assert not refreshed
    assert sorted(window.builds) == sorted(name.casefold() for name in TEAM_NAMES)
    assert window.preview._pixmap is not None

    window.close()
    app.processEvents()


def test_open_project_without_cache_shows_hint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui, "QMessageBox", ForbiddenMessageBox)
    project_path = tmp_path / "project.json"
    write_project(project_path, "900000099")
    monkeypatch.setattr(
        gui.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )
    window = MainWindow()

    window.open_project()

    assert not window.builds
    assert "no cached profile" in window.statusBar().currentMessage()

    window.close()
    app.processEvents()


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
    wait_for_render(window, app)

    assert window.preview._pixmap is not None
    assert not window.preview._pixmap.isNull()

    window.close()
    app.processEvents()


def test_on_asset_ready_populates_incrementally_and_schedules_render(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    names = ["Furina", "Nahida"]
    _fill_window_teams(window, names)
    window.assets = {}
    all_assets = _create_test_assets(tmp_path / "assets", names)

    assert not window._render_timer.isActive()

    window._on_asset_ready("furina", all_assets["furina"])

    # Only the first of several builds' assets has arrived, but the GUI is
    # already render-able: it does not wait for the whole batch.
    assert set(window.assets) == {"furina"}
    assert window._render_timer.isActive()

    window.close()
    app.processEvents()


def test_schedule_render_throttles_instead_of_restarting_the_timer(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    names = ["Furina", "Nahida"]
    _fill_window_teams(window, names)
    window.assets = _create_test_assets(tmp_path / "assets", names)

    window.schedule_render()
    assert window._render_timer.isActive()

    # Imitate a drag: many calls in quick succession, with a little wall-clock
    # time between them so a restart would show up as a jump back up.
    remaining = [window._render_timer.remainingTime()]
    for _ in range(5):
        time.sleep(0.005)
        window.schedule_render()
        assert window._render_timer.isActive()
        remaining.append(window._render_timer.remainingTime())

    assert all(later <= earlier for earlier, later in zip(remaining, remaining[1:])), remaining
    assert remaining[-1] < remaining[0], remaining

    window.close()
    app.processEvents()


def test_schedule_render_without_assets_is_a_noop(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    names = ["Furina", "Nahida"]
    _fill_window_teams(window, names)

    # With assets, the very same call does start the timer, so the assertion
    # below really is about the `self.assets` guard and not about some other
    # reason for the timer to stay idle.
    window.assets = _create_test_assets(tmp_path / "assets", names)
    window.schedule_render()
    assert window._render_timer.isActive()

    window._render_timer.stop()
    window.assets = {}

    window.schedule_render()

    assert not window._render_timer.isActive()

    window.close()
    app.processEvents()


def test_swap_slots_exchanges_placements(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    first = window.project.teams[0][0]
    second = window.project.teams[1][3]
    first.name = "Furina"
    first.offset_x = 0.10
    first.zoom = 1.20
    second.name = "Nahida"
    second.offset_x = -0.08
    second.zoom = 0.95

    window.swap_slots((0, 0), (1, 3))

    swapped_first = window.project.teams[0][0]
    swapped_second = window.project.teams[1][3]
    assert swapped_first.name == "Nahida"
    assert swapped_first.offset_x == -0.08
    assert swapped_first.zoom == 0.95
    assert swapped_second.name == "Furina"
    assert swapped_second.offset_x == 0.10
    assert swapped_second.zoom == 1.20

    window.close()
    app.processEvents()


def _prepare_export_window(window: MainWindow, tmp_path: Path, names: list[str]) -> None:
    assets = _create_test_assets(tmp_path / "assets", names)
    window.builds = {key: asset.build for key, asset in assets.items()}
    _fill_window_teams(window, names)
    window._rebuild_team_fields()
    window.assets = assets


def test_export_abyss_writes_the_file_chosen_in_the_save_dialog(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.output_name.setText("prefilled")

    monkeypatch.setattr(gui, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        gui.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: pytest.fail("abyss export must not ask for a folder")),
    )
    chosen = tmp_path / "out" / "chosen.png"
    default_names = []

    def fake_save_dialog(parent, title, default_name, name_filter):  # noqa: ANN001 - Qt parent
        default_names.append(default_name)
        return str(chosen), "PNG (*.png)"

    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.export()

    assert [Path(name).name for name in default_names] == ["prefilled.png"]
    assert chosen.exists()
    assert list(chosen.parent.glob("*.png")) == [chosen]
    assert window.output_name.text() == "chosen"
    assert window.project.output_name == "chosen"

    window.close()
    app.processEvents()


def test_export_stygian_still_asks_for_a_folder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    # Switching the mode replaces window.project, so fill the teams afterwards.
    window.stygian_radio.setChecked(True)
    names = TEAM_NAMES + ["Xingqiu", "Ganyu", "Raiden Shogun", "Yelan"]
    _prepare_export_window(window, tmp_path, names)
    window.output_name.setText("bosses")

    monkeypatch.setattr(gui, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        gui.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: pytest.fail("stygian export must not ask for a file name")),
    )
    directory = tmp_path / "out"
    monkeypatch.setattr(gui.QFileDialog, "getExistingDirectory", staticmethod(lambda *args, **kwargs: str(directory)))

    window.export()

    for index in (1, 2, 3):
        assert (directory / f"bosses_boss{index}.png").exists()

    window.close()
    app.processEvents()


def test_export_defaults_to_the_opened_project_folder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    project_dir = tmp_path / "projects"
    project_dir.mkdir()
    project_file = project_dir / "thumbnail-project.json"
    write_project(project_file, "700000042")

    window = MainWindow()
    monkeypatch.setattr(gui, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(gui.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(project_file), "")))
    window.open_project()

    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.output_name.setText("prefilled")
    default_paths = []

    def fake_save_dialog(parent, title, default_path, name_filter):  # noqa: ANN001 - Qt parent
        default_paths.append(default_path)
        return str(tmp_path / "out" / "chosen.png"), "PNG (*.png)"

    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.export()

    assert default_paths == [str(project_dir / "prefilled.png")]

    window.close()
    app.processEvents()


def test_export_defaults_to_the_saved_project_folder(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    project_dir = tmp_path / "saved"
    project_dir.mkdir()
    project_file = project_dir / "thumbnail-project.json"

    window = MainWindow()
    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.output_name.setText("prefilled")

    monkeypatch.setattr(gui, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(project_file), "")))
    window.save_project()

    default_paths = []

    def fake_save_dialog(parent, title, default_path, name_filter):  # noqa: ANN001 - Qt parent
        default_paths.append(default_path)
        return str(tmp_path / "out" / "chosen.png"), "PNG (*.png)"

    monkeypatch.setattr(gui.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.export()

    assert default_paths == [str(project_dir / "prefilled.png")]

    window.close()
    app.processEvents()


def test_offset_sliders_are_signed_and_span_the_reachable_range(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    _fill_window_teams(window, TEAM_NAMES)
    window.assets = _create_test_assets(tmp_path / "assets", TEAM_NAMES)
    window.select_slot(0, 0)

    member = window.current_member()
    art_size = art_pixel_size(str(window.assets[member.name.casefold()].art_path))
    max_x, max_y = max_offset(art_size, True, member.zoom)

    # Truncated, so the slider end never exceeds what the renderer can reach.
    assert window.x_slider.maximum() == int(max_x * 1000)
    assert window.x_slider.maximum() / 1000 <= max_x
    assert window.x_slider.minimum() == -window.x_slider.maximum()
    assert window.x_slider.maximum() > 0
    assert window.y_slider.maximum() == int(max_y * 1000)
    assert window.y_slider.maximum() / 1000 <= max_y
    assert window.y_slider.minimum() == -window.y_slider.maximum()

    window.x_slider.setValue(window.x_slider.minimum())
    assert window.current_member().offset_x == pytest.approx(-max_x, abs=1e-3)
    assert window.x_value.text().startswith("-")

    window.x_slider.setValue(0)
    assert window.current_member().offset_x == 0.0
    assert window.x_value.text() == "+0%"

    window.close()
    app.processEvents()


def _window_with_assets(tmp_path, names: list[str]) -> MainWindow:
    window = MainWindow()
    _fill_window_teams(window, names)
    window.assets = _create_test_assets(tmp_path / "assets", names)
    window.select_slot(0, 0)
    return window


# ``_sync_controls`` writes the integer slider values back onto the member, so
# every offset is quantized to per-mille of the panel, a step of at most 0.5
# canvas pixels and hence a rounding error of at most half that.
OFFSET_TOLERANCE = 0.001


def test_drag_moves_the_offsets_by_one_canvas_pixel_per_mouse_pixel(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = _window_with_assets(tmp_path, TEAM_NAMES)

    target_w, target_h = panel_target_size(True)
    member = window.current_member()
    before_x, before_y = member.offset_x, member.offset_y

    window.drag_placement(30, 30)

    member = window.current_member()
    assert member.offset_x - before_x == pytest.approx(30 / target_w, abs=OFFSET_TOLERANCE)
    assert member.offset_y - before_y == pytest.approx(30 / target_h, abs=OFFSET_TOLERANCE)

    window.close()
    app.processEvents()


def test_drag_displaces_the_portrait_equally_on_both_axes(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = _window_with_assets(tmp_path, TEAM_NAMES)

    target_w, target_h = panel_target_size(True)
    member = window.current_member()
    before_x, before_y = member.offset_x, member.offset_y

    window.drag_placement(30, 30)

    member = window.current_member()
    pixels_x = (member.offset_x - before_x) * target_w
    pixels_y = (member.offset_y - before_y) * target_h
    # A per-mille of the panel bounds the slider quantization on either axis.
    tolerance = OFFSET_TOLERANCE * max(target_w, target_h)
    assert pixels_x == pytest.approx(pixels_y, abs=tolerance)
    assert pixels_x == pytest.approx(30, abs=tolerance)

    window.close()
    app.processEvents()


def test_drag_past_the_reachable_range_stops_at_the_bounds(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = _window_with_assets(tmp_path, TEAM_NAMES)

    max_x, max_y = window._offset_bounds(window.current_member())

    window.drag_placement(10_000, 10_000)

    member = window.current_member()
    assert member.offset_x == pytest.approx(max_x, abs=OFFSET_TOLERANCE)
    assert member.offset_y == pytest.approx(max_y, abs=OFFSET_TOLERANCE)

    window.drag_placement(-20_000, -20_000)

    member = window.current_member()
    assert member.offset_x == pytest.approx(-max_x, abs=OFFSET_TOLERANCE)
    assert member.offset_y == pytest.approx(-max_y, abs=OFFSET_TOLERANCE)

    window.close()
    app.processEvents()


def test_load_profile_persists_profile_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    uid = "700000042"
    builds = [make_build("Furina"), make_build("Nahida")]
    last_update = datetime(2026, 8, 3, 10, 30, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(window.client, "load_profile", lambda *args, **kwargs: (builds, 5.0, last_update))
    window.uid_edit.setText(uid)

    window.load_profile()

    cached = load_profile_cache(uid)
    assert cached is not None
    cached_builds, cached_last_update = cached
    assert cached_builds == builds
    assert cached_last_update == last_update

    window.close()
    app.processEvents()
