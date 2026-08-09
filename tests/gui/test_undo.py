"""Tests for undo and redo of the placement and lineup edits made in `MainWindow`.

Unlike `test_history.py`, which drives `HistoryController` against a stand-in
host, these go through the real window, so they need the offscreen platform.

The debounce is driven deterministically by calling `commit_now()` wherever a
real user would simply go idle, so nothing here sleeps or spins the timer.
"""

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtGui import QKeySequence, QShortcut

from genshin_thumbnail_studio.gui import MainWindow

from .helpers import (
    TEAM_NAMES,
    close_ignoring_unsaved_changes,
    create_test_assets,
    fill_window_teams,
    live_build,
    publish_art,
    qapp,
)

# `sync_controls` quantizes every offset to per-mille of the panel, so a
# restored offset can differ from the recorded one by half a step.
OFFSET_TOLERANCE = 0.001


def _approx(expected: float) -> Any:
    """Wraps `pytest.approx`, whose own parameters are unannotated in pytest itself."""
    return pytest.approx(expected, abs=OFFSET_TOLERANCE)  # pyright: ignore[reportUnknownMemberType]


def _window_with_history_baseline(tmp_path: Path) -> MainWindow:
    """A window with a filled lineup as the history's baseline.

    The names are written straight onto the placements, which bypasses the edit
    handlers, so the history is re-seeded afterwards exactly as opening a
    project does. Art is attached for the selected slot only, since placement
    edits are refused on a slot that still renders as a placeholder; the other
    seven stay placeholders, which the renders the window schedules anyway draw
    and `close_ignoring_unsaved_changes()` then drains through `closeEvent`.
    """
    window = MainWindow()
    fill_window_teams(window, TEAM_NAMES)
    window.assets = create_test_assets(tmp_path / "assets", TEAM_NAMES[:1])
    publish_art(window.art_root, TEAM_NAMES[:1])
    window.rebuild_team_fields()
    window.select_slot(0, 0)
    window._history.reset()
    return window


def test_each_settled_drag_is_its_own_undo_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    start_x = window.current_member().offset_x

    window.drag_placement(30, 0)
    window._history.commit_now()
    after_first = window.current_member().offset_x
    window.drag_placement(30, 0)
    window._history.commit_now()
    after_second = window.current_member().offset_x
    assert after_second > after_first > start_x

    window._history.undo()
    assert window.current_member().offset_x == _approx(after_first)

    window._history.undo()
    assert window.current_member().offset_x == _approx(start_x)

    window._history.redo()
    assert window.current_member().offset_x == _approx(after_first)

    window._history.redo()
    assert window.current_member().offset_x == _approx(after_second)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_continuous_drag_collapses_into_one_undo_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    start_x = window.current_member().offset_x

    # Two drags without going idle in between: the debounce has not fired, so
    # they belong to the same undo step.
    window.drag_placement(30, 0)
    window.drag_placement(30, 0)
    window._history.commit_now()

    window._history.undo()
    assert window.current_member().offset_x == _approx(start_x)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_wheel_zoom_is_undone_and_redone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    start_zoom = window.current_member().zoom

    window.change_zoom(3)
    window._history.commit_now()
    zoomed = window.current_member().zoom
    assert zoomed != start_zoom

    window._history.undo()
    assert window.current_member().zoom == _approx(start_zoom)

    window._history.redo()
    assert window.current_member().zoom == _approx(zoomed)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_zoom_slider_change_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    start_zoom = window.current_member().zoom

    window.editor_panel.zoom_slider.setValue(round(start_zoom * 100) + 15)
    window._history.commit_now()
    assert window.current_member().zoom == _approx(start_zoom + 0.15)

    window._history.undo()

    assert window.current_member().zoom == _approx(start_zoom)
    assert window.editor_panel.zoom_slider.value() == round(start_zoom * 100)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_flip_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)

    window.editor_panel.flip_check.setChecked(True)
    window._history.commit_now()

    window._history.undo()

    assert window.current_member().flip is False
    assert window.editor_panel.flip_check.isChecked() is False

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_character_name_change_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)

    window.team_fields.combos[0][0].setCurrentText("Klee")
    window._history.commit_now()
    assert window.project.teams[0][0].name == "Klee"

    window._history.undo()

    assert window.project.teams[0][0].name == TEAM_NAMES[0]
    assert window.team_fields.combos[0][0].currentText() == TEAM_NAMES[0]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_slot_reorder_is_undone_without_an_explicit_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    window.project.teams[0][0].offset_x = 0.1
    window.project.teams[1][3].zoom = 1.35
    window._history.reset()

    window.team_fields.reorder((0, 0), (1, 3))
    assert window.project.teams[1][3].name == TEAM_NAMES[0]

    window._history.undo()

    names = [member.name for team in window.project.teams for member in team]
    assert names == TEAM_NAMES
    assert window.project.teams[0][0].offset_x == _approx(0.1)
    assert window.project.teams[1][3].zoom == _approx(1.35)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_whole_drag_gesture_is_a_single_undo_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)

    window.team_fields.on_drag_started(0, 0)
    window.team_fields.on_drag_hover(1, 3)
    window.team_fields.on_drag_hover(0, 2)
    window.team_fields.on_drag_ended(True)

    window._history.undo()
    names = [member.name for team in window.project.teams for member in team]
    assert names == TEAM_NAMES

    # Every hovered slot along the way was folded into that one step.
    window._history.undo()
    names = [member.name for team in window.project.teams for member in team]
    assert names == TEAM_NAMES

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_cancelled_drag_leaves_nothing_to_undo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    start_x = window.current_member().offset_x
    window.drag_placement(30, 0)
    window._history.commit_now()

    window.team_fields.on_drag_started(0, 0)
    window.team_fields.on_drag_hover(1, 3)
    window.team_fields.on_drag_ended(False)

    # The one undo left is the drag before the gesture, not a state the
    # cancelled reorder pushed.
    window._history.undo()

    names = [member.name for team in window.project.teams for member in team]
    assert names == TEAM_NAMES
    assert window.project.teams[0][0].offset_x == _approx(start_x)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_switching_the_mode_drops_the_previous_modes_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    # A clean window, so the mode switch does not put up the unsaved-changes prompt.
    window = MainWindow()

    window.controls_panel.stygian_radio.setChecked(True)
    window._history.undo()

    assert window.project.mode == "stygian"
    assert len(window.project.teams) == 3
    assert all(not member.name for team in window.project.teams for member in team)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_the_undo_and_redo_shortcuts_reach_the_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    sequences = [shortcut.key() for shortcut in window.findChildren(QShortcut)]

    assert QKeySequence("Ctrl+Z") in sequences
    assert QKeySequence("Ctrl+Y") in sequences
    assert QKeySequence("Ctrl+Shift+Z") in sequences

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_redo_survives_a_baseline_the_sliders_would_requantize(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Restoring re-quantizes the offsets, which must not count as a new edit.

    An unquantized baseline is the normal case, not a contrived one: applying a
    stored preset writes the raw pan result, so this is the plain
    load-profile, generate-preview, drag, undo, redo flow.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    window.current_member().offset_x = 0.0724
    window._history.reset()

    window.drag_placement(30, 0)
    window._history.commit_now()
    dragged_x = window.current_member().offset_x

    window._history.undo()
    window._history.redo()

    assert window.current_member().offset_x == _approx(dragged_x)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_no_debounce_is_left_pending_during_a_slot_drag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing may be scheduled mid-gesture, so a lingering drag cannot snapshot.

    A debounce firing while the user rests over a slot would record a
    half-finished arrangement, which a cancelled drag then reverts around,
    leaving the aborted reorder one `Ctrl+Z` away.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)

    # An edit still pending when the drag starts must be settled, not left armed.
    window.drag_placement(30, 0)
    assert window._history._timer.isActive() is True

    window.team_fields.on_drag_started(0, 0)
    assert window._history._timer.isActive() is False

    window.team_fields.on_drag_hover(1, 3)
    assert window._history._timer.isActive() is False

    window.team_fields.on_drag_ended(False)
    window._history.undo()
    names = [member.name for team in window.project.teams for member in team]
    assert names == TEAM_NAMES

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_undoing_back_to_a_name_re_requests_its_art(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A restored name must not leave its slot a placeholder for good.

    Clearing a name prunes its `Asset`, and a restore writes the name onto the
    combos before their signals are connected, so it reaches neither
    `member_changed` nor the `ensure()` at its end. Without a call of its own
    the slot would stay inert and refuse to export, with nothing downloading.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    restored: list[list[str]] = []
    monkeypatch.setattr(
        window.asset_loader, "ensure", lambda: restored.append(sorted(window.selected_build_keys()))
    )

    window.member_changed(0, 0, "")
    window._history.commit_now()
    assert window.assets == {}
    restored.clear()

    window._history.undo()

    assert window.current_member().name == TEAM_NAMES[0]
    assert restored == [sorted(f"{name.casefold()}|live" for name in TEAM_NAMES)]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_undo_resolves_a_build_onto_a_state_snapshotted_before_the_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A state recorded before the profile arrived carries no build snapshot.

    `Placement.build` is what the renderer resolves art through, and a restore
    reaches the combos before their signals are connected, so `member_changed`
    never runs to fill one in. Without a resolve of its own the slot would keep
    an empty `asset_key` and render as a placeholder for good, while still
    counting as filled everywhere the editor resolves through the builds map.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    window.member_changed(0, 0, TEAM_NAMES[0])  # No profile loaded, so no build.
    window._history.commit_now()
    assert window.current_member().asset_key == ""

    window.builds = {TEAM_NAMES[0].casefold(): [live_build(TEAM_NAMES[0])]}
    window.current_member().zoom = 1.4
    window._history.commit_now()

    window._history.undo()

    assert window.current_member().asset_key == f"{TEAM_NAMES[0].casefold()}|live"

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_art_arriving_mid_drag_leaves_the_debounce_disarmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule holds for the one edit the user does not make.

    Downloads run for seconds after a profile load, so an asset can land in the
    middle of a slot drag; the preset it re-applies must not re-arm the debounce
    `on_drag_started` just settled.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    arriving = create_test_assets(tmp_path / "late", TEAM_NAMES[1:2])

    window.team_fields.on_drag_started(0, 0)
    window.team_fields.on_drag_hover(1, 3)

    window._on_asset_ready(f"{TEAM_NAMES[1].casefold()}|live", arriving[f"{TEAM_NAMES[1].casefold()}|live"])

    assert window._history._timer.isActive() is False

    window.team_fields.on_drag_ended(False)
    window._history.undo()
    names = [member.name for team in window.project.teams for member in team]
    assert names == TEAM_NAMES

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def _activate(window: MainWindow, sequence: str) -> None:
    """Fire the shortcut bound to `sequence` as if the user had pressed it.

    `activated` is emitted directly rather than posting a key event, because an
    offscreen window never gains the focus real key delivery would need. It
    still proves which handler each binding is connected to, which asserting
    over the installed key sequences alone does not.
    """
    shortcut = next(s for s in window.findChildren(QShortcut) if s.key() == QKeySequence(sequence))
    shortcut.activated.emit()


@pytest.mark.parametrize("redo_sequence", ["Ctrl+Y", "Ctrl+Shift+Z"])
def test_each_shortcut_is_connected_to_the_direction_it_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, redo_sequence: str
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline(tmp_path)
    start_x = window.current_member().offset_x

    window.drag_placement(30, 0)
    window._history.commit_now()
    dragged_x = window.current_member().offset_x
    assert dragged_x > start_x

    _activate(window, "Ctrl+Z")
    assert window.current_member().offset_x == _approx(start_x)

    _activate(window, redo_sequence)
    assert window.current_member().offset_x == _approx(dragged_x)

    close_ignoring_unsaved_changes(window, app, monkeypatch)
