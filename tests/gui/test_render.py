"""Tests for `MainWindow`'s throttled preview rendering."""

import itertools
import time
from pathlib import Path

import pytest
from PIL import Image

from genshin_thumbnail_studio.gui import MainWindow, asset_loader
from genshin_thumbnail_studio.gui.render_job import RenderJob
from genshin_thumbnail_studio.models import Asset, Build

from .helpers import close_ignoring_unsaved_changes, create_test_assets, fill_window_teams, qapp, wait_for_render


def test_dispatch_render_marks_stale_while_job_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    started_jobs: list[RenderJob] = []

    def fake_start(job: RenderJob) -> None:
        started_jobs.append(job)

    monkeypatch.setattr(window._thread_pool, "start", fake_start)

    window._render.running = True
    window._render.dispatch()

    assert window._render.stale is True
    assert started_jobs == []

    window.close()
    app.processEvents()


def test_stale_token_result_does_not_update_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    baseline_pixmap = window.preview._pixmap

    # Simulate a render dispatched at an older token, with newer state having
    # since been requested (token bumped past the in-flight job's token).
    window._render.token = 5
    stale_token = 3
    fake_image = Image.new("RGB", (1280, 720), (200, 40, 40))
    window._render._on_job_finished(stale_token, fake_image, None)

    assert window.preview._pixmap is baseline_pixmap

    window.close()
    app.processEvents()


def test_dispatch_render_end_to_end_sets_preview_pixmap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
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
    fill_window_teams(window, names)
    window.assets = create_test_assets(tmp_path / "assets", names)

    window._render.dispatch()
    wait_for_render(window, app)

    assert window.preview._pixmap is not None
    assert not window.preview._pixmap.isNull()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_on_asset_ready_populates_incrementally_and_schedules_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    names = ["Furina", "Nahida"]
    fill_window_teams(window, names)
    window.assets = {}
    all_assets = create_test_assets(tmp_path / "assets", names)

    # The window schedules its own placeholder render on construction; clear
    # that one so the timer below can only have been started by the asset.
    window._render.timer.stop()
    assert not window._render.timer.isActive()

    window._on_asset_ready("furina", all_assets["furina"])

    # Only the first of several builds' assets has arrived, but the GUI is
    # already render-able: it does not wait for the whole batch.
    assert set(window.assets) == {"furina"}
    assert window._render.timer.isActive()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_schedule_render_throttles_instead_of_restarting_the_timer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    names = ["Furina", "Nahida"]
    fill_window_teams(window, names)
    window.assets = create_test_assets(tmp_path / "assets", names)

    window.schedule_render()
    assert window._render.timer.isActive()

    # Imitate a drag: many calls in quick succession, with a little wall-clock
    # time between them so a restart would show up as a jump back up.
    remaining = [window._render.timer.remainingTime()]
    for _ in range(5):
        time.sleep(0.005)
        window.schedule_render()
        assert window._render.timer.isActive()
        remaining.append(window._render.timer.remainingTime())

    assert all(later <= earlier for earlier, later in itertools.pairwise(remaining)), remaining
    assert remaining[-1] < remaining[0], remaining

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_schedule_render_without_assets_starts_the_timer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    # A window that has downloaded nothing at all still renders: every slot
    # becomes a placeholder panel rather than nothing being drawn.
    window.assets = {}
    window._render.timer.stop()

    window.schedule_render()

    assert window._render.timer.isActive()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_fresh_window_schedules_its_first_render_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No user action is required to obtain a preview: the constructor asks for one."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    assert window._render.timer.isActive()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_switching_modes_schedules_a_render_instead_of_blanking_the_canvas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    window._render.dispatch()
    wait_for_render(window, app)
    rendered = window.preview._pixmap
    assert rendered is not None and not rendered.isNull()
    window._render.timer.stop()

    window.controls_panel.stygian_radio.setChecked(True)

    # The new mode's blank teams have a placeholder rendering of their own, so
    # the canvas keeps the old frame until that render lands, rather than
    # being emptied.
    assert window.project.mode == "stygian"
    assert window._render.timer.isActive()
    assert window.preview._pixmap is rendered

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_closing_the_window_stops_rendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A render must not be scheduled or dispatched into a window being torn down.

    Both jobs signal the GUI thread across a queued connection, so draining the
    pool in `closeEvent` leaves their slots in the event queue; `client.close()`
    then spins the loops that deliver them.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    close_ignoring_unsaved_changes(window, app, monkeypatch)

    assert window._closing is True
    assert not window._render.timer.isActive()

    started_jobs: list[RenderJob] = []
    monkeypatch.setattr(window._thread_pool, "start", started_jobs.append)

    window.schedule_render()
    window._render.dispatch()
    # A download can outlive the drain and land here mid-teardown.
    window._on_asset_ready("furina", create_test_assets(tmp_path / "assets", ["Furina"])["furina"])

    assert not window._render.timer.isActive()
    assert started_jobs == []
    assert window.assets == {}


def test_arriving_art_makes_its_slot_editable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A portrait the user cannot touch is not what the download was for.

    The placement controls and the preview's inert-slot set are both derived in
    `sync_controls()`, so an asset arriving outside any edit handler has to
    trigger one or the slot keeps behaving like the placeholder it just stopped
    being.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    assets = create_test_assets(tmp_path / "assets", ["Furina"])
    fill_window_teams(window, ["Furina"])
    window.select_slot(0, 0)

    assert window.x_slider.isEnabled() is False
    assert window.preview._filled == set()

    window._on_asset_ready("furina", assets["furina"])

    assert window.x_slider.isEnabled() is True
    assert window.zoom_slider.isEnabled() is True
    assert window.reset_button.isEnabled() is True
    assert (0, 0) in window.preview._filled

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_fresh_window_renders_a_placeholder_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    assert window.builds == {}
    assert window.assets == {}

    window._render.dispatch()
    wait_for_render(window, app)

    assert window.preview._pixmap is not None
    assert not window.preview._pixmap.isNull()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_typing_a_member_name_downloads_its_art_in_the_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    assets = create_test_assets(tmp_path / "assets", ["Furina"])
    window.builds = {"furina": assets["furina"].build}
    requested: list[list[str]] = []

    def fake_download_assets(
        builds: list[Build],
        root: Path,
        progress: object = None,
        on_asset: object = None,
    ) -> dict[str, Asset]:
        requested.append([build.name for build in builds])
        if callable(on_asset):
            on_asset("furina", assets["furina"])
        return assets

    monkeypatch.setattr(asset_loader, "download_assets", fake_download_assets)

    window._member_changed(0, 0, "Furina")
    # The download runs on the window's own pool, and its `asset_ready` crosses
    # back to the GUI thread as a queued signal.
    window._thread_pool.waitForDone(5000)
    app.processEvents()

    assert requested == [["Furina"]]
    assert set(window.assets) == {"furina"}

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_render_mixes_portraits_and_placeholders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
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
    fill_window_teams(window, names)
    window.assets = create_test_assets(tmp_path / "assets", names[:1])

    window._render.dispatch()
    wait_for_render(window, app)

    # The per-panel pixels are asserted in tests/renderer/test_panels.py; what
    # matters here is that a partially filled team renders at all, which is
    # what the manual preview step used to refuse.
    assert window.preview._pixmap is not None
    assert not window.preview._pixmap.isNull()

    close_ignoring_unsaved_changes(window, app, monkeypatch)
