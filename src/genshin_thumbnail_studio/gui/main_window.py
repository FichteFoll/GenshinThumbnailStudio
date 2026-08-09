"""`MainWindow`, the application window wiring UID entry, mode selection and
drag/wheel/slider placement editing to fetching, preview/export, and persistence.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMainWindow,
    QMenu,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..akasha import AkashaError, AkashaWebClient, Build, StaleProfileError
from ..models import Asset, Placement, Project
from ..storage import cache_dir, save_profile_cache
from . import dialogs
from .asset_loader import AssetLoader
from .controls_panel import ControlsPanel
from .history import HistoryController
from .lineup import parse_lineup
from .placement import PlacementController
from .presets import PresetStore
from .preview import PreviewWidget
from .project_io import ProjectFiles
from .render_pipeline import RenderPipeline
from .style import MAIN_STYLESHEET
from .team_slots import TeamSlotWidget


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
        self.project_files = ProjectFiles(self, self, self._history)
        self.selected = (0, 0)
        self._drag_snapshot: list[list[Placement]] | None = None
        self._drag_position: tuple[int, int] | None = None
        self._updating_controls = False
        self._thread_pool = QThreadPool(self)
        self.asset_loader = AssetLoader(self, cache_dir() / "assets", self._thread_pool, self)
        self.asset_loader.asset_ready.connect(self._on_asset_ready)
        self.asset_loader.progress.connect(self.statusBar().showMessage)
        self.asset_loader.failed.connect(self._on_asset_download_failed)
        self._render = RenderPipeline(self, self._thread_pool, self)
        self._closing = False
        self.client = AkashaWebClient(cache_dir())
        self.team_combos: list[list[QComboBox]] = []
        self._build_ui()
        # Connected only now: the preview does not exist before `_build_ui()`.
        self._render.rendered.connect(self.preview.set_preview)
        self._render.failed.connect(self._on_render_failed)
        self.rebuild_team_fields()
        self.sync_controls()
        self.saved_snapshot = copy.deepcopy(self.project)
        self.schedule_render()  # Through the throttle, so no render runs in the constructor.

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
        self._render.stop()
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
        save_button = self.controls_panel.save_button
        save_button.setText(self.save_action.text())
        save_button.setToolTip(self.save_action.toolTip())
        # Without a file to overwrite the button already *is* "save as", so a
        # menu repeating it would be noise; Ctrl+Shift+S still works, because
        # the action is registered on the window rather than only on the menu.
        # Detaching takes a null menu, which Qt documents but the PySide6 stub
        # does not admit, so the argument type has to be waived here.
        save_button.setMenu(self._save_menu if path else None)  # pyright: ignore[reportArgumentType]

    def _build_ui(self) -> None:
        self._build_actions()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self.controls_panel = ControlsPanel()
        self.controls_panel.mode_changed.connect(self._mode_changed)
        self.controls_panel.profile_requested.connect(self.load_profile)
        self.controls_panel.paste_requested.connect(self.paste_teams)
        self.controls_panel.output_name_changed.connect(self._output_name_changed)
        self.controls_panel.resolution_changed.connect(self._resolution_changed)
        # The three project buttons trigger the window's own actions, so the
        # panel declares no signal for them.
        self.controls_panel.open_button.clicked.connect(self.open_action.trigger)
        self.controls_panel.save_button.clicked.connect(self.save_action.trigger)
        self.controls_panel.export_button.clicked.connect(self.export_action.trigger)

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

        splitter.addWidget(self.controls_panel)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.statusBar().showMessage("Ready")

        self.setStyleSheet(MAIN_STYLESHEET)
        self.controls_panel.align_save_button_height()
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
        team_layout = self.controls_panel.team_layout
        self._clear_layout(team_layout)
        self.team_combos = []
        for team_index, team in enumerate(self.project.teams):
            title = QLabel(f"{'Team' if self.project.mode == 'abyss' else 'Boss'} {team_index + 1}")
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
                    self._member_changed(t, s, value)

                combo.currentTextChanged.connect(on_text_changed)
                slot_widget = TeamSlotWidget(team_index, slot_index, combo)
                slot_widget.drag_started.connect(self._on_slot_drag_started)
                slot_widget.drag_hover.connect(self._on_slot_drag_hover)
                slot_widget.drag_ended.connect(self._on_slot_drag_ended)
                rows.addWidget(slot_widget)
                row_combos.append(combo)
            team_layout.addLayout(rows)
            self.team_combos.append(row_combos)
        team_layout.addStretch(1)
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
            self.controls_panel.abyss_radio.setChecked(self.project.mode == "abyss")
            self.controls_panel.stygian_radio.setChecked(self.project.mode == "stygian")
            return
        uid = self.controls_panel.uid_edit.text().strip()
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
        self.project.output_height = self.controls_panel.resolution_combo.itemData(index)

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
        resolution_combo = self.controls_panel.resolution_combo
        resolution_index = resolution_combo.findData(self.project.output_height)
        resolution_combo.setCurrentIndex(resolution_index if resolution_index >= 0 else 1)
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
        self._render.schedule()

    def load_profile(self) -> None:
        uid = self.controls_panel.uid_edit.text().strip()
        self.project.uid = uid
        self.controls_panel.load_button.setEnabled(False)
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
            self.controls_panel.profile_status.setText(
                f"{len(builds)} builds \u00b7 last updated {local} \u00b7 {age:.0f} min ago"
            )
            self.statusBar().showMessage("Akasha profile loaded", 5000)
            self.asset_loader.ensure()
            self.schedule_render()
        except Exception as error:
            dialogs.show_error(self, "Could not load profile", error)
        finally:
            QApplication.restoreOverrideCursor()
            self.controls_panel.load_button.setEnabled(True)

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

    def _on_render_failed(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def export(self) -> None:
        self.project_files.export()

    def is_dirty(self) -> bool:
        """Whether the project differs from what was last saved, loaded, or started blank."""
        return self.project != self.saved_snapshot

    def set_project_path(self, path: Path | None) -> None:
        """The single write path for `project_path`, so nothing that has to
        follow a change of it can be missed at an assignment site."""
        self.project_path = path
        self._update_save_button()

    def save_project(self) -> None:
        self.project_files.save()

    def save_project_as(self) -> None:
        self.project_files.save_as()

    def open_project(self) -> None:
        self.project_files.open()
