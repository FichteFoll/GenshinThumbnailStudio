from __future__ import annotations

import re
from datetime import timezone
from pathlib import Path

from PIL.ImageQt import ImageQt
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
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

from .akasha import AkashaError, AkashaWebClient, Build, StaleProfileError, download_assets
from .models import Asset, Placement, Project
from .renderer import export_project, render_preview
from .storage import cache_dir, load_presets, load_project, save_presets, save_project


RESOLUTION_OPTIONS = [
    ("720p", 720),
    ("1080p", 1080),
    ("1440p", 1440),
    ("2160p", 2160),
]


class PreviewWidget(QFrame):
    slot_selected = Signal(int, int)
    placement_dragged = Signal(float, float)
    zoom_requested = Signal(float)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(640, 360)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._pixmap: QPixmap | None = None
        self._mode = "abyss"
        self._active_team = 0
        self._selected = (0, 0)
        self._drag_last: QPoint | None = None

    def set_preview(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def set_context(self, mode: str, active_team: int, selected: tuple[int, int]) -> None:
        self._mode = mode
        self._active_team = active_team
        self._selected = selected
        self.update()

    def _image_rect(self) -> QRect:
        if not self._pixmap:
            return QRect()
        fitted = self._pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width() - fitted.width()) // 2, (self.height() - fitted.height()) // 2, fitted.width(), fitted.height())

    def _image_point(self, point: QPoint) -> tuple[float, float] | None:
        rect = self._image_rect()
        if rect.isEmpty() or not rect.contains(point):
            return None
        return (
            (point.x() - rect.x()) * 1280 / rect.width(),
            (point.y() - rect.y()) * 720 / rect.height(),
        )

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#111216"))
        rect = self._image_rect()
        if not self._pixmap or rect.isEmpty():
            painter.setPen(QColor("#8f96a3"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Profil laden und Vorschau erzeugen")
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(rect, self._pixmap)

        team, slot = self._selected
        visible_team = team if self._mode == "abyss" else 0
        if self._mode == "stygian" and team != self._active_team:
            return
        cell_w = rect.width() / 4
        cell_h = rect.height() / (2 if self._mode == "abyss" else 1)
        highlight = QRect(
            int(rect.x() + slot * cell_w),
            int(rect.y() + visible_team * cell_h),
            int(cell_w),
            int(cell_h),
        ).adjusted(3, 3, -3, -3)
        painter.setPen(QPen(QColor("#ffd95d"), 3))
        painter.drawRect(highlight)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self._image_point(event.position().toPoint())
        if point is None:
            return
        x, y = point
        slot = min(3, max(0, int(x // 320)))
        team = min(1, max(0, int(y // 360))) if self._mode == "abyss" else self._active_team
        self._selected = (team, slot)
        self._drag_last = event.position().toPoint()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.slot_selected.emit(team, slot)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_last is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        rect = self._image_rect()
        if rect.isEmpty():
            return
        current = event.position().toPoint()
        delta = current - self._drag_last
        self._drag_last = current
        image_dx = delta.x() * 1280 / rect.width()
        image_dy = delta.y() * 720 / rect.height()
        self.placement_dragged.emit(-image_dx / 900.0, -image_dy / 700.0)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_last = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._image_point(event.position().toPoint()) is None:
            return
        self.zoom_requested.emit(0.04 if event.angleDelta().y() > 0 else -0.04)
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Genshin Thumbnail Studio")
        self.resize(1380, 860)
        self.setMinimumSize(1020, 680)
        self.project = Project.blank("abyss")
        self.builds: dict[str, Build] = {}
        self.assets: dict[str, Asset] = {}
        self.presets = load_presets()
        self.selected = (0, 0)
        self._updating_controls = False
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self.render_preview)
        self.client = AkashaWebClient(cache_dir())
        self.team_combos: list[list[QComboBox]] = []
        self._build_ui()
        self._rebuild_team_fields()
        self._sync_controls()

    def _icon(self, standard: QStyle.StandardPixmap):
        return self.style().standardIcon(standard)

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
        self.load_button = QPushButton("Profil laden")
        self.load_button.clicked.connect(self.load_profile)
        uid_row.addWidget(self.uid_edit, 1)
        uid_row.addWidget(self.load_button)
        controls_layout.addLayout(uid_row)

        self.profile_status = QLabel("Kein Profil geladen")
        self.profile_status.setObjectName("secondary")
        self.profile_status.setWordWrap(True)
        controls_layout.addWidget(self.profile_status)

        paste_button = QPushButton("Teamaufstellung einf\u00fcgen")
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
        self.output_name.textChanged.connect(lambda value: setattr(self.project, "output_name", value))
        output_form.addRow("Dateiname", self.output_name)
        self.resolution_combo = QComboBox()
        for label, height in RESOLUTION_OPTIONS:
            self.resolution_combo.addItem(label, height)
        self.resolution_combo.currentIndexChanged.connect(self._resolution_changed)
        output_form.addRow("Auflösung", self.resolution_combo)
        controls_layout.addLayout(output_form)

        project_row = QHBoxLayout()
        open_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogOpenButton), "Projekt \u00f6ffnen")
        save_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogSaveButton), "Projekt speichern")
        open_button.clicked.connect(self.open_project)
        save_button.clicked.connect(self.save_project)
        project_row.addWidget(open_button)
        project_row.addWidget(save_button)
        controls_layout.addLayout(project_row)

        self.preview_button = QPushButton("Vorschau erzeugen")
        self.preview_button.clicked.connect(self.prepare_preview)
        self.export_button = QPushButton(self._icon(QStyle.StandardPixmap.SP_DialogSaveButton), "PNG exportieren")
        self.export_button.clicked.connect(self.export)
        controls_layout.addWidget(self.preview_button)
        controls_layout.addWidget(self.export_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(12, 16, 16, 16)
        right_layout.setSpacing(10)

        preview_toolbar = QHBoxLayout()
        self.preview_team_label = QLabel("Vorschau")
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
        self.selected_label = QLabel("Team 1, Figur 1")
        self.x_slider = self._slider(0, 1000, 500)
        self.y_slider = self._slider(0, 1000, 520)
        self.zoom_slider = self._slider(70, 180, 106)
        self.x_value = QLabel("50%")
        self.y_value = QLabel("52%")
        self.zoom_value = QLabel("106%")
        for slider in [self.x_slider, self.y_slider, self.zoom_slider]:
            slider.valueChanged.connect(self._placement_slider_changed)
        reset_button = QPushButton("Zur\u00fccksetzen")
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
        placement_row.addWidget(reset_button)
        right_layout.addLayout(placement_row)

        splitter.addWidget(controls)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.statusBar().showMessage("Bereit")

        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #1a1b20; color: #f1f2f4; }
            QLineEdit, QComboBox { background: #26282f; border: 1px solid #484b55; padding: 6px; min-height: 22px; }
            QPushButton { background: #30333b; border: 1px solid #515561; padding: 7px 10px; }
            QPushButton:hover { background: #3a3e48; border-color: #777d8b; }
            QPushButton:pressed { background: #25272d; }
            QRadioButton { spacing: 6px; }
            QSlider::groove:horizontal { height: 4px; background: #454954; }
            QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #ffd95d; border-radius: 7px; }
            QLabel#secondary { color: #aeb3bf; }
            QScrollArea { background: transparent; }
            """
        )

    @staticmethod
    def _slider(minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setMinimumWidth(80)
        return slider

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())  # type: ignore[arg-type]

    def _rebuild_team_fields(self) -> None:
        self._clear_layout(self.team_layout)
        self.team_combos = []
        for team_index, team in enumerate(self.project.teams):
            title = QLabel(f"{'Team' if self.project.mode == 'abyss' else 'Boss'} {team_index + 1}")
            title.setStyleSheet("font-weight: 600;")
            self.team_layout.addWidget(title)
            grid = QGridLayout()
            row_combos = []
            for slot_index, member in enumerate(team):
                combo = QComboBox()
                combo.setEditable(True)
                combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
                combo.setPlaceholderText(f"Figur {slot_index + 1}")
                if member.name:
                    combo.setCurrentText(member.name)
                combo.currentTextChanged.connect(
                    lambda value, t=team_index, s=slot_index: self._member_changed(t, s, value)
                )
                grid.addWidget(QLabel(str(slot_index + 1)), slot_index, 0)
                grid.addWidget(combo, slot_index, 1)
                row_combos.append(combo)
            self.team_layout.addLayout(grid)
            self.team_combos.append(row_combos)
        self.team_layout.addStretch(1)
        self._populate_combo_items()

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
        self.assets = {}
        self.selected = (0, 0)
        self.boss_combo.setVisible(mode == "stygian")
        self._rebuild_team_fields()
        self._sync_controls()
        self.preview.set_preview(QPixmap())

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
            self._apply_preset(member)
        self.assets = {key: value for key, value in self.assets.items() if key in self._selected_name_keys()}
        self._sync_controls()

    def _selected_name_keys(self) -> set[str]:
        return {member.name.casefold() for team in self.project.teams for member in team if member.name}

    def _preset_key(self, member: Placement) -> str:
        build = self.builds.get(member.name.casefold())
        identity = build.costume_id if build and build.costume_id else (build.build_id if build else member.name.casefold())
        return f"{self.project.mode}|{identity}"

    def _apply_preset(self, member: Placement) -> None:
        preset = self.presets.get(self._preset_key(member))
        if preset:
            member.fx = float(preset.get("fx", member.fx))
            member.fy = float(preset.get("fy", member.fy))
            member.zoom = float(preset.get("zoom", member.zoom))

    def _save_current_preset(self) -> None:
        member = self.current_member()
        if not member.name:
            return
        self.presets[self._preset_key(member)] = {"fx": member.fx, "fy": member.fy, "zoom": member.zoom}
        save_presets(self.presets)

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
        self.x_slider.setValue(int(round(member.fx * 1000)))
        self.y_slider.setValue(int(round(member.fy * 1000)))
        self.zoom_slider.setValue(int(round(member.zoom * 100)))
        resolution_index = self.resolution_combo.findData(self.project.output_height)
        self.resolution_combo.setCurrentIndex(resolution_index if resolution_index >= 0 else 1)
        self._updating_controls = False
        label = "Team" if self.project.mode == "abyss" else "Boss"
        self.selected_label.setText(f"{label} {team + 1}, Figur {slot + 1}")
        self.x_value.setText(f"{member.fx * 100:.0f}%")
        self.y_value.setText(f"{member.fy * 100:.0f}%")
        self.zoom_value.setText(f"{member.zoom * 100:.0f}%")
        self.preview.set_context(self.project.mode, self.project.active_team, self.selected)

    def _placement_slider_changed(self) -> None:
        if self._updating_controls:
            return
        member = self.current_member()
        member.fx = self.x_slider.value() / 1000
        member.fy = self.y_slider.value() / 1000
        member.zoom = self.zoom_slider.value() / 100
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def drag_placement(self, dx: float, dy: float) -> None:
        member = self.current_member()
        member.fx = min(1.0, max(0.0, member.fx + dx))
        member.fy = min(1.0, max(0.0, member.fy + dy))
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def change_zoom(self, delta: float) -> None:
        member = self.current_member()
        member.zoom = min(1.80, max(0.70, member.zoom + delta))
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def reset_placement(self) -> None:
        member = self.current_member()
        member.fx = 0.50
        member.fy = 0.52
        member.zoom = 1.06 if self.project.mode == "abyss" else 1.18
        self._save_current_preset()
        self._sync_controls()
        self.schedule_render()

    def schedule_render(self) -> None:
        if self.assets:
            self._render_timer.start(80)

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
                dialog.setWindowTitle("Akasha-Profil ist \u00e4lter als eine Stunde")
                dialog.setText(f"Letzte Aktualisierung vor {stale.age_minutes / 60:.1f} Stunden.")
                refresh_button = dialog.addButton("Jetzt aktualisieren", QMessageBox.ButtonRole.AcceptRole)
                stale_button = dialog.addButton("Trotzdem laden", QMessageBox.ButtonRole.ActionRole)
                dialog.addButton(QMessageBox.StandardButton.Cancel)
                dialog.exec()
                if dialog.clickedButton() == refresh_button:
                    self.statusBar().showMessage("Akasha wird aktualisiert ...")
                    QApplication.restoreOverrideCursor()
                    if not self.client.refresh_profile(uid, progress=lambda text: self.statusBar().showMessage(text)):
                        raise AkashaError("Akasha refresh did not finish within 90 seconds.")
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                    builds, age, last = self.client.load_profile(uid)
                elif dialog.clickedButton() == stale_button:
                    builds, age, last = self.client.load_profile(uid, allow_stale=True)
                else:
                    return
            self.builds = {build.name.casefold(): build for build in builds}
            self.assets = {}
            self._populate_combo_items()
            local = last.astimezone().strftime("%d.%m.%Y %H:%M")
            self.profile_status.setText(f"{len(builds)} Builds \u00b7 zuletzt aktualisiert {local} \u00b7 vor {age:.0f} min")
            self.statusBar().showMessage("Akasha-Profil geladen", 5000)
        except Exception as error:
            self._show_error("Profil konnte nicht geladen werden", error)
        finally:
            QApplication.restoreOverrideCursor()
            self.load_button.setEnabled(True)

    def paste_teams(self) -> None:
        expected = 8 if self.project.mode == "abyss" else 12
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Teamaufstellung",
            f"{expected} Figurennamen in Reihenfolge, getrennt durch Komma oder Zeilenumbruch:",
        )
        if not ok:
            return
        names = [value.strip() for value in re.split(r"[,;\n]+", text) if value.strip()]
        if len(names) != expected:
            self._show_error("Ung\u00fcltige Teamaufstellung", f"Erwartet: {expected} Namen. Gefunden: {len(names)}.")
            return
        for index, name in enumerate(names):
            team, slot = divmod(index, 4)
            self.team_combos[team][slot].setCurrentText(name)

    def _validate_team(self) -> list[Build]:
        missing = []
        selected = []
        for team_index, row in enumerate(self.team_combos):
            for slot_index, combo in enumerate(row):
                name = combo.currentText().strip()
                self.project.teams[team_index][slot_index].name = name
                build = self.builds.get(name.casefold())
                if build is None:
                    missing.append(f"{team_index + 1}-{slot_index + 1}: {name or 'leer'}")
                else:
                    selected.append(build)
        if missing:
            raise ValueError("Build nicht im geladenen Profil: " + ", ".join(missing))
        unique = {build.name.casefold(): build for build in selected}
        return list(unique.values())

    def prepare_preview(self) -> None:
        try:
            builds = self._validate_team()
            self.preview_button.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.assets = download_assets(
                builds,
                cache_dir() / "assets",
                progress=lambda current, total, name: (
                    self.statusBar().showMessage(f"Lade {name} ({current}/{total}) ..."),
                    QApplication.processEvents(),
                ),
            )
            for team in self.project.teams:
                for member in team:
                    self._apply_preset(member)
            self.render_preview()
            self.statusBar().showMessage("Vorschau bereit", 5000)
        except Exception as error:
            self._show_error("Vorschau konnte nicht erzeugt werden", error)
        finally:
            QApplication.restoreOverrideCursor()
            self.preview_button.setEnabled(True)

    def render_preview(self) -> None:
        try:
            image = render_preview(self.project, self.assets)
            self.preview.set_preview(QPixmap.fromImage(ImageQt(image)))
        except Exception as error:
            self.statusBar().showMessage(str(error), 8000)

    def export(self) -> None:
        try:
            self._validate_team()
            if set(self._selected_name_keys()) - set(self.assets):
                self.prepare_preview()
            if set(self._selected_name_keys()) - set(self.assets):
                return
            directory = QFileDialog.getExistingDirectory(self, "Ausgabeordner w\u00e4hlen")
            if not directory:
                return
            self.project.output_name = self.output_name.text().strip() or "genshin_thumbnail"
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            written = export_project(self.project, self.assets, Path(directory))
            QMessageBox.information(self, "Export abgeschlossen", "\n".join(str(path) for path in written))
            self.statusBar().showMessage(f"{len(written)} Thumbnail(s) exportiert", 7000)
        except Exception as error:
            self._show_error("Export fehlgeschlagen", error)
        finally:
            QApplication.restoreOverrideCursor()

    def save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Projekt speichern", "thumbnail-project.json", "JSON (*.json)")
        if not path:
            return
        try:
            self._validate_team()
        except ValueError:
            pass
        self.project.uid = self.uid_edit.text().strip()
        self.project.output_name = self.output_name.text().strip() or "genshin_thumbnail"
        save_project(self.project, Path(path))
        self.statusBar().showMessage("Projekt gespeichert", 5000)

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Projekt \u00f6ffnen", "", "JSON (*.json)")
        if not path:
            return
        try:
            project = load_project(Path(path))
            self.project = project
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
            self.statusBar().showMessage("Projekt ge\u00f6ffnet", 5000)
        except Exception as error:
            self._show_error("Projekt konnte nicht ge\u00f6ffnet werden", error)


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setApplicationName("Genshin Thumbnail Studio")
    app.setOrganizationName("GenshinThumbnailStudio")
    window = MainWindow()
    window.show()
    return app.exec()
