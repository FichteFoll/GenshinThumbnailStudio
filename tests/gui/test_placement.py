"""Tests for `MainWindow`'s placement editing (drag, wheel, slider, reset)."""

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap

from genshin_thumbnail_studio.gui import MainWindow
from genshin_thumbnail_studio.models import Placement
from genshin_thumbnail_studio.renderer import art_pixel_size, max_offset, panel_target_size

from .helpers import (
    TEAM_NAMES,
    close_ignoring_unsaved_changes,
    create_test_assets,
    fill_window_teams,
    live_build,
    qapp,
)


def _approx(expected: float, abs: float) -> Any:
    """Wraps `pytest.approx`, whose own `expected`/`rel`/`abs` parameters are
    unannotated in pytest itself, not fixable from our code."""
    return pytest.approx(expected, abs=abs)  # pyright: ignore[reportUnknownMemberType]


def test_reorder_slots_shifts_placements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    first = window.project.teams[0][0]
    second = window.project.teams[1][3]
    first.name = "Furina"
    first.offset_x = 0.10
    first.zoom = 1.20
    second.name = "Nahida"
    second.offset_x = -0.08
    second.zoom = 0.95

    window.team_fields.reorder((0, 0), (1, 3))

    shifted = window.project.teams[1][2]
    moved = window.project.teams[1][3]
    assert shifted.name == "Nahida"
    assert shifted.offset_x == -0.08
    assert shifted.zoom == 0.95
    assert moved.name == "Furina"
    assert moved.offset_x == 0.10
    assert moved.zoom == 1.20
    assert window.team_fields.combos[1][2].currentText() == "Nahida"
    assert window.team_fields.combos[1][3].currentText() == "Furina"
    assert window.selected == (1, 3)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_slot_drag_hover_reorders_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    fill_window_teams(window, TEAM_NAMES)
    create_test_assets(window.art_root, TEAM_NAMES)

    window.team_fields.on_drag_started(0, 0)
    window.team_fields.on_drag_hover(1, 3)

    assert window.project.teams[1][3].name == TEAM_NAMES[0]
    assert window.team_fields.combos[1][3].currentText() == TEAM_NAMES[0]
    assert window.selected == (1, 3)
    assert window._render.timer.isActive()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_slot_drag_cancelled_reverts_to_the_original_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    fill_window_teams(window, TEAM_NAMES)

    window.team_fields.on_drag_started(0, 0)
    window.team_fields.on_drag_hover(1, 3)
    window.team_fields.on_drag_hover(0, 2)
    window.team_fields.on_drag_ended(False)

    names = [member.name for team in window.project.teams for member in team]
    assert names == TEAM_NAMES
    combo_names = [combo.currentText() for row in window.team_fields.combos for combo in row]
    assert combo_names == TEAM_NAMES

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_slot_drag_accepted_keeps_the_live_arrangement(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    fill_window_teams(window, TEAM_NAMES)

    window.team_fields.on_drag_started(0, 0)
    window.team_fields.on_drag_hover(1, 3)
    window.team_fields.on_drag_ended(True)

    assert window.project.teams[1][3].name == TEAM_NAMES[0]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_offset_sliders_are_signed_and_span_the_reachable_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    fill_window_teams(window, TEAM_NAMES)
    create_test_assets(window.art_root, TEAM_NAMES)
    window.select_slot(0, 0)

    member = window.current_member()
    assert member.build is not None
    art_size = art_pixel_size(str(member.build.art_path(window.art_root)))
    max_x, max_y = max_offset(art_size, True, member.zoom)

    # Truncated, so the slider end never exceeds what the renderer can reach.
    assert window.editor_panel.x_slider.maximum() == int(max_x * 1000)
    assert window.editor_panel.x_slider.maximum() / 1000 <= max_x
    assert window.editor_panel.x_slider.minimum() == -window.editor_panel.x_slider.maximum()
    assert window.editor_panel.x_slider.maximum() > 0
    assert window.editor_panel.y_slider.maximum() == int(max_y * 1000)
    assert window.editor_panel.y_slider.maximum() / 1000 <= max_y
    assert window.editor_panel.y_slider.minimum() == -window.editor_panel.y_slider.maximum()

    window.editor_panel.x_slider.setValue(window.editor_panel.x_slider.minimum())
    assert window.current_member().offset_x == _approx(-max_x, 1e-3)
    assert window.editor_panel.x_value.text().startswith("-")

    window.editor_panel.x_slider.setValue(0)
    assert window.current_member().offset_x == 0.0
    assert window.editor_panel.x_value.text() == "+0%"

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def _window_with_assets(names: list[str]) -> MainWindow:
    window = MainWindow()
    fill_window_teams(window, names)
    create_test_assets(window.art_root, names)
    window.select_slot(0, 0)
    return window


# ``sync_controls`` writes the integer slider values back onto the member, so
# every offset is quantized to per-mille of the panel, a step of at most 0.5
# canvas pixels and hence a rounding error of at most half that.
OFFSET_TOLERANCE = 0.001


def test_drag_moves_the_offsets_by_one_canvas_pixel_per_mouse_pixel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_assets(TEAM_NAMES)

    target_w, target_h = panel_target_size(True)
    member = window.current_member()
    before_x, before_y = member.offset_x, member.offset_y

    window.drag_placement(30, 30)

    member = window.current_member()
    assert member.offset_x - before_x == _approx(30 / target_w, OFFSET_TOLERANCE)
    assert member.offset_y - before_y == _approx(30 / target_h, OFFSET_TOLERANCE)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_drag_displaces_the_portrait_equally_on_both_axes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_assets(TEAM_NAMES)

    target_w, target_h = panel_target_size(True)
    member = window.current_member()
    before_x, before_y = member.offset_x, member.offset_y

    window.drag_placement(30, 30)

    member = window.current_member()
    pixels_x = (member.offset_x - before_x) * target_w
    pixels_y = (member.offset_y - before_y) * target_h
    # A per-mille of the panel bounds the slider quantization on either axis.
    tolerance = OFFSET_TOLERANCE * max(target_w, target_h)
    assert pixels_x == _approx(pixels_y, tolerance)
    assert pixels_x == _approx(30, tolerance)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_drag_past_the_reachable_range_stops_at_the_bounds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_assets(TEAM_NAMES)

    max_x, max_y = window._placement.offset_bounds(window.current_member())

    window.drag_placement(10_000, 10_000)

    member = window.current_member()
    assert member.offset_x == _approx(max_x, OFFSET_TOLERANCE)
    assert member.offset_y == _approx(max_y, OFFSET_TOLERANCE)

    window.drag_placement(-20_000, -20_000)

    member = window.current_member()
    assert member.offset_x == _approx(-max_x, OFFSET_TOLERANCE)
    assert member.offset_y == _approx(-max_y, OFFSET_TOLERANCE)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_flip_check_toggles_the_selected_member(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_assets(TEAM_NAMES)

    assert window.current_member().flip is False

    window.editor_panel.flip_check.setChecked(True)
    assert window.current_member().flip is True

    window.editor_panel.flip_check.setChecked(False)
    assert window.current_member().flip is False

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_sync_controls_shows_the_flip_without_writing_it_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_assets(TEAM_NAMES)

    window.current_member().flip = True
    # Asserting the member still reads True would hold even without the
    # _updating_controls guard, since the handler would write back the same
    # value. Only the write side proves the handler did not run.
    writes: list[int] = []
    monkeypatch.setattr(window, "_save_current_preset", lambda: writes.append(1))
    window.sync_controls()

    assert window.editor_panel.flip_check.isChecked() is True
    assert window.current_member().flip is True
    assert writes == []

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_selecting_another_slot_shows_that_slots_flip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_assets(TEAM_NAMES)

    window.editor_panel.flip_check.setChecked(True)

    window.select_slot(0, 1)
    assert window.editor_panel.flip_check.isChecked() is False
    assert window.current_member().flip is False

    window.select_slot(0, 0)
    assert window.editor_panel.flip_check.isChecked() is True

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_flip_round_trips_through_the_presets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_assets(TEAM_NAMES)
    window.builds = {name.casefold(): [live_build(name)] for name in TEAM_NAMES}

    window.editor_panel.flip_check.setChecked(True)

    fresh = Placement(name=window.current_member().name)
    window._presets.apply_to(window, fresh)
    assert fresh.flip is True

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_reset_placement_clears_the_flip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_assets(TEAM_NAMES)

    window.editor_panel.flip_check.setChecked(True)

    window.reset_placement()

    assert window.current_member().flip is False
    assert window.editor_panel.flip_check.isChecked() is False

    close_ignoring_unsaved_changes(window, app, monkeypatch)


# Slot (0, 0) is the only one with downloaded art; every other slot renders as a
# placeholder panel and must therefore be inert.
FILLED_SLOT = (0, 0)
PLACEHOLDER_SLOT = (0, 3)


def _window_with_one_filled_slot() -> MainWindow:
    window = MainWindow()
    fill_window_teams(window, TEAM_NAMES)
    create_test_assets(window.art_root, TEAM_NAMES[:1])
    window.select_slot(*FILLED_SLOT)
    return window


def test_clicking_a_placeholder_slot_does_not_select_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_one_filled_slot()
    # `_image_rect()` is empty without a pixmap, which would swallow the click
    # before it ever reached the placeholder check.
    window.editor_panel.preview.resize(1280, 720)
    window.editor_panel.preview.set_preview(QPixmap(1280, 720))
    emitted: list[tuple[int, int]] = []

    def record(team: int, slot: int) -> None:
        emitted.append((team, slot))

    window.editor_panel.preview.slot_selected.connect(record)

    team, slot = PLACEHOLDER_SLOT
    center = QPointF(slot * 320 + 160, team * 360 + 180)
    window.editor_panel.preview.mousePressEvent(
        QMouseEvent(
            QEvent.Type.MouseButtonPress,
            center,
            center,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
    )

    assert emitted == []
    assert window.selected == FILLED_SLOT

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_dragging_a_placeholder_slot_does_not_move_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_one_filled_slot()
    window.select_slot(*PLACEHOLDER_SLOT)
    member = window.current_member()
    before_x, before_y = member.offset_x, member.offset_y

    window.drag_placement(40, 40)

    assert member.offset_x == before_x
    assert member.offset_y == before_y

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_zooming_a_placeholder_slot_does_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_one_filled_slot()
    window.select_slot(*PLACEHOLDER_SLOT)
    member = window.current_member()
    before_zoom = member.zoom

    window.change_zoom(0.1)

    assert member.zoom == before_zoom

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_placement_controls_are_disabled_for_a_placeholder_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_one_filled_slot()
    editor = window.editor_panel
    controls = [editor.x_slider, editor.y_slider, editor.zoom_slider, editor.flip_check, editor.reset_button]

    window.select_slot(*PLACEHOLDER_SLOT)
    assert [control.isEnabled() for control in controls] == [False] * len(controls)

    window.select_slot(*FILLED_SLOT)
    assert [control.isEnabled() for control in controls] == [True] * len(controls)

    close_ignoring_unsaved_changes(window, app, monkeypatch)
