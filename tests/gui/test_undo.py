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

from .helpers import TEAM_NAMES, close_ignoring_unsaved_changes, fill_window_teams, qapp

# `_sync_controls` quantizes every offset to per-mille of the panel, so a
# restored offset can differ from the recorded one by half a step.
OFFSET_TOLERANCE = 0.001


def _approx(expected: float) -> Any:
    """Wraps `pytest.approx`, whose own parameters are unannotated in pytest itself."""
    return pytest.approx(expected, abs=OFFSET_TOLERANCE)  # pyright: ignore[reportUnknownMemberType]


def _window_with_history_baseline() -> MainWindow:
    """A window with a filled lineup as the history's baseline.

    The names are written straight onto the placements, which bypasses the edit
    handlers, so the history is re-seeded afterwards exactly as opening a
    project does. No assets are attached: undo needs none, and without them
    `schedule_render()` no-ops, so no background render outlives the window.
    """
    window = MainWindow()
    fill_window_teams(window, TEAM_NAMES)
    window._rebuild_team_fields()
    window.select_slot(0, 0)
    window._history.reset()
    return window


def test_each_settled_drag_is_its_own_undo_step(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline()
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
    window = _window_with_history_baseline()
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
    window = _window_with_history_baseline()
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
    window = _window_with_history_baseline()
    start_zoom = window.current_member().zoom

    window.zoom_slider.setValue(round(start_zoom * 100) + 15)
    window._history.commit_now()
    assert window.current_member().zoom == _approx(start_zoom + 0.15)

    window._history.undo()

    assert window.current_member().zoom == _approx(start_zoom)
    assert window.zoom_slider.value() == round(start_zoom * 100)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_flip_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline()

    window.flip_check.setChecked(True)
    window._history.commit_now()

    window._history.undo()

    assert window.current_member().flip is False
    assert window.flip_check.isChecked() is False

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_character_name_change_is_undone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline()

    window.team_combos[0][0].setCurrentText("Klee")
    window._history.commit_now()
    assert window.project.teams[0][0].name == "Klee"

    window._history.undo()

    assert window.project.teams[0][0].name == TEAM_NAMES[0]
    assert window.team_combos[0][0].currentText() == TEAM_NAMES[0]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_slot_reorder_is_undone_without_an_explicit_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = _window_with_history_baseline()
    window.project.teams[0][0].offset_x = 0.1
    window.project.teams[1][3].zoom = 1.35
    window._history.reset()

    window.reorder_slots((0, 0), (1, 3))
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
    window = _window_with_history_baseline()

    window._on_slot_drag_started(0, 0)
    window._on_slot_drag_hover(1, 3)
    window._on_slot_drag_hover(0, 2)
    window._on_slot_drag_ended(True)

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
    window = _window_with_history_baseline()
    start_x = window.current_member().offset_x
    window.drag_placement(30, 0)
    window._history.commit_now()

    window._on_slot_drag_started(0, 0)
    window._on_slot_drag_hover(1, 3)
    window._on_slot_drag_ended(False)

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

    window.stygian_radio.setChecked(True)
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
    window = _window_with_history_baseline()
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
    window = _window_with_history_baseline()

    # An edit still pending when the drag starts must be settled, not left armed.
    window.drag_placement(30, 0)
    assert window._history._timer.isActive() is True

    window._on_slot_drag_started(0, 0)
    assert window._history._timer.isActive() is False

    window._on_slot_drag_hover(1, 3)
    assert window._history._timer.isActive() is False

    window._on_slot_drag_ended(False)
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
    window = _window_with_history_baseline()
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
