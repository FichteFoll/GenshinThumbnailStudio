"""`MainWindow`, the application window wiring UID entry, mode selection and
drag/wheel/slider placement editing to fetching, preview/export, and persistence.
"""

from __future__ import annotations

import copy
from pathlib import Path

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
)

from ..enka import EnkaClient, is_uid
from ..models import Asset, Build, Placement, Project
from ..storage import cache_dir, load_last_profile
from . import dialogs, profile_io
from .actions import ProjectActions
from .asset_loader import AssetLoader
from .build_choices import resolve_build, selected_build
from .controls_panel import ControlsPanel
from .editor_panel import EditorPanel
from .history import HistoryController
from .placement import PlacementController
from .presets import PresetStore
from .project_io import ProjectFiles
from .render_pipeline import RenderPipeline
from .style import MAIN_STYLESHEET
from .team_fields import TeamFieldsController


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Genshin Thumbnail Studio")
        self.resize(1380, 860)
        self.setMinimumSize(1020, 680)
        self.project = Project.blank("abyss")
        self.project_path: Path | None = None
        self.builds: dict[str, list[Build]] = {}
        self.assets: dict[str, Asset] = {}
        self._presets = PresetStore.load()
        self._placement = PlacementController(self)
        self._history = HistoryController(self, self, self._history_restored)
        self.project_files = ProjectFiles(self, self, self._history)
        self.selected = (0, 0)
        self._updating_controls = False
        self._thread_pool = QThreadPool(self)
        self.asset_loader = AssetLoader(self, cache_dir() / "assets", self._thread_pool, self)
        self.asset_loader.asset_ready.connect(self._on_asset_ready)
        self.asset_loader.progress.connect(self.statusBar().showMessage)
        self.asset_loader.failed.connect(self._on_asset_download_failed)
        self._render = RenderPipeline(self, self._thread_pool, self)
        self._closing = False
        self.client = EnkaClient(cache_dir() / "enka")
        self._build_ui()
        # Ready to use, not a fetch on startup (R13): filled in but not loaded.
        self.controls_panel.profile_edit.setText(load_last_profile())
        # Connected only now: the preview does not exist before `_build_ui()`.
        self._render.rendered.connect(self.editor_panel.preview.set_preview)
        self._render.failed.connect(self._on_render_failed)
        self._actions = ProjectActions(self, self)
        self._actions.bind_buttons(self.controls_panel)
        # `__init__`'s own `self.project_path = None` cannot go through
        # `set_project_path()`, the buttons not existing yet, so the save
        # button's initial face is applied here instead.
        self._actions.set_project_path(self.project_path)
        self.team_fields = TeamFieldsController(self, self.controls_panel.team_layout, self._history, self)
        self.profile_loader = profile_io.ProfileLoader(self, self)
        self.rebuild_team_fields()
        self.sync_controls()
        self.saved_snapshot = copy.deepcopy(self.project)
        self.schedule_render()  # Through the throttle, so no render runs in the constructor.

    def _history_restored(self) -> None:
        """Show the teams an undo or redo just put back on the project."""
        # A state snapshotted before the profile arrived carries no build, and
        # the restore reaches the combos before their signals are connected, so
        # `member_changed()` never runs to resolve one. Without this the slot
        # renders as a placeholder for good while still counting as filled.
        for team in self.project.teams:
            for member in team:
                if member.name:
                    resolve_build(self, member)
        self.rebuild_team_fields()
        self.sync_controls()
        self._save_current_preset()
        # A restore can bring back a name whose art `member_changed` pruned,
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
        # and the event loop then delivers them. The flag stops a late one from
        # restarting the timer or re-dispatching onto the pool.
        self._closing = True
        self._render.stop()
        self._thread_pool.waitForDone(2000)
        super().closeEvent(event)

    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        self.controls_panel = ControlsPanel()
        self.controls_panel.mode_changed.connect(self._mode_changed)
        self.controls_panel.profile_requested.connect(self.load_profile)
        self.controls_panel.paste_requested.connect(self.paste_teams)
        self.controls_panel.output_name_changed.connect(self._output_name_changed)
        self.controls_panel.resolution_changed.connect(self._resolution_changed)
        # The three project buttons declare no panel signal: they trigger the
        # `QAction`s, which `ProjectActions.bind_buttons()` connects them to.

        self.editor_panel = EditorPanel()
        self.editor_panel.active_team_changed.connect(self._active_team_changed)
        self.editor_panel.placement_changed.connect(self._placement_slider_changed)
        self.editor_panel.flip_toggled.connect(self._flip_toggled)
        self.editor_panel.reset_requested.connect(self.reset_placement)
        # The preview's own signals are not re-exposed by the panel: they are
        # the canvas's, not the column's.
        self.editor_panel.preview.slot_selected.connect(self.select_slot)
        self.editor_panel.preview.placement_dragged.connect(self.drag_placement)
        self.editor_panel.preview.zoom_requested.connect(self.change_zoom)

        splitter.addWidget(self.controls_panel)
        splitter.addWidget(self.editor_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.statusBar().showMessage("Ready")

        self.setStyleSheet(MAIN_STYLESHEET)
        self.controls_panel.align_save_button_height()

    def rebuild_team_fields(self) -> None:
        self.team_fields.rebuild()

    def populate_combo_items(self) -> None:
        self.team_fields.populate_items()

    def _mode_changed(self, abyss_checked: bool) -> None:
        mode = "abyss" if abyss_checked else "stygian"
        if self.project.mode == mode:
            return
        if not dialogs.confirm_discard_changes(self, "switch modes", self.is_dirty, self.save_project):
            self.controls_panel.abyss_radio.setChecked(self.project.mode == "abyss")
            self.controls_panel.stygian_radio.setChecked(self.project.mode == "stygian")
            return
        identifier = self.controls_panel.profile_edit.text().strip()
        self.project = Project.blank(mode, identifier if is_uid(identifier) else "")
        self.project.profile_name = "" if is_uid(identifier) else identifier
        self.set_project_path(None)
        self.assets = {}
        self.selected = (0, 0)
        self.editor_panel.boss_combo.setVisible(mode == "stygian")
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

    def member_changed(self, team: int, slot: int, name: str) -> None:
        member = self.project.teams[team][slot]
        old_name = member.name
        member.name = name.strip()
        if member.build and member.build.name.casefold() != member.name.casefold():
            # The snapshot belongs to the character that was here before, so the
            # retyped slot falls back to the new character's live build.
            member.build = None
        if member.name and member.name.casefold() != old_name.casefold():
            self._presets.apply_to(self, member)
        resolve_build(self, member)
        self.assets = {key: value for key, value in self.assets.items() if key in self.selected_build_keys()}
        self.sync_controls()
        self._history.schedule()
        self.asset_loader.ensure()
        self.schedule_render()

    def build_selected(self, team: int, slot: int, build: Build) -> None:
        """Frame a slot with one of its character's other builds, snapshotting it."""
        member = self.project.teams[team][slot]
        member.build = build
        member.name = build.name
        self._presets.apply_to(self, member)  # The costume may differ, and `preset_key()` keys on it.
        self.assets = {key: value for key, value in self.assets.items() if key in self.selected_build_keys()}
        self.sync_controls()
        self._history.schedule()
        self.asset_loader.ensure()
        self.schedule_render()

    def selected_build_keys(self) -> set[str]:
        """The `Build.key`s the named slots are framed with, which is what the
        downloaded-art dict is keyed by."""
        builds = (selected_build(self, member) for team in self.project.teams for member in team if member.name)
        return {build.key for build in builds if build is not None}

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
            if (build := selected_build(self, member)) is not None and build.key in self.assets
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
        editor = self.editor_panel
        self._updating_controls = True
        max_x, max_y = self._placement.offset_bounds(member)
        # Truncate rather than round, so the slider end stays inside the range
        # the renderer can reach and no travel is left dead at the ends.
        limit_x, limit_y = int(max_x * 1000), int(max_y * 1000)
        editor.x_slider.setRange(-limit_x, limit_x)
        editor.y_slider.setRange(-limit_y, limit_y)
        editor.x_slider.setValue(round(member.offset_x * 1000))
        editor.y_slider.setValue(round(member.offset_y * 1000))
        # The sliders clamp to their range, so read the values back to keep the
        # model from holding an offset the renderer could not reach anyway.
        member.offset_x = editor.x_slider.value() / 1000
        member.offset_y = editor.y_slider.value() / 1000
        editor.zoom_slider.setValue(round(member.zoom * 100))
        editor.flip_check.setChecked(member.flip)
        resolution_combo = self.controls_panel.resolution_combo
        resolution_index = resolution_combo.findData(self.project.output_height)
        resolution_combo.setCurrentIndex(resolution_index if resolution_index >= 0 else 1)
        self._updating_controls = False
        label = "Team" if self.project.mode == "abyss" else "Boss"
        editor.selected_label.setText(f"{label} {team + 1}, character {slot + 1}")
        editor.x_value.setText(f"{member.offset_x * 100:+.0f}%")
        editor.y_value.setText(f"{member.offset_y * 100:+.0f}%")
        editor.zoom_value.setText(f"{member.zoom * 100:.0f}%")
        filled = self._filled_slots()
        editable = self.selected in filled
        for control in (editor.x_slider, editor.y_slider, editor.zoom_slider, editor.flip_check, editor.reset_button):
            control.setEnabled(editable)
        editor.preview.set_context(self.project.mode, self.project.active_team, self.selected, filled)

    def _placement_slider_changed(self) -> None:
        if self._updating_controls:
            return
        member = self.current_member()
        member.offset_x = self.editor_panel.x_slider.value() / 1000
        member.offset_y = self.editor_panel.y_slider.value() / 1000
        member.zoom = self.editor_panel.zoom_slider.value() / 100
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
        self.profile_loader.load()

    def paste_teams(self) -> None:
        self.profile_loader.paste_lineup()

    def validate_team(self) -> list[Build]:
        return self.profile_loader.validate_team()

    def _on_asset_ready(self, key: str, asset: Asset) -> None:
        # A download outliving `waitForDone(2000)` lands here during teardown,
        # where touching the widgets `sync_controls()` drives is pointless.
        if self._closing:
            return
        self.assets[key] = asset
        for team in self.project.teams:
            for member in team:
                build = selected_build(self, member)
                if build is not None and build.key == key:
                    self._presets.apply_to(self, member)
        # The arriving portrait only stops being a placeholder once the controls
        # resync: `sync_controls()` is what re-derives `_filled_slots()` for the
        # preview and the placement widgets, and so makes the slot editable.
        self.sync_controls()
        self.schedule_render()
        if not self.team_fields.dragging:
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
        self._actions.set_project_path(path)

    def save_project(self) -> None:
        self.project_files.save()

    def save_project_as(self) -> None:
        self.project_files.save_as()

    def open_project(self) -> None:
        self.project_files.open()
