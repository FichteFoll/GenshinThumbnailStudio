"""`MainWindow`, the application window wiring UID entry, mode selection and
drag/wheel/slider placement editing to fetching, preview/export, and persistence.
"""

from __future__ import annotations

import contextlib
import copy
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QCloseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ..akasha import AkashaError, AkashaWebClient, Build, StaleProfileError, download_assets
from ..models import Asset, Placement, Project
from ..renderer import export_project, safe_name
from ..storage import (
    cache_dir,
    load_profile_cache,
    load_project,
    save_profile_cache,
    save_project,
)
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
        self.selected = (0, 0)
        self._drag_snapshot: list[list[Placement]] | None = None
        self._drag_position: tuple[int, int] | None = None
        self._updating_controls = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._dispatch_render)
        self._thread_pool = QThreadPool(self)
        self._render_token = 0
        self._render_job_running = False
        self._render_stale = False
        self.client = AkashaWebClient(cache_dir())
        self.team_combos: list[list[QComboBox]] = []
        self._build_ui()
        self._rebuild_team_fields()
        self._sync_controls()

    def _icon(self, standard: QStyle.StandardPixmap):
        return self.style().standardIcon(standard)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.client.close()
        super().closeEvent(event)

    def _build_ui(self) -> None:
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
        open_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogOpenButton), "Open project")
        save_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogSaveButton), "Save project")
        open_button.clicked.connect(self.open_project)
        save_button.clicked.connect(self.save_project)
        project_row.addWidget(open_button)
        project_row.addWidget(save_button)
        controls_layout.addLayout(project_row)

        self.preview_button = QPushButton("Generate preview")
        self.preview_button.clicked.connect(self.prepare_preview)
        self.export_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogSaveButton), "Export PNG")
        self.export_button.clicked.connect(self.export)
        controls_layout.addWidget(self.preview_button)
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
        # Placeholder offset ranges; _sync_controls() sets the reachable ones.
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
        reset_button = QPushButton("Reset")
        reset_button.clicked.connect(self.reset_placement)
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
        placement_row.addWidget(reset_button)
        right_layout.addLayout(placement_row)

        splitter.addWidget(controls)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.statusBar().showMessage("Ready")

        self.setStyleSheet(MAIN_STYLESHEET)

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

    def _rebuild_team_fields(self) -> None:
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
        self._populate_combo_items()

    def _refresh_slot_display(self) -> None:
        for team_index, row in enumerate(self.team_combos):
            for slot_index, combo in enumerate(row):
                name = self.project.teams[team_index][slot_index].name
                if combo.currentText() != name:
                    combo.blockSignals(True)
                    combo.setCurrentText(name)
                    combo.blockSignals(False)

    def _on_slot_drag_started(self, team: int, slot: int) -> None:
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
            self._sync_controls()
            if self.assets:
                self.schedule_render()
        self._drag_snapshot = None
        self._drag_position = None

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
        self._sync_controls()
        if self.assets:
            self.schedule_render()

    def _populate_combo_items(self) -> None:
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
        uid = self.uid_edit.text().strip()
        self.project = Project.blank(mode, uid)
        self.project_path = None
        self.assets = {}
        self.selected = (0, 0)
        self.boss_combo.setVisible(mode == "stygian")
        self._rebuild_team_fields()
        self._sync_controls()
        self.preview.set_preview(QPixmap())

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
        self._sync_controls()
        if self.assets:
            self.schedule_render()

    def _member_changed(self, team: int, slot: int, name: str) -> None:
        member = self.project.teams[team][slot]
        old_name = member.name
        member.name = name.strip()
        if member.name and member.name.casefold() != old_name.casefold():
            self._presets.apply_to(self, member)
        self.assets = {key: value for key, value in self.assets.items() if key in self._selected_name_keys()}
        self._sync_controls()

    def _selected_name_keys(self) -> set[str]:
        return {member.name.casefold() for team in self.project.teams for member in team if member.name}

    def _save_current_preset(self) -> None:
        self._presets.remember(self, self.current_member())

    def current_member(self) -> Placement:
        team, slot = self.selected
        return self.project.teams[team][slot]

    def select_slot(self, team: int, slot: int) -> None:
        self.selected = (team, slot)
        self._sync_controls()

    def _sync_controls(self) -> None:
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
        self.preview.set_context(self.project.mode, self.project.active_team, self.selected)

    def _placement_slider_changed(self) -> None:
        if self._updating_controls:
            return
        member = self.current_member()
        member.offset_x = self.x_slider.value() / 1000
        member.offset_y = self.y_slider.value() / 1000
        member.zoom = self.zoom_slider.value() / 100
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def _flip_toggled(self, checked: bool) -> None:
        if self._updating_controls:
            return
        self.current_member().flip = checked
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def drag_placement(self, dx: float, dy: float) -> None:
        """Pan the selected portrait by a drag delta given in canvas pixels."""
        self._placement.pan(self.current_member(), dx, dy)
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def change_zoom(self, delta: float) -> None:
        self._placement.zoom_by(self.current_member(), delta)
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def reset_placement(self) -> None:
        self._placement.reset(self.current_member())
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def schedule_render(self) -> None:
        # A throttle, not a debounce: restarting the timer on every
        # mouse-move event would mean it never fires during a drag.
        if self.assets and not self._render_timer.isActive():
            self._render_timer.start(RENDER_THROTTLE_MS)

    def _show_error(self, title: str, error: Exception | str) -> None:
        QMessageBox.critical(self, title, str(error))
        self.statusBar().showMessage(str(error), 10000)

    def load_profile(self) -> None:
        uid = self.uid_edit.text().strip()
        self.project.uid = uid
        self.load_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            try:
                builds, age, last = self.client.load_profile(uid)
            except StaleProfileError as stale:
                dialog = QMessageBox(self)
                dialog.setWindowTitle("Akasha profile is older than one hour")
                dialog.setText(f"Last updated {stale.age_minutes / 60:.1f} hours ago.")
                refresh_button = dialog.addButton("Refresh now", QMessageBox.ButtonRole.AcceptRole)
                stale_button = dialog.addButton("Load anyway", QMessageBox.ButtonRole.ActionRole)
                dialog.addButton(QMessageBox.StandardButton.Cancel)
                dialog.exec()
                if dialog.clickedButton() == refresh_button:
                    self.statusBar().showMessage("Refreshing Akasha ...")
                    QApplication.restoreOverrideCursor()
                    if not self.client.refresh_profile(uid, progress=lambda text: self.statusBar().showMessage(text)):
                        raise AkashaError("Akasha refresh did not finish within 90 seconds.") from None
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                    builds, age, last = self.client.load_profile(uid)
                elif dialog.clickedButton() == stale_button:
                    builds, age, last = self.client.load_profile(uid, allow_stale=True)
                else:
                    return
            self.builds = {build.name.casefold(): build for build in builds}
            save_profile_cache(uid, builds, last)
            self.assets = {}
            self._populate_combo_items()
            local = last.astimezone().strftime("%Y-%m-%d %H:%M")
            self.profile_status.setText(f"{len(builds)} builds \u00b7 last updated {local} \u00b7 {age:.0f} min ago")
            self.statusBar().showMessage("Akasha profile loaded", 5000)
        except Exception as error:
            self._show_error("Could not load profile", error)
        finally:
            QApplication.restoreOverrideCursor()
            self.load_button.setEnabled(True)

    def paste_teams(self) -> None:
        expected = 8 if self.project.mode == "abyss" else 12
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Lineup",
            f"{expected} character names in order, separated by comma, semicolon, "
            "pipe (|), or newline:",
        )
        if not ok:
            return
        names = parse_lineup(text)
        if len(names) != expected:
            self._show_error("Invalid lineup", f"Expected {expected} names, found {len(names)}.")
            return
        for index, name in enumerate(names):
            team, slot = divmod(index, 4)
            self.team_combos[team][slot].setCurrentText(name)

    def _validate_team(self) -> list[Build]:
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
        self.assets[key] = asset
        for team in self.project.teams:
            for member in team:
                if member.name.casefold() == key:
                    self._presets.apply_to(self, member)
        self.schedule_render()

    def prepare_preview(self) -> None:
        try:
            builds = self._validate_team()
            self.preview_button.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self._generate_preview_from_builds(builds)
            self.statusBar().showMessage("Preview ready", 5000)
        except Exception as error:
            self._show_error("Could not generate preview", error)
        finally:
            QApplication.restoreOverrideCursor()
            self.preview_button.setEnabled(True)

    def _report_download_progress(self, current: int, total: int, name: str) -> None:
        self.statusBar().showMessage(f"Downloading {name} ({current}/{total}) ...")
        QApplication.processEvents()

    def _generate_preview_from_builds(self, builds: list[Build]) -> None:
        self.assets = {}
        self.assets = download_assets(
            builds,
            cache_dir() / "assets",
            progress=self._report_download_progress,
            on_asset=self._on_asset_ready,
        )
        for team in self.project.teams:
            for member in team:
                self._presets.apply_to(self, member)
        self._dispatch_render()

    def _dispatch_render(self) -> None:
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
        try:
            self._validate_team()
            if set(self._selected_name_keys()) - set(self.assets):
                self.prepare_preview()
            if set(self._selected_name_keys()) - set(self.assets):
                return
            stem = safe_name(self.output_name.text().strip() or "genshin_thumbnail")
            default_dir = self.project_path.parent if self.project_path else Path.cwd()
            if self.project.mode == "abyss":
                default_path = str(default_dir / f"{stem}.png")
                path, _ = QFileDialog.getSaveFileName(self, "Export PNG", default_path, "PNG (*.png)")
                if not path:
                    return
                target = Path(path)
                directory = target.parent
                stem = safe_name(target.stem)
            else:
                # Stygian writes three files at once, so only the folder can be chosen.
                directory_str = QFileDialog.getExistingDirectory(self, "Choose output folder", str(default_dir))
                if not directory_str:
                    return
                directory = Path(directory_str)
            self.output_name.setText(stem)
            self.project.output_name = stem
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            written = export_project(self.project, self.assets, directory)
            QMessageBox.information(self, "Export finished", "\n".join(str(path) for path in written))
            self.statusBar().showMessage(f"Exported {len(written)} thumbnail(s)", 7000)
        except Exception as error:
            self._show_error("Export failed", error)
        finally:
            QApplication.restoreOverrideCursor()

    def save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save project", "thumbnail-project.json", "JSON (*.json)")
        if not path:
            return
        with contextlib.suppress(ValueError):
            self._validate_team()
        self.project.uid = self.uid_edit.text().strip()
        self.project.output_name = self.output_name.text().strip() or "genshin_thumbnail"
        save_project(self.project, Path(path))
        self.project_path = Path(path)
        self.statusBar().showMessage("Project saved", 5000)

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open project", "", "JSON (*.json)")
        if not path:
            return
        try:
            project = load_project(Path(path))
            self.project = project
            self.project_path = Path(path)
            self.selected = (project.active_team if project.mode == "stygian" else 0, 0)
            self.assets = {}
            self.abyss_radio.blockSignals(True)
            self.stygian_radio.blockSignals(True)
            self.abyss_radio.setChecked(project.mode == "abyss")
            self.stygian_radio.setChecked(project.mode == "stygian")
            self.abyss_radio.blockSignals(False)
            self.stygian_radio.blockSignals(False)
            self.uid_edit.setText(project.uid)
            self.output_name.setText(project.output_name)
            self.boss_combo.setVisible(project.mode == "stygian")
            self.boss_combo.setCurrentIndex(project.active_team)
            self._rebuild_team_fields()
            self._sync_controls()
            cached = load_profile_cache(project.uid)
            if cached is None:
                self.statusBar().showMessage(
                    "Project opened \u00b7 no cached profile found for this UID", 8000
                )
                return
            builds, last_update = cached
            self.builds = {build.name.casefold(): build for build in builds}
            self._populate_combo_items()
            age_minutes = max(0.0, (datetime.now(timezone.utc) - last_update).total_seconds() / 60)
            local = last_update.astimezone().strftime("%Y-%m-%d %H:%M")
            self.profile_status.setText(
                f"{len(builds)} builds · from cache · last updated {local} · {age_minutes:.0f} min ago"
            )
            self._auto_preview()
            if age_minutes > 60:
                self._offer_cache_refresh(age_minutes)
            self.statusBar().showMessage("Project opened", 5000)
        except Exception as error:
            self._show_error("Could not open project", error)

    def _auto_preview(self) -> None:
        """Render a preview from already loaded builds, reporting failures without aborting the caller."""
        try:
            self._generate_preview_from_builds(self._validate_team())
        except Exception as error:
            self._show_error("Could not generate preview", error)

    def _offer_cache_refresh(self, age_minutes: float) -> None:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Cached profile is older than one hour")
        dialog.setText(f"Last updated {age_minutes / 60:.1f} hours ago.")
        refresh_button = dialog.addButton("Refresh now", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        if dialog.clickedButton() != refresh_button:
            return
        self.load_profile()
        if self.builds:
            self._auto_preview()
