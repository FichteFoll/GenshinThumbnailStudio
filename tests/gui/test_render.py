"""Tests for `MainWindow`'s throttled preview rendering."""

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

import genshin_thumbnail_studio.enka.assets as enka_assets
from genshin_thumbnail_studio.gui import MainWindow, asset_loader
from genshin_thumbnail_studio.gui.render_job import RenderJob
from genshin_thumbnail_studio.gui.render_pipeline import RENDER_THROTTLE_MS
from genshin_thumbnail_studio.models import Build, Placement
from genshin_thumbnail_studio.renderer import (
    BASE_H,
    BASE_W,
    badge_geometry,
    clear_render_cache,
    find_font,
    panel_background,
    panel_metrics,
    panel_origin,
    panel_target_size,
    render_preview,
)

from .helpers import (
    close_ignoring_unsaved_changes,
    create_test_assets,
    fill_window_teams,
    live_build,
    qapp,
    wait_for_render,
    write_build_files,
)


def renders_as_placeholder(window: MainWindow, member: Placement) -> bool:
    """Whether slot (0, 0) of the window's compact preview is a bare placeholder.

    Probes the same point `tests/renderer/test_panels.py` does, mapped from
    panel-local to canvas coordinates the way the panel is pasted, and compares
    it against the panel background a placeholder is made of.
    """
    clear_render_cache()  # the panel cache outlives a single test
    preview = render_preview(window.project, window.art_root)
    slant = panel_metrics(compact=True, scale=1)[2]
    local_point = (188, 180)
    rendered = preview.getpixel((local_point[0] - slant, local_point[1]))
    expected = panel_background(panel_target_size(compact=True), member.color, compact=True)
    bare = expected.getpixel(local_point)
    assert isinstance(rendered, tuple) and isinstance(bare, tuple)
    return rendered[:3] == bare[:3]


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

    baseline_pixmap = window.editor_panel.preview._pixmap

    # Simulate a render dispatched at an older token, with newer state having
    # since been requested (token bumped past the in-flight job's token).
    window._render.token = 5
    stale_token = 3
    fake_image = Image.new("RGB", (1280, 720), (200, 40, 40))
    window._render._on_job_finished(stale_token, fake_image, None)

    assert window.editor_panel.preview._pixmap is baseline_pixmap

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
    create_test_assets(window.art_root, names)

    window._render.dispatch()
    wait_for_render(window, app)

    assert window.editor_panel.preview._pixmap is not None
    assert not window.editor_panel.preview._pixmap.isNull()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_on_asset_ready_populates_incrementally_and_schedules_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    names = ["Furina", "Nahida"]
    fill_window_teams(window, names)
    furina = create_test_assets(window.art_root, names[:1])[0]

    # The window schedules its own placeholder render on construction; clear
    # that one so the timer below can only have been started by the asset.
    window._render.timer.stop()
    assert not window._render.timer.isActive()

    window._on_asset_ready(furina)

    # Only the first of several builds' art has arrived, but the GUI is already
    # render-able: it does not wait for the whole batch.
    assert window._filled_slots() == {(0, 0)}
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
    create_test_assets(window.art_root, names)

    # The constructor already started the throttle timer, which may be overdue
    # by now on a slow machine; start from a quiet pipeline instead.
    window._render.timer.stop()
    wait_for_render(window, app)
    token = window._render.token

    # Imitate a drag: calls about 10 ms apart, or up to 16 ms where the sleep
    # resolution is coarse, always shorter than the throttle.
    # A throttle dispatches a render within the burst, whereas a debounce
    # (restarting the timer on every call) never fires inside it.
    deadline = time.monotonic() + 4 * RENDER_THROTTLE_MS / 1000
    while time.monotonic() < deadline:
        window.schedule_render()
        app.processEvents()
        time.sleep(0.01)

    assert window._render.token > token

    wait_for_render(window, app)
    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_schedule_render_without_assets_starts_the_timer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    # A window that has downloaded nothing at all still renders: every slot
    # becomes a placeholder panel rather than nothing being drawn.
    assert window._filled_slots() == set()
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
    rendered = window.editor_panel.preview._pixmap
    assert rendered is not None and not rendered.isNull()
    window._render.timer.stop()

    window.controls_panel.stygian_radio.setChecked(True)

    # The new mode's blank teams have a placeholder rendering of their own, so
    # the canvas keeps the old frame until that render lands, rather than
    # being emptied.
    assert window.project.mode == "stygian"
    assert window._render.timer.isActive()
    assert window.editor_panel.preview._pixmap is rendered

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_closing_the_window_stops_rendering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A render must not be scheduled or dispatched into a window being torn down.

    Both jobs signal the GUI thread across a queued connection, so draining the
    pool in `closeEvent` leaves their slots in the event queue, which the event
    loop then delivers.
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
    window._on_asset_ready(create_test_assets(window.art_root, ["Furina"])[0])

    assert not window._render.timer.isActive()
    assert started_jobs == []


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
    fill_window_teams(window, ["Furina"])
    window.select_slot(0, 0)

    assert window.editor_panel.x_slider.isEnabled() is False
    assert window.editor_panel.preview._filled == set()

    window._on_asset_ready(create_test_assets(window.art_root, ["Furina"])[0])

    assert window.editor_panel.x_slider.isEnabled() is True
    assert window.editor_panel.zoom_slider.isEnabled() is True
    assert window.editor_panel.reset_button.isEnabled() is True
    assert (0, 0) in window.editor_panel.preview._filled

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_changing_a_slots_build_renders_a_placeholder_until_the_new_art_arrives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R5: a slot whose build changes falls back to a placeholder.

    The new build's art lives at a path of its own, so the slot has nothing to
    draw until that file exists - and it must not keep drawing the previous
    build's portrait in the meantime.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    monkeypatch.setattr(window.asset_loader, "ensure", lambda: None)

    live = live_build("Furina")
    vape = replace(
        live,
        build_name="Vape",
        art_url="https://example.invalid/furina-vape-art.png",
        weapon_url="https://example.invalid/furina-vape-weapon.png",
    )
    window.builds = {"furina": [live, vape]}
    write_build_files(window.art_root, live)
    fill_window_teams(window, ["Furina"])
    window.select_slot(0, 0)
    window.sync_controls()

    member = window.project.teams[0][0]
    assert (0, 0) in window._filled_slots()
    assert not renders_as_placeholder(window, member)

    window.build_selected(0, 0, vape)

    assert (0, 0) not in window._filled_slots()
    assert renders_as_placeholder(window, member)

    write_build_files(window.art_root, vape)
    window.sync_controls()

    assert (0, 0) in window._filled_slots()
    assert not renders_as_placeholder(window, member)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


STORED_ART_COLOR = (200, 40, 40, 255)
STORED_WEAPON_COLOR = (240, 200, 40, 255)
PROFILE_ART_COLOR = (40, 60, 200, 255)
PROFILE_WEAPON_COLOR = (40, 200, 120, 255)


def _image_writer(colors: dict[str, tuple[int, int, int, int]]) -> Callable[[str, Path], None]:
    """A `http.download()` stand-in that paints a flat colour per URL.

    Every URL gets a colour of its own, so a slot drawing another slot's file
    shows up as the wrong colour rather than as an indistinguishable portrait.
    """

    def fake_download(url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        size = (256, 256) if "weapon" in url else (1200, 900)
        # Explicit format: the destination is a `.part` path whose suffix
        # Pillow cannot map to one.
        Image.new("RGBA", size, colors[url]).save(destination, format="PNG")

    return fake_download


def _nearer(pixel: tuple[int, int, int], first: tuple[int, int, int, int], second: tuple[int, int, int, int]) -> bool:
    """Whether `pixel` is closer to `first` than to `second` in RGB."""
    def distance(color: tuple[int, int, int, int]) -> int:
        return sum((pixel[channel] - color[channel]) ** 2 for channel in range(3))

    return distance(first) < distance(second)


def _panel_pixel(preview: Image.Image, index: int) -> tuple[int, int, int]:
    """The portrait pixel of slot `index` in the compact preview's first row.

    The same panel-local point `renders_as_placeholder()` probes, mapped onto
    the canvas the way `render_image()` pastes the panel.
    """
    row_height, _, slant = panel_metrics(compact=True, scale=1)
    origin_x, origin_y = panel_origin(index, 0, row_height, BASE_W / 4, slant)
    pixel = preview.getpixel((origin_x + 188, origin_y + 180))
    assert isinstance(pixel, tuple)
    return (pixel[0], pixel[1], pixel[2])


def _weapon_icon_pixel(preview: Image.Image, index: int) -> tuple[int, int, int]:
    """The centre of slot `index`'s weapon-icon circle, mirroring add_badges'
    own geometry for the first (compact) abyss row."""
    row_height, _, _ = panel_metrics(compact=True, scale=1)
    step = BASE_W / 4
    font = find_font(38)
    draw = ImageDraw.Draw(Image.new("RGBA", (BASE_W, BASE_H), (0, 0, 0, 0)))
    center = round(index * step + step / 2)
    top_y = row_height - 68
    geometry = badge_geometry(draw, "C0R1", font, center_x=center, top_y=top_y, scale=1, compact=True)
    circle_x0, circle_y0, circle_x1, circle_y1 = geometry.circle
    pixel = preview.getpixel(((circle_x0 + circle_x1) // 2, (circle_y0 + circle_y1) // 2))
    assert isinstance(pixel, tuple)
    return (pixel[0], pixel[1], pixel[2])


def test_two_builds_of_one_character_sharing_a_build_name_keep_their_own_art_and_badges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6: two slots holding builds of one character never trade art or badges.

    Both builds are named "Vape", which is all the old `Build.key` looked at, so
    the second slot's files were never fetched and the two slots shared one
    entry in the downloaded-art dict. A build resolves its own paths from its
    URLs, so nothing about them collides any more.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    stored = Build(
        name="Furina",
        constellation=0,
        refinement=1,
        weapon_name="Fountain",
        costume_id=None,
        build_name="Vape",
        art_url="https://example.invalid/furina-stored-art.png",
        weapon_url="https://example.invalid/furina-stored-weapon.png",
    )
    profile = replace(
        stored,
        constellation=6,
        art_url="https://example.invalid/furina-profile-art.png",
        weapon_url="https://example.invalid/furina-profile-weapon.png",
    )
    window.builds = {"furina": [profile]}
    monkeypatch.setattr(
        enka_assets,
        "download",
        _image_writer(
            {
                stored.art_url: STORED_ART_COLOR,
                stored.weapon_url: STORED_WEAPON_COLOR,
                profile.art_url: PROFILE_ART_COLOR,
                profile.weapon_url: PROFILE_WEAPON_COLOR,
            }
        ),
    )

    for slot, build in enumerate((stored, profile)):
        member = window.project.teams[0][slot]
        member.name = "Furina"
        member.build = build

    window.asset_loader.ensure()
    window._thread_pool.waitForDone(5000)
    app.processEvents()

    # Both builds are fetched: deduplication is by URL pair, not by build name.
    assert stored.art_path(window.art_root).exists()
    assert profile.art_path(window.art_root).exists()
    assert {(0, 0), (0, 1)} <= window._filled_slots()

    clear_render_cache()  # the panel cache outlives a single test
    preview = render_preview(window.project, window.art_root)

    assert _nearer(_panel_pixel(preview, 0), STORED_ART_COLOR, PROFILE_ART_COLOR)
    assert _nearer(_panel_pixel(preview, 1), PROFILE_ART_COLOR, STORED_ART_COLOR)
    assert _nearer(_weapon_icon_pixel(preview, 0), STORED_WEAPON_COLOR, PROFILE_WEAPON_COLOR)
    assert _nearer(_weapon_icon_pixel(preview, 1), PROFILE_WEAPON_COLOR, STORED_WEAPON_COLOR)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_fresh_window_renders_a_placeholder_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    assert window.builds == {}
    assert window._filled_slots() == set()

    window._render.dispatch()
    wait_for_render(window, app)

    assert window.editor_panel.preview._pixmap is not None
    assert not window.editor_panel.preview._pixmap.isNull()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_typing_a_member_name_downloads_its_art_in_the_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    window.builds = {"furina": [live_build("Furina")]}
    requested: list[list[str]] = []

    def fake_download_assets(
        builds: list[Build],
        root: Path,
        progress: object = None,
        on_build: Callable[[Build], None] | None = None,
    ) -> None:
        requested.append([build.name for build in builds])
        for build in builds:
            write_build_files(root, build)
            if on_build:
                on_build(build)

    monkeypatch.setattr(asset_loader, "download_assets", fake_download_assets)

    window.member_changed(0, 0, "Furina")
    # The download runs on the window's own pool, and its `asset_ready` crosses
    # back to the GUI thread as a queued signal.
    window._thread_pool.waitForDone(5000)
    app.processEvents()

    assert requested == [["Furina"]]
    assert window._filled_slots() == {(0, 0)}

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
    create_test_assets(window.art_root, names[:1])

    window._render.dispatch()
    wait_for_render(window, app)

    # The per-panel pixels are asserted in tests/renderer/test_panels.py; what
    # matters here is that a partially filled team renders at all, which is
    # what the manual preview step used to refuse.
    assert window.editor_panel.preview._pixmap is not None
    assert not window.editor_panel.preview._pixmap.isNull()

    close_ignoring_unsaved_changes(window, app, monkeypatch)
