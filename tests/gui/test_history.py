"""Tests for `gui.history`, both the Qt-free history and its controller.

`PlacementHistory` itself constructs no widget, but the `HistoryController`
tests below build a `QWidget` parent and a `QShortcut`, so this module as a whole
does need the offscreen platform that `tests/gui/conftest.py` sets.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from PySide6.QtCore import QDeadlineTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from genshin_thumbnail_studio.gui.history import (
    HISTORY_DEBOUNCE_MS,
    HISTORY_LIMIT,
    HistoryController,
    PlacementHistory,
    Teams,
)
from genshin_thumbnail_studio.models import DEFAULT_ZOOM, Asset, Build, Placement, Project

from .helpers import qapp


def _teams(offset_x: float = 0.0, zoom: float = 1.0, name: str = "Furina") -> Teams:
    return [[Placement(name=name, offset_x=offset_x, zoom=zoom), Placement(name="Nahida")]]


def test_undo_returns_the_previous_state_and_redo_the_committed_one() -> None:
    history = PlacementHistory(_teams(0.1, 1.0))

    assert history.commit(_teams(0.4, 1.5)) is True

    undone = history.undo()
    assert undone is not None
    assert (undone[0][0].offset_x, undone[0][0].zoom) == (0.1, 1.0)

    redone = history.redo()
    assert redone is not None
    assert (redone[0][0].offset_x, redone[0][0].zoom) == (0.4, 1.5)


def test_undo_at_the_baseline_and_redo_at_the_tip_return_none() -> None:
    history = PlacementHistory(_teams())

    assert history.can_undo is False
    assert history.can_redo is False
    assert history.undo() is None
    assert history.redo() is None

    history.commit(_teams(0.3))
    assert history.can_undo is True
    assert history.redo() is None


def test_committing_an_unchanged_state_is_a_no_op() -> None:
    history = PlacementHistory(_teams(0.2))

    assert history.commit(_teams(0.2)) is False

    assert history.can_undo is False
    assert history.can_redo is False


def test_a_commit_after_an_undo_discards_the_redo_tail() -> None:
    history = PlacementHistory(_teams(0.1))
    history.commit(_teams(0.2))
    history.undo()
    assert history.can_redo is True

    history.commit(_teams(0.3))

    assert history.can_redo is False
    undone = history.undo()
    assert undone is not None
    assert undone[0][0].offset_x == 0.1


def test_the_history_keeps_at_most_its_limit_of_states() -> None:
    history = PlacementHistory(_teams(0.0), limit=3)
    for step in range(1, 6):
        history.commit(_teams(step / 10))

    reached = [0.5]
    while (undone := history.undo()) is not None:
        reached.append(undone[0][0].offset_x)

    # Three retained states: the last two commits plus the oldest survivor, 0.3.
    assert reached == [0.5, 0.4, 0.3]


def test_the_default_limit_is_fifty() -> None:
    assert HISTORY_LIMIT == 50


def test_stored_states_are_isolated_from_the_live_placements() -> None:
    baseline = _teams(0.1)
    history = PlacementHistory(baseline)
    edited = _teams(0.4)
    history.commit(edited)

    # Mutating the live teams after they were seeded or committed must not
    # rewrite the stored states.
    baseline[0][0].offset_x = 9.0
    edited[0][0].offset_x = 9.0

    undone = history.undo()
    assert undone is not None
    assert undone[0][0].offset_x == 0.1

    # Nor may mutating a handed-out state affect a later undo/redo.
    undone[0][0].offset_x = 9.0
    redone = history.redo()
    assert redone is not None
    assert redone[0][0].offset_x == 0.4
    again = history.undo()
    assert again is not None
    assert again[0][0].offset_x == 0.1


def test_replace_current_rewrites_the_state_in_place_and_keeps_the_redo_tail() -> None:
    history = PlacementHistory(_teams(0.1))
    history.commit(_teams(0.2))
    history.undo()

    history.replace_current(_teams(0.11))

    # The tail survives, so a redo still reaches the committed state.
    assert history.can_redo is True
    redone = history.redo()
    assert redone is not None
    assert redone[0][0].offset_x == 0.2
    undone = history.undo()
    assert undone is not None
    assert undone[0][0].offset_x == 0.11


def test_reset_drops_the_history_and_reseeds_the_baseline() -> None:
    history = PlacementHistory(_teams(0.1))
    history.commit(_teams(0.2))

    history.reset(_teams(0.7))

    assert history.can_undo is False
    assert history.can_redo is False
    history.commit(_teams(0.8))
    undone = history.undo()
    assert undone is not None
    assert undone[0][0].offset_x == 0.7


@dataclass
class StubState:
    """The minimal `EditorState` the controller needs."""

    project: Project
    builds: dict[str, Build] = field(default_factory=dict)
    assets: dict[str, Asset] = field(default_factory=dict)


@dataclass
class Host:
    """A stand-in for `MainWindow`: the state, a parent widget and the callback.

    Keeping the window out of these tests keeps them independent of the wiring
    that the window-side commit adds.
    """

    controller: HistoryController
    state: StubState
    parent: QWidget
    restored: list[None] = field(default_factory=list)

    @property
    def member(self) -> Placement:
        return self.state.project.teams[0][0]


@pytest.fixture
def host() -> Iterator[Host]:
    qapp()
    state = StubState(project=Project.blank("abyss"))
    state.project.teams[0][0].name = "Furina"
    parent = QWidget()
    restored: list[None] = []
    controller = HistoryController(state, parent, lambda: restored.append(None))
    yield Host(controller=controller, state=state, parent=parent, restored=restored)
    parent.deleteLater()
    qapp().processEvents()


def test_the_debounce_interval_is_six_hundred_milliseconds() -> None:
    assert HISTORY_DEBOUNCE_MS == 600


def test_a_scheduled_edit_only_snapshots_once_the_debounce_fires(host: Host) -> None:
    host.member.offset_x = 0.2
    host.controller.schedule()
    host.member.offset_x = 0.3
    host.controller.schedule()

    # The timer has not fired yet, so nothing is undoable.
    assert host.controller._history.can_undo is False

    # Fire the debounce deterministically instead of waiting for the timer.
    host.controller.commit_now()

    host.controller.undo()
    assert host.member.offset_x == 0.0
    # A single state for the whole edit, so there is nothing left to undo.
    assert host.controller._history.can_undo is False


def test_the_debounce_timer_itself_commits_when_it_fires(host: Host) -> None:
    """Drive the real `QTimer`, so the `timeout` wiring cannot be deleted unnoticed.

    The tests above fire the debounce by calling `commit_now()` directly, which
    keeps them deterministic but would pass just as well against a controller
    whose timer is connected to nothing.
    """
    host.controller._timer.setInterval(10)
    host.member.offset_x = 0.2
    host.controller._timer.start()

    deadline = QDeadlineTimer(2000)
    while host.controller._timer.isActive() and not deadline.hasExpired():
        qapp().processEvents()

    assert host.controller._timer.isActive() is False
    assert host.controller._history.can_undo is True


def test_scheduling_again_restarts_the_debounce_rather_than_letting_it_run_out(host: Host) -> None:
    """A debounce, not a throttle: a second edit must push the deadline out."""
    host.controller.schedule()
    host.controller._timer.setInterval(HISTORY_DEBOUNCE_MS - 200)
    shortened = host.controller._timer.remainingTime()

    host.controller.schedule()

    assert host.controller._timer.isSingleShot() is True
    assert host.controller._timer.interval() == HISTORY_DEBOUNCE_MS
    assert host.controller._timer.remainingTime() > shortened


def test_undo_restores_the_previous_framing_and_notifies_the_host(host: Host) -> None:
    host.member.offset_x = 0.25
    host.member.zoom = 1.4
    host.controller.commit_now()

    host.controller.undo()

    assert (host.member.offset_x, host.member.zoom) == (0.0, DEFAULT_ZOOM["abyss"])
    assert len(host.restored) == 1


def test_redo_returns_to_the_edited_framing(host: Host) -> None:
    host.member.offset_x = 0.25
    host.controller.commit_now()
    host.controller.undo()

    host.controller.redo()

    assert host.member.offset_x == 0.25
    assert len(host.restored) == 2


def test_undo_with_nothing_to_undo_does_not_notify_the_host(host: Host) -> None:
    host.controller.undo()

    assert host.restored == []


def test_both_redo_bindings_and_the_undo_binding_are_installed(host: Host) -> None:
    sequences = [shortcut.key() for shortcut in host.parent.findChildren(QShortcut)]

    assert QKeySequence("Ctrl+Z") in sequences
    assert QKeySequence("Ctrl+Y") in sequences
    assert QKeySequence("Ctrl+Shift+Z") in sequences


def test_a_focused_text_field_keeps_its_own_undo(host: Host, monkeypatch: pytest.MonkeyPatch) -> None:
    """The window-level `Ctrl+Z` reaches the controller before a focused
    `QLineEdit` sees it, so the controller has to hand the key back.

    The focus is monkeypatched rather than set through `setFocus()`, because
    focus on an unmapped window is not reliable under `QT_QPA_PLATFORM=offscreen`.
    """
    line_edit = QLineEdit(host.parent)
    line_edit.setText("70000001")
    monkeypatch.setattr(QApplication, "focusWidget", staticmethod(lambda: line_edit))
    host.member.offset_x = 0.25
    host.controller.commit_now()

    host.controller.undo()

    assert host.member.offset_x == 0.25
    assert host.restored == []
