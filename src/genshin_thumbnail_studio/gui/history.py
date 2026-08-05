"""A bounded undo/redo history over the teams of `Placement`s.

Qt-free: a plain list of states plus an index into it, so the undo semantics
can be tested without a widget.

A state is a deep copy of `Project.teams`, which carries every member's name,
framing and color as well as their order. The rest of the `Project` (mode, uid,
output settings, active team) is deliberately not part of a state: undoing must
not switch the mode, which would discard all teams.
"""

from __future__ import annotations

import copy

from ..models import Placement

HISTORY_LIMIT = 50

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
