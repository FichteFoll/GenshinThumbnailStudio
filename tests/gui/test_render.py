"""Tests for `MainWindow`'s throttled preview rendering."""

import itertools
import time
from pathlib import Path

import pytest
from PIL import Image

from genshin_thumbnail_studio.gui import MainWindow
from genshin_thumbnail_studio.gui.render_job import RenderJob

from .helpers import close_ignoring_unsaved_changes, create_test_assets, fill_window_teams, qapp, wait_for_render


def test_dispatch_render_marks_stale_while_job_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    started_jobs: list[RenderJob] = []

    def fake_start(job: RenderJob) -> None:
        started_jobs.append(job)

    monkeypatch.setattr(window._thread_pool, "start", fake_start)

    window._render_job_running = True
    window._dispatch_render()

    assert window._render_stale is True
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
    window._render_token = 5
    stale_token = 3
    fake_image = Image.new("RGB", (1280, 720), (200, 40, 40))
    window._on_render_finished(stale_token, fake_image, None)

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

    window._dispatch_render()
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

    assert not window._render_timer.isActive()

    window._on_asset_ready("furina", all_assets["furina"])

    # Only the first of several builds' assets has arrived, but the GUI is
    # already render-able: it does not wait for the whole batch.
    assert set(window.assets) == {"furina"}
    assert window._render_timer.isActive()

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
    assert window._render_timer.isActive()

    # Imitate a drag: many calls in quick succession, with a little wall-clock
    # time between them so a restart would show up as a jump back up.
    remaining = [window._render_timer.remainingTime()]
    for _ in range(5):
        time.sleep(0.005)
        window.schedule_render()
        assert window._render_timer.isActive()
        remaining.append(window._render_timer.remainingTime())

    assert all(later <= earlier for earlier, later in itertools.pairwise(remaining)), remaining
    assert remaining[-1] < remaining[0], remaining

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_schedule_render_without_assets_is_a_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    names = ["Furina", "Nahida"]
    fill_window_teams(window, names)

    # With assets, the very same call does start the timer, so the assertion
    # below really is about the `self.assets` guard and not about some other
    # reason for the timer to stay idle.
    window.assets = create_test_assets(tmp_path / "assets", names)
    window.schedule_render()
    assert window._render_timer.isActive()

    window._render_timer.stop()
    window.assets = {}

    window.schedule_render()

    assert not window._render_timer.isActive()

    close_ignoring_unsaved_changes(window, app, monkeypatch)
