"""`TeamFieldsController`, the team slot combos and their drag reordering.

Fills the layout `ControlsPanel` provides with one `TeamSlotWidget` per slot,
keeps the combos in step with the project's teams, and turns a drag gesture over
them into a reorder plus exactly one undo step. Nothing here imports
`MainWindow`: what the controller needs from the editor is spelled out by the
`TeamFieldsEditor` Protocol below, which `MainWindow` satisfies structurally.
"""

from __future__ import annotations

import copy
from typing import Protocol

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QComboBox, QLabel, QLayout, QVBoxLayout

from ..models import Placement
from .history import HistoryController
from .state import EditorState
from .team_slots import TeamSlotWidget


def clear_layout(layout: QLayout) -> None:
    """Delete every widget and nested layout in `layout`, recursively."""
    while layout.count():
        item = layout.takeAt(0)
        if item is None:
            continue
        widget = item.widget()
        if widget:
            widget.deleteLater()
        else:
            sub_layout = item.layout()
            if sub_layout:
                clear_layout(sub_layout)


class TeamFieldsEditor(EditorState, Protocol):
    """What the team fields read and write on the editor.

    `MainWindow` satisfies it structurally; nothing has to declare it.
    Like the other collaborators, the controller reads `project` through the
    Protocol on every call rather than capturing it, because the window replaces
    it wholesale in several places; see `state.py`.
    """

    selected: tuple[int, int]

    def member_changed(self, team: int, slot: int, name: str) -> None: ...
    def sync_controls(self) -> None: ...
    def schedule_render(self) -> None: ...


class TeamFieldsController(QObject):
    """The team slot combos, their population and the drag reordering.

    Takes the `HistoryController` as a constructor argument like `ProjectFiles`
    does, which keeps `MainWindow._history` private.
    """

    def __init__(
        self,
        editor: TeamFieldsEditor,
        layout: QVBoxLayout,
        history: HistoryController,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._editor = editor
        self._layout = layout
        self._history = history
        self.combos: list[list[QComboBox]] = []
        self._drag_snapshot: list[list[Placement]] | None = None
        self._drag_position: tuple[int, int] | None = None

    @property
    def dragging(self) -> bool:
        """Whether a slot drag is in progress, during which nothing may be snapshotted."""
        return self._drag_position is not None

    def rebuild(self) -> None:
        project = self._editor.project
        team_layout = self._layout
        clear_layout(team_layout)
        self.combos = []
        for team_index, team in enumerate(project.teams):
            title = QLabel(f"{'Team' if project.mode == 'abyss' else 'Boss'} {team_index + 1}")
            title.setStyleSheet("font-weight: 600;")
            team_layout.addWidget(title)
            rows = QVBoxLayout()
            rows.setSpacing(4)
            row_combos: list[QComboBox] = []
            for slot_index, member in enumerate(team):
                combo = QComboBox()
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                combo.setPlaceholderText(f"Character {slot_index + 1}")
                if member.name:
                    combo.setCurrentText(member.name)

                def on_text_changed(value: str, t: int = team_index, s: int = slot_index) -> None:
                    self._editor.member_changed(t, s, value)

                combo.currentTextChanged.connect(on_text_changed)
                slot_widget = TeamSlotWidget(team_index, slot_index, combo)
                slot_widget.drag_started.connect(self.on_drag_started)
                slot_widget.drag_hover.connect(self.on_drag_hover)
                slot_widget.drag_ended.connect(self.on_drag_ended)
                rows.addWidget(slot_widget)
                row_combos.append(combo)
            team_layout.addLayout(rows)
            self.combos.append(row_combos)
        team_layout.addStretch(1)
        self.populate_items()

    def refresh_display(self) -> None:
        for team_index, row in enumerate(self.combos):
            for slot_index, combo in enumerate(row):
                name = self._editor.project.teams[team_index][slot_index].name
                if combo.currentText() != name:
                    combo.blockSignals(True)
                    combo.setCurrentText(name)
                    combo.blockSignals(False)

    def on_drag_started(self, team: int, slot: int) -> None:
        # Settle any edit still pending from before the drag, so its debounce
        # cannot fire mid-gesture and snapshot a half-finished reorder.
        self._history.commit_now()
        self._drag_snapshot = copy.deepcopy(self._editor.project.teams)
        self._drag_position = (team, slot)

    def on_drag_hover(self, team: int, slot: int) -> None:
        if self._drag_position is None or (team, slot) == self._drag_position:
            return
        self.reorder(self._drag_position, (team, slot))
        self._drag_position = (team, slot)

    def on_drag_ended(self, accepted: bool) -> None:
        if not accepted and self._drag_snapshot is not None:
            self._editor.project.teams = self._drag_snapshot
            self.refresh_display()
            self._editor.sync_controls()
            self._editor.schedule_render()
        self._drag_snapshot = None
        self._drag_position = None
        # A no-op after a cancelled drag, whose revert restored the last state.
        self._history.commit_now()

    def reorder(self, source: tuple[int, int], target: tuple[int, int]) -> None:
        if source == target:
            return
        editor = self._editor
        project = editor.project
        per_team = len(project.teams[0])
        members = [member for team in project.teams for member in team]
        source_index = source[0] * per_team + source[1]
        target_index = target[0] * per_team + target[1]
        moved = members.pop(source_index)
        members.insert(target_index, moved)
        for team_index, team in enumerate(project.teams):
            for slot_index in range(len(team)):
                team[slot_index] = members[team_index * per_team + slot_index]
        self.refresh_display()
        editor.selected = target
        editor.sync_controls()
        editor.schedule_render()
        if self._drag_position is None:
            self._history.commit_now()
        # During a drag nothing is scheduled: the drop commits the whole gesture
        # in one go, and a debounce that fired while the user lingered over a
        # slot would record an arrangement that a cancelled drag then reverts.

    def populate_items(self) -> None:
        builds = self._editor.builds
        names = [build.name for build in sorted(builds.values(), key=lambda item: item.name.casefold())]
        for row in self.combos:
            for combo in row:
                current = combo.currentText()
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(names)
                combo.setCurrentText(current)
                combo.blockSignals(False)
