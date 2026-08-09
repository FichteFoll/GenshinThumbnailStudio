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
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QComboBox, QLabel, QLayout, QMenu, QVBoxLayout

from ..models import Build, Placement
from .build_choices import BuildChoice, build_choices
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
    def build_selected(self, team: int, slot: int, build: Build) -> None: ...


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
        self.slot_widgets: list[list[TeamSlotWidget]] = []
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
        self.slot_widgets = []
        for team_index, team in enumerate(project.teams):
            title = QLabel(f"{'Team' if project.mode == 'abyss' else 'Boss'} {team_index + 1}")
            title.setStyleSheet("font-weight: 600;")
            team_layout.addWidget(title)
            rows = QVBoxLayout()
            rows.setSpacing(4)
            row_combos: list[QComboBox] = []
            row_widgets: list[TeamSlotWidget] = []
            for slot_index, member in enumerate(team):
                combo = QComboBox()
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                combo.setPlaceholderText(f"Character {slot_index + 1}")
                if member.name:
                    combo.setCurrentText(member.name)

                def on_text_changed(value: str, t: int = team_index, s: int = slot_index) -> None:
                    self._editor.member_changed(t, s, value)
                    # The new character has builds of its own, or none at all.
                    self.refresh_build_buttons()

                combo.currentTextChanged.connect(on_text_changed)
                slot_widget = TeamSlotWidget(team_index, slot_index, combo)
                slot_widget.drag_started.connect(self.on_drag_started)
                slot_widget.drag_hover.connect(self.on_drag_hover)
                slot_widget.drag_ended.connect(self.on_drag_ended)
                slot_widget.build_menu_requested.connect(self.show_build_menu)
                rows.addWidget(slot_widget)
                row_combos.append(combo)
                row_widgets.append(slot_widget)
            team_layout.addLayout(rows)
            self.combos.append(row_combos)
            self.slot_widgets.append(row_widgets)
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
        # The names moved with their slots, and the signals were blocked, so
        # the arrows have to follow them by hand.
        self.refresh_build_buttons()

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
        # One entry per character, spelled the way its builds spell it.
        names = sorted(
            (builds[0].name for builds in self._editor.builds.values() if builds),
            key=str.casefold,
        )
        for row in self.combos:
            for combo in row:
                current = combo.currentText()
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(names)
                combo.setCurrentText(current)
                combo.blockSignals(False)
        self.refresh_build_buttons()

    def refresh_build_buttons(self) -> None:
        """Offer the arrow only where there is a build list behind it, and
        caption it with the selected build.

        Which builds a slot has follows its character, so this has to run
        wherever a slot's name changes, not just when the profile arrives.
        """
        for team_index, row in enumerate(self.slot_widgets):
            for slot_index, slot_widget in enumerate(row):
                choices = self._build_choices(team_index, slot_index)
                slot_widget.build_button.setEnabled(len(choices) > 0)
                selected = next((choice for choice in choices if choice.selected), None)
                slot_widget.set_build_caption(selected.label if selected else "")

    def _build_choices(self, team: int, slot: int) -> list[BuildChoice]:
        member = self._editor.project.teams[team][slot]
        if not member.name:
            return []
        profile_builds = self._editor.builds.get(member.name.casefold(), [])
        return build_choices(profile_builds, member.build)

    def build_menu(self, team: int, slot: int) -> QMenu:
        """The checkable actions for one slot's build dropdown.

        Returns the menu rather than popping it up, so tests can assert its
        contents without a running event loop; `show_build_menu()` is what
        actually displays it.
        """
        menu = QMenu()
        # Exactly one build can be selected, and an exclusive action group is
        # what makes Qt draw the entries with radio indicators instead of
        # check boxes. Parented to the menu so it outlives this call.
        group = QActionGroup(menu)
        group.setExclusive(True)
        for choice in self._build_choices(team, slot):
            action = QAction(choice.label, menu)
            action.setCheckable(True)
            action.setChecked(choice.selected)
            action.triggered.connect(
                lambda _checked=False, build=choice.build: self._select_build(team, slot, build)
            )
            group.addAction(action)
            menu.addAction(action)
        return menu

    def _select_build(self, team: int, slot: int, build: Build) -> None:
        # The editor answers a selection with `sync_controls()`, which does not
        # touch the team fields, so the new caption has to be set from here.
        self._editor.build_selected(team, slot, build)
        self.refresh_build_buttons()

    def show_build_menu(self, team: int, slot: int) -> None:
        slot_widget = self.slot_widgets[team][slot]
        menu = self.build_menu(team, slot)
        menu.exec(slot_widget.build_button.mapToGlobal(slot_widget.build_button.rect().bottomLeft()))
