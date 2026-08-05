"""A bounded undo/redo history over the teams of `Placement`s, and its Qt half.

`PlacementHistory` is Qt-free: a plain list of states plus an index into it, so
the undo semantics can be tested without a widget. `HistoryController` wires it
to the editor, debouncing the snapshots behind a `QTimer` and installing the
undo/redo shortcuts.

A state is a deep copy of `Project.teams`, which carries every member's name,
framing and color as well as their order. The rest of the `Project` (mode, uid,
output settings, active team) is deliberately not part of a state: undoing must
not switch the mode, which would discard all teams.
"""

from __future__ import annotations

import copy
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from ..models import Placement
from .state import EditorState

HISTORY_LIMIT = 50
HISTORY_DEBOUNCE_MS = 600

Teams = list[list[Placement]]


class PlacementHistory:
    """Undo/redo over at most `limit` retained team states.

    Every state stored or handed out is a deep copy, so a caller can never
    reach a stored state through the live `Placement` objects.
    """

    def __init__(self, teams: Teams, limit: int = HISTORY_LIMIT) -> None:
        self._limit = limit
        self._states: list[Teams] = [copy.deepcopy(teams)]
        self._index = 0

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._states) - 1

    def commit(self, teams: Teams) -> bool:
        """Record `teams` as a new state, unless it equals the current one.

        Returns whether a state was added.
        """
        # `Placement` is a dataclass, so `==` compares field by field.
        if teams == self._states[self._index]:
            return False
        del self._states[self._index + 1 :]
        self._states.append(copy.deepcopy(teams))
        del self._states[: max(0, len(self._states) - self._limit)]
        self._index = len(self._states) - 1
        return True

    def undo(self) -> Teams | None:
        """Step back one state and return it, or `None` at the baseline."""
        if not self.can_undo:
            return None
        self._index -= 1
        return copy.deepcopy(self._states[self._index])

    def redo(self) -> Teams | None:
        """Step forward one state and return it, or `None` at the tip."""
        if not self.can_redo:
            return None
        self._index += 1
        return copy.deepcopy(self._states[self._index])

    def reset(self, teams: Teams) -> None:
        """Drop the whole history and start over with `teams` as the baseline."""
        self._states = [copy.deepcopy(teams)]
        self._index = 0


class HistoryController(QObject):
    """The editor-facing half: a debounce timer, the shortcuts and the restore.

    It reads `state.project` freshly on every call and never caches it, because
    the window replaces the project wholesale in several places, see `state.py`.
    """

    def __init__(self, state: EditorState, parent: QWidget, on_restored: Callable[[], None]) -> None:
        super().__init__(parent)
        self._state = state
        self._on_restored = on_restored
        self._history = PlacementHistory(state.project.teams)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.commit_now)
        # Parented to `parent`, so Qt owns each shortcut's lifetime; the default
        # window context is what makes them fire from anywhere in the window.
        for sequence, handler in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo)):
            QShortcut(QKeySequence(sequence), parent).activated.connect(handler)

    def schedule(self) -> None:
        """Snapshot once the user has been idle for `HISTORY_DEBOUNCE_MS`.

        A debounce, not a throttle, unlike `MainWindow.schedule_render()` next to
        it at the same call sites: restarting the timer on every mouse-move event
        is the point here, so a whole drag becomes one undo step.
        """
        self._timer.start(HISTORY_DEBOUNCE_MS)

    def commit_now(self) -> None:
        """Snapshot the current teams immediately, cancelling any pending debounce."""
        self._timer.stop()
        self._history.commit(self._state.project.teams)

    def reset(self) -> None:
        """Re-seed the history with the current teams, dropping everything before."""
        self._timer.stop()
        self._history.reset(self._state.project.teams)

    def undo(self) -> None:
        if self._undo_focused_text_field(redo=False):
            return
        self.commit_now()
        self._restore(self._history.undo())

    def redo(self) -> None:
        if self._undo_focused_text_field(redo=True):
            return
        # A pending edit truncates the redo tail, so committing it first turns a
        # redo right after an edit into a no-op rather than a jump into a stale
        # future.
        self.commit_now()
        self._restore(self._history.redo())

    def _undo_focused_text_field(self, redo: bool) -> bool:
        """Delegate to a focused text field's own undo stack, if there is one.

        The window-level shortcut is dispatched before a focused `QLineEdit` sees
        the key, so typing into the UID field or an editable team combo would
        otherwise lose its own undo to the placement history.
        """
        widget = QApplication.focusWidget()
        if not isinstance(widget, QLineEdit):
            return False
        if redo:
            widget.redo()
        else:
            widget.undo()
        return True

    def _restore(self, teams: Teams | None) -> None:
        if teams is None:
            return
        self._state.project.teams = teams
        self._on_restored()
