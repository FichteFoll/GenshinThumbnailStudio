"""Tests for `gui.history.PlacementHistory`, needing no Qt environment.

`PlacementHistory` is Qt-free: it constructs no widget and needs no display, so
these tests run without `QT_QPA_PLATFORM` or `QTWEBENGINE_CHROMIUM_FLAGS` being
set. (PySide6 still ends up imported, because reaching `gui.history` executes
the `gui` package's facade, but nothing here uses it.)
"""

from genshin_thumbnail_studio.gui.history import HISTORY_LIMIT, PlacementHistory, Teams
from genshin_thumbnail_studio.models import Placement


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
