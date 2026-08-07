"""`MainWindow`, the application window wiring UID entry, mode selection and
drag/wheel/slider placement editing to fetching, preview/export, and persistence.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..akasha import AkashaError, AkashaWebClient, Build, StaleProfileError
from ..models import Asset, Placement, Project
from ..storage import cache_dir, save_profile_cache
from . import dialogs, project_io
from .asset_loader import AssetLoader
from .history import HistoryController
from .lineup import parse_lineup
from .placement import PlacementController
from .presets import PresetStore
from .preview import PreviewWidget
from .render_job import RenderJob
from .style import MAIN_STYLESHEET
from .team_slots import TeamSlotWidget

# Delay between a placement change and the preview render it triggers.
RENDER_THROTTLE_MS = 80


RESOLUTION_OPTIONS = [
    ("720p", 720),
    ("1080p", 1080),
    ("1440p", 1440),
    ("2160p", 2160),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Genshin Thumbnail Studio")
        self.resize(1380, 860)
        self.setMinimumSize(1020, 680)
        self.project = Project.blank("abyss")
        self.project_path: Path | None = None
        self.builds: dict[str, Build] = {}
        self.assets: dict[str, Asset] = {}
        self._presets = PresetStore.load()
        self._placement = PlacementController(self)
        self._history = HistoryController(self, self, self._history_restored)
        self.selected = (0, 0)
        self._drag_snapshot: list[list[Placement]] | None = None
        self._drag_position: tuple[int, int] | None = None
        self._updating_controls = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._dispatch_render)
        self._thread_pool = QThreadPool(self)
        self.asset_loader = AssetLoader(self, cache_dir() / "assets", self._thread_pool, self)
        self.asset_loader.asset_ready.connect(self._on_asset_ready)
        self.asset_loader.progress.connect(self.statusBar().showMessage)
        self.asset_loader.failed.connect(self._on_asset_download_failed)
        self._render_token = 0
        self._render_job_running = False
        self._render_stale = False
        self._closing = False
        self.client = AkashaWebClient(cache_dir())
        self.team_combos: list[list[QComboBox]] = []
        self._build_ui()
        self.rebuild_team_fields()
        self.sync_controls()
        self.saved_snapshot = copy.deepcopy(self.project)
        self.schedule_render()  # Through the throttle, so no render runs in the constructor.

    def _icon(self, standard: QStyle.StandardPixmap):
        return self.style().standardIcon(standard)

    def _history_restored(self) -> None:
        """Show the teams an undo or redo just put back on the project."""
        self.rebuild_team_fields()
        self.sync_controls()
        self._save_current_preset()
        # A restore can bring back a name whose art `_member_changed` pruned,
        # and it reaches the combos before their signals are connected, so it
        # goes through neither that handler nor its `ensure()`. Without this the
        # slot would stay a placeholder for good: inert, and refusing to export.
        self.asset_loader.ensure()
        self.schedule_render()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not dialogs.confirm_discard_changes(self, "exit", self.is_dirty, self.save_project):
            event.ignore()
            return
        # The preview renders on its own now, so a job may well be in flight.
        # Draining is not enough: both jobs signal the GUI thread over a queued
        # connection, so `waitForDone()` returns with their slots still queued
        # and `client.close()` spins the loops that deliver them. The flag stops
        # a late one from restarting the timer or re-dispatching onto the pool.
        self._closing = True
        self._render_timer.stop()
        self._thread_pool.waitForDone(2000)
        self.client.close()
        super().closeEvent(event)

    def _action(self, text: str, sequence: str, handler: Callable[[], None]) -> QAction:
        """A window-wide action for one of the project file flows.

        Registered on the window with `addAction()`, so its shortcut fires
        wherever the focus is. Deliberately a `QAction` and not a `QShortcut`
        like `history.py` uses: the "Save as..." menu entry needs an action
        anyway, and a sequence bound to both would be ambiguous and fire
        neither. Callers pass a lambda rather than a bound method, so the
        dispatch stays late-bound and replacing the method on the instance
        replaces what fires.
        """
        action = QAction(text, self)
        action.setShortcut(QKeySequence(sequence))
        action.triggered.connect(handler)
        self.addAction(action)
        return action

    def _build_actions(self) -> None:
        self.open_action = self._action("Open project", "Ctrl+O", lambda: self.open_project())
        self.save_action = self._action("Save project", "Ctrl+S", lambda: self.save_project())
        self.save_as_action = self._action("Save as...", "Ctrl+Shift+S", lambda: self.save_project_as())
        self.export_action = self._action("Export PNG", "Ctrl+E", lambda: self.export())
        self._save_menu = QMenu(self)
        self._save_menu.addAction(self.save_as_action)

    def _update_save_button(self) -> None:
        """Show whether saving overwrites a file or asks for one.

        Driven from `set_project_path()`, the single write path for
        `project_path`, so no transition can miss it.
        """
        path = self.project_path
        self.save_action.setText("Save project" if path else "Save project as...")
        self.save_action.setToolTip(f"Save {path.name} (Ctrl+S)" if path else "Save project as... (Ctrl+S)")
        self.save_button.setText(self.save_action.text())
        self.save_button.setToolTip(self.save_action.toolTip())
        # Without a file to overwrite the button already *is* "save as", so a
        # menu repeating it would be noise; Ctrl+Shift+S still works, because
        # the action is registered on the window rather than only on the menu.
        # Detaching takes a null menu, which Qt documents but the PySide6 stub
        # does not admit, so the argument type has to be waived here.
        self.save_button.setMenu(self._save_menu if path else None)  # pyright: ignore[reportArgumentType]

    def _build_ui(self) -> None:
        self._build_actions()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        controls = QWidget()
        controls.setMinimumWidth(330)
        controls.setMaximumWidth(430)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(16, 16, 12, 16)
        controls_layout.setSpacing(12)

        mode_row = QHBoxLayout()
        self.abyss_radio = QRadioButton("Spiral Abyss")
        self.stygian_radio = QRadioButton("Stygian Onslaught")
        self.abyss_radio.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.abyss_radio)
        mode_group.addButton(self.stygian_radio)
        mode_row.addWidget(self.abyss_radio)
        mode_row.addWidget(self.stygian_radio)
        controls_layout.addLayout(mode_row)
        self.abyss_radio.toggled.connect(self._mode_changed)

        uid_row = QHBoxLayout()
        self.uid_edit = QLineEdit()
        self.uid_edit.setPlaceholderText("Genshin UID")
        self.uid_edit.setMaxLength(12)
        self.load_button = QPushButton("Load profile")
        self.load_button.clicked.connect(self.load_profile)
        uid_row.addWidget(self.uid_edit, 1)
        uid_row.addWidget(self.load_button)
        controls_layout.addLayout(uid_row)

        self.profile_status = QLabel("No profile loaded")
        self.profile_status.setObjectName("secondary")
        self.profile_status.setWordWrap(True)
        controls_layout.addWidget(self.profile_status)

        paste_button = QPushButton("Paste lineup")
        paste_button.clicked.connect(self.paste_teams)
        controls_layout.addWidget(paste_button)

        self.team_container = QWidget()
        self.team_layout = QVBoxLayout(self.team_container)
        self.team_layout.setContentsMargins(0, 0, 0, 0)
        self.team_layout.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.team_container)
        controls_layout.addWidget(scroll, 1)

        output_form = QFormLayout()
        self.output_name = QLineEdit("genshin_thumbnail")
        self.output_name.textChanged.connect(self._output_name_changed)
        output_form.addRow("File name", self.output_name)
        self.resolution_combo = QComboBox()
        for label, height in RESOLUTION_OPTIONS:
            self.resolution_combo.addItem(label, height)
        self.resolution_combo.currentIndexChanged.connect(self._resolution_changed)
        output_form.addRow("Resolution", self.resolution_combo)
        controls_layout.addLayout(output_form)

        project_row = QHBoxLayout()
        self.open_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogOpenButton), "Open project")
        self.open_button.setToolTip("Open project (Ctrl+O)")
        self.open_button.clicked.connect(self.open_action.trigger)
        # A QToolButton, so its arrow section can open the "Save as..." menu
        # while the main section still saves; _update_save_button() fills in
        # the caption, the tooltip and whether the menu is attached at all.
        self.save_button = QToolButton()
        self.save_button.setIcon(self._icon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.save_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.save_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.save_button.setSizePolicy(self.open_button.sizePolicy())
        self.save_button.clicked.connect(self.save_action.trigger)
        project_row.addWidget(self.open_button)
        project_row.addWidget(self.save_button)
        controls_layout.addLayout(project_row)

        self.export_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogSaveButton), "Export PNG")
        self.export_button.setToolTip("Export PNG (Ctrl+E)")
        self.export_button.clicked.connect(self.export_action.trigger)
        controls_layout.addWidget(self.export_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 16, 16, 16)
        right_layout.setSpacing(10)

        preview_toolbar = QHBoxLayout()
        self.preview_team_label = QLabel("Preview")
        self.boss_combo = QComboBox()
        self.boss_combo.addItems(["Boss 1", "Boss 2", "Boss 3"])
        self.boss_combo.setVisible(False)
        self.boss_combo.currentIndexChanged.connect(self._active_team_changed)
        preview_toolbar.addWidget(self.preview_team_label)
        preview_toolbar.addStretch(1)
        preview_toolbar.addWidget(self.boss_combo)
        right_layout.addLayout(preview_toolbar)

        self.preview = PreviewWidget()
        self.preview.slot_selected.connect(self.select_slot)
        self.preview.placement_dragged.connect(self.drag_placement)
        self.preview.zoom_requested.connect(self.change_zoom)
        right_layout.addWidget(self.preview, 1)

        placement_row = QHBoxLayout()
        self.selected_label = QLabel("Team 1, character 1")
        # Placeholder offset ranges; sync_controls() sets the reachable ones.
        self.x_slider = self._slider(-500, 500, 0)
        self.y_slider = self._slider(-500, 500, -20)
        self.zoom_slider = self._slider(70, 180, 100)
        self.x_value = QLabel("+0%")
        self.y_value = QLabel("-2%")
        self.zoom_value = QLabel("100%")
        for slider in [self.x_slider, self.y_slider, self.zoom_slider]:
            slider.valueChanged.connect(self._placement_slider_changed)
        self.flip_check = QCheckBox("Flip")
        self.flip_check.setToolTip("Mirror this character horizontally")
        self.flip_check.toggled.connect(self._flip_toggled)
        self.reset_button = QPushButton("Reset")
        self.reset_button.clicked.connect(self.reset_placement)
        placement_row.addWidget(self.selected_label)
        placement_row.addSpacing(12)
        placement_row.addWidget(QLabel("X"))
        placement_row.addWidget(self.x_slider, 1)
        placement_row.addWidget(self.x_value)
        placement_row.addWidget(QLabel("Y"))
        placement_row.addWidget(self.y_slider, 1)
        placement_row.addWidget(self.y_value)
        placement_row.addWidget(QLabel("Zoom"))
        placement_row.addWidget(self.zoom_slider, 1)
        placement_row.addWidget(self.zoom_value)
        placement_row.addWidget(self.flip_check)
        placement_row.addWidget(self.reset_button)
        right_layout.addLayout(placement_row)

        splitter.addWidget(controls)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.statusBar().showMessage("Ready")

        self.setStyleSheet(MAIN_STYLESHEET)
        self._update_save_button()

    @staticmethod
    def _slider(minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setMinimumWidth(80)
        return slider

    def _clear_layout(self, layout: QLayout) -> None:
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
                    self._clear_layout(sub_layout)

    def rebuild_team_fields(self) -> None:
        self._clear_layout(self.team_layout)
        self.team_combos = []
        for team_index, team in enumerate(self.project.teams):
            title = QLabel(f"{'Team' if self.project.mode == 'abyss' else 'Boss'} {team_index + 1}")
            title.setStyleSheet("font-weight: 600;")
            self.team_layout.addWidget(title)
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
                    self._member_changed(t, s, value)

                combo.currentTextChanged.connect(on_text_changed)
                slot_widget = TeamSlotWidget(team_index, slot_index, combo)
                slot_widget.drag_started.connect(self._on_slot_drag_started)
                slot_widget.drag_hover.connect(self._on_slot_drag_hover)
                slot_widget.drag_ended.connect(self._on_slot_drag_ended)
                rows.addWidget(slot_widget)
                row_combos.append(combo)
            self.team_layout.addLayout(rows)
            self.team_combos.append(row_combos)
        self.team_layout.addStretch(1)
        self.populate_combo_items()

    def _refresh_slot_display(self) -> None:
        for team_index, row in enumerate(self.team_combos):
            for slot_index, combo in enumerate(row):
                name = self.project.teams[team_index][slot_index].name
                if combo.currentText() != name:
                    combo.blockSignals(True)
                    combo.setCurrentText(name)
                    combo.blockSignals(False)

    def _on_slot_drag_started(self, team: int, slot: int) -> None:
        # Settle any edit still pending from before the drag, so its debounce
        # cannot fire mid-gesture and snapshot a half-finished reorder.
        self._history.commit_now()
        self._drag_snapshot = copy.deepcopy(self.project.teams)
        self._drag_position = (team, slot)

    def _on_slot_drag_hover(self, team: int, slot: int) -> None:
        if self._drag_position is None or (team, slot) == self._drag_position:
            return
        self.reorder_slots(self._drag_position, (team, slot))
        self._drag_position = (team, slot)

    def _on_slot_drag_ended(self, accepted: bool) -> None:
        if not accepted and self._drag_snapshot is not None:
            self.project.teams = self._drag_snapshot
            self._refresh_slot_display()
            self.sync_controls()
            self.schedule_render()
        self._drag_snapshot = None
        self._drag_position = None
        # A no-op after a cancelled drag, whose revert restored the last state.
        self._history.commit_now()

    def reorder_slots(self, source: tuple[int, int], target: tuple[int, int]) -> None:
        if source == target:
            return
        per_team = len(self.project.teams[0])
        members = [member for team in self.project.teams for member in team]
        source_index = source[0] * per_team + source[1]
        target_index = target[0] * per_team + target[1]
        moved = members.pop(source_index)
        members.insert(target_index, moved)
        for team_index, team in enumerate(self.project.teams):
            for slot_index in range(len(team)):
                team[slot_index] = members[team_index * per_team + slot_index]
        self._refresh_slot_display()
        self.selected = target
        self.sync_controls()
        self.schedule_render()
        if self._drag_position is None:
            self._history.commit_now()
        # During a drag nothing is scheduled: the drop commits the whole gesture
        # in one go, and a debounce that fired while the user lingered over a
        # slot would record an arrangement that a cancelled drag then reverts.

    def populate_combo_items(self) -> None:
        names = [build.name for build in sorted(self.builds.values(), key=lambda item: item.name.casefold())]
        for row in self.team_combos:
            for combo in row:
                current = combo.currentText()
                combo.blockSignals(True)
                combo.clear()
                combo.addItems(names)
                combo.setCurrentText(current)
                combo.blockSignals(False)

    def _mode_changed(self, abyss_checked: bool) -> None:
        mode = "abyss" if abyss_checked else "stygian"
        if self.project.mode == mode:
            return
        if not dialogs.confirm_discard_changes(self, "switch modes", self.is_dirty, self.save_project):
            self.abyss_radio.setChecked(self.project.mode == "abyss")
            self.stygian_radio.setChecked(self.project.mode == "stygian")
            return
        uid = self.uid_edit.text().strip()
        self.project = Project.blank(mode, uid)
        self.set_project_path(None)
        self.assets = {}
        self.selected = (0, 0)
        self.boss_combo.setVisible(mode == "stygian")
        self.rebuild_team_fields()
        self.sync_controls()
        self.schedule_render()
        self._history.reset()
        self.saved_snapshot = copy.deepcopy(self.project)

    def _output_name_changed(self, value: str) -> None:
        self.project.output_name = value

    def _resolution_changed(self, index: int) -> None:
        if self._updating_controls or index < 0:
            return
        self.project.output_height = self.resolution_combo.itemData(index)

    def _active_team_changed(self, index: int) -> None:
        if self.project.mode != "stygian":
            return
        self.project.active_team = max(0, index)
        self.selected = (self.project.active_team, self.selected[1])
        self.sync_controls()
        self.schedule_render()

    def _member_changed(self, team: int, slot: int, name: str) -> None:
        member = self.project.teams[team][slot]
        old_name = member.name
        member.name = name.strip()
        if member.name and member.name.casefold() != old_name.casefold():
            self._presets.apply_to(self, member)
        self.assets = {key: value for key, value in self.assets.items() if key in self.selected_name_keys()}
        self.sync_controls()
        self._history.schedule()
        self.asset_loader.ensure()
        self.schedule_render()

    def selected_name_keys(self) -> set[str]:
        return {member.name.casefold() for team in self.project.teams for member in team if member.name}

    def _save_current_preset(self) -> None:
        self._presets.remember(self, self.current_member())

    def current_member(self) -> Placement:
        team, slot = self.selected
        return self.project.teams[team][slot]

    def _filled_slots(self) -> set[tuple[int, int]]:
        """The `(team, slot)` pairs whose art is downloaded; the rest are placeholders."""
        return {
            (team_index, slot_index)
            for team_index, team in enumerate(self.project.teams)
            for slot_index, member in enumerate(team)
            if member.name and member.name.casefold() in self.assets
        }

    def select_slot(self, team: int, slot: int) -> None:
        self.selected = (team, slot)
        self.sync_controls()

    def sync_controls(self) -> None:
        team, slot = self.selected
        team = min(team, len(self.project.teams) - 1)
        slot = min(slot, 3)
        self.selected = (team, slot)
        member = self.current_member()
        self._updating_controls = True
        max_x, max_y = self._placement.offset_bounds(member)
        # Truncate rather than round, so the slider end stays inside the range
        # the renderer can reach and no travel is left dead at the ends.
        limit_x, limit_y = int(max_x * 1000), int(max_y * 1000)
        self.x_slider.setRange(-limit_x, limit_x)
        self.y_slider.setRange(-limit_y, limit_y)
        self.x_slider.setValue(round(member.offset_x * 1000))
        self.y_slider.setValue(round(member.offset_y * 1000))
        # The sliders clamp to their range, so read the values back to keep the
        # model from holding an offset the renderer could not reach anyway.
        member.offset_x = self.x_slider.value() / 1000
        member.offset_y = self.y_slider.value() / 1000
        self.zoom_slider.setValue(round(member.zoom * 100))
        self.flip_check.setChecked(member.flip)
        resolution_index = self.resolution_combo.findData(self.project.output_height)
        self.resolution_combo.setCurrentIndex(resolution_index if resolution_index >= 0 else 1)
        self._updating_controls = False
        label = "Team" if self.project.mode == "abyss" else "Boss"
        self.selected_label.setText(f"{label} {team + 1}, character {slot + 1}")
        self.x_value.setText(f"{member.offset_x * 100:+.0f}%")
        self.y_value.setText(f"{member.offset_y * 100:+.0f}%")
        self.zoom_value.setText(f"{member.zoom * 100:.0f}%")
        filled = self._filled_slots()
        editable = self.selected in filled
        for control in (self.x_slider, self.y_slider, self.zoom_slider, self.flip_check, self.reset_button):
            control.setEnabled(editable)
        self.preview.set_context(self.project.mode, self.project.active_team, self.selected, filled)

    def _placement_slider_changed(self) -> None:
        if self._updating_controls:
            return
        member = self.current_member()
        member.offset_x = self.x_slider.value() / 1000
        member.offset_y = self.y_slider.value() / 1000
        member.zoom = self.zoom_slider.value() / 100
        self._save_current_preset()
        self.sync_controls()
        self.schedule_render()
        self._history.schedule()

    def _flip_toggled(self, checked: bool) -> None:
        if self._updating_controls:
            return
        self.current_member().flip = checked
        self._save_current_preset()
        self.sync_controls()
        self.schedule_render()
        self._history.schedule()

    def drag_placement(self, dx: float, dy: float) -> None:
        """Pan the selected portrait by a drag delta given in canvas pixels."""
        if self.selected not in self._filled_slots():
            return
        self._placement.pan(self.current_member(), dx, dy)
        self._save_current_preset()
        self.sync_controls()
        self.schedule_render()
        self._history.schedule()

    def change_zoom(self, delta: float) -> None:
        # A placeholder has no framing to edit, and the no-op would still snapshot.
        if self.selected not in self._filled_slots():
            return
        self._placement.zoom_by(self.current_member(), delta)
        self._save_current_preset()
        self.sync_controls()
        self.schedule_render()
        self._history.schedule()

    def reset_placement(self) -> None:
        self._placement.reset(self.current_member())
        self._save_current_preset()
        self.sync_controls()
        self.schedule_render()
        self._history.commit_now()

    def schedule_render(self) -> None:
        # A throttle, not a debounce: restarting the timer on every
        # mouse-move event would mean it never fires during a drag.
        if not self._closing and not self._render_timer.isActive():
            self._render_timer.start(RENDER_THROTTLE_MS)

    def load_profile(self) -> None:
        uid = self.uid_edit.text().strip()
        self.project.uid = uid
        self.load_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            try:
                builds, age, last = self.client.load_profile(uid)
            except StaleProfileError as stale:
                choice = dialogs.choose_stale_profile_action(self, stale.age_minutes)
                if choice == "refresh":
                    self.statusBar().showMessage("Refreshing Akasha ...")
                    QApplication.restoreOverrideCursor()
                    if not self.client.refresh_profile(uid, progress=lambda text: self.statusBar().showMessage(text)):
                        raise AkashaError("Akasha refresh did not finish within 90 seconds.") from None
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                    builds, age, last = self.client.load_profile(uid)
                elif choice == "stale":
                    builds, age, last = self.client.load_profile(uid, allow_stale=True)
                else:
                    return
            self.builds = {build.name.casefold(): build for build in builds}
            save_profile_cache(uid, builds, last)
            self.assets = {}
            self.populate_combo_items()
            local = last.astimezone().strftime("%Y-%m-%d %H:%M")
            self.profile_status.setText(f"{len(builds)} builds \u00b7 last updated {local} \u00b7 {age:.0f} min ago")
            self.statusBar().showMessage("Akasha profile loaded", 5000)
            self.asset_loader.ensure()
            self.schedule_render()
        except Exception as error:
            dialogs.show_error(self, "Could not load profile", error)
        finally:
            QApplication.restoreOverrideCursor()
            self.load_button.setEnabled(True)

    def paste_teams(self) -> None:
        expected = 8 if self.project.mode == "abyss" else 12
        text = dialogs.ask_lineup_text(self, expected)
        if text is None:
            return
        names = parse_lineup(text)
        if len(names) != expected:
            dialogs.show_error(self, "Invalid lineup", f"Expected {expected} names, found {len(names)}.")
            return
        for index, name in enumerate(names):
            team, slot = divmod(index, 4)
            self.team_combos[team][slot].setCurrentText(name)

    def validate_team(self) -> list[Build]:
        missing: list[str] = []
        selected: list[Build] = []
        for team_index, row in enumerate(self.team_combos):
            for slot_index, combo in enumerate(row):
                name = combo.currentText().strip()
                self.project.teams[team_index][slot_index].name = name
                build = self.builds.get(name.casefold())
                if build is None:
                    missing.append(f"{team_index + 1}-{slot_index + 1}: {name or 'empty'}")
                else:
                    selected.append(build)
        if missing:
            raise ValueError("Build not in the loaded profile: " + ", ".join(missing))
        unique: dict[str, Build] = {build.name.casefold(): build for build in selected}
        return list(unique.values())

    def _on_asset_ready(self, key: str, asset: Asset) -> None:
        # A download outliving `waitForDone(2000)` lands here during teardown,
        # where touching the widgets `sync_controls()` drives is pointless.
        if self._closing:
            return
        self.assets[key] = asset
        for team in self.project.teams:
            for member in team:
                if member.name.casefold() == key:
                    self._presets.apply_to(self, member)
        # The arriving portrait only stops being a placeholder once the controls
        # resync: `sync_controls()` is what re-derives `_filled_slots()` for the
        # preview and the placement widgets, and so makes the slot editable.
        self.sync_controls()
        self.schedule_render()
        if self._drag_position is None:
            # Debounced, so a batch of arrivals coalesces into one undo step;
            # skipped mid-drag, where nothing may be scheduled at all.
            self._history.schedule()

    def _on_asset_download_failed(self, error: Exception) -> None:
        # In the status bar rather than a dialog: a download running in the
        # background must not interrupt what the user is typing.
        self.statusBar().showMessage(str(error), 8000)

    def _dispatch_render(self) -> None:
        if self._closing:
            return
        self._render_token += 1
        if self._render_job_running:
            self._render_stale = True
            return
        snapshot = Project(
            mode=self.project.mode,
            uid=self.project.uid,
            output_name=self.project.output_name,
            output_height=self.project.output_height,
            teams=copy.deepcopy(self.project.teams),
            active_team=self.project.active_team,
        )
        assets_snapshot = dict(self.assets)
        self._render_job_running = True
        job = RenderJob(self._render_token, snapshot, assets_snapshot)
        job.signals.finished.connect(self._on_render_finished)
        self._thread_pool.start(job)

    def _on_render_finished(self, token: int, image: Image.Image | None, error: Exception | None) -> None:
        self._render_job_running = False
        if token == self._render_token:
            if error is None:
                self.preview.set_preview(QPixmap.fromImage(ImageQt(image)))
            else:
                self.statusBar().showMessage(str(error), 8000)
        if self._render_stale:
            self._render_stale = False
            self._dispatch_render()

    def export(self) -> None:
        project_io.export(self, self)

    def is_dirty(self) -> bool:
        """Whether the project differs from what was last saved, loaded, or started blank."""
        return self.project != self.saved_snapshot

    def set_project_path(self, path: Path | None) -> None:
        """The single write path for `project_path`, so nothing that has to
        follow a change of it can be missed at an assignment site."""
        self.project_path = path
        self._update_save_button()

    def save_project(self) -> None:
        project_io.save_project(self, self)

    def save_project_as(self) -> None:
        project_io.save_project_as(self, self)

    def open_project(self) -> None:
        project_io.open_project(self, self, self._history)
