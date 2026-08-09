"""Reading and writing the project's files: the JSON project itself and the
exported PNGs, as a `ProjectFiles` collaborator wired once to the window it
acts on.

Nothing here imports `MainWindow`, so the window can call into this module
without a cycle, the same reason `dialogs.py` gives. What the window has to
offer these flows is spelled out by the `ProjectEditor` Protocol below, which
`MainWindow` satisfies structurally.
"""

from __future__ import annotations

import contextlib
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QFileDialog, QMainWindow

from .. import storage
from ..models import Build, Project
from ..renderer import export_project, safe_name
from . import dialogs
from .asset_loader import AssetLoader
from .controls_panel import ControlsPanel
from .history import HistoryController
from .state import EditorState


class ProjectEditor(EditorState, Protocol):
    """What the project file flows read and write on the editor.

    `MainWindow` satisfies it structurally; nothing has to declare it.
    Like the other collaborators, `ProjectFiles` reads the attributes
    through the Protocol on every call rather than capturing them,
    because the window replaces `project`, `builds` and `assets`
    wholesale in several places; see `state.py`.
    """

    project_path: Path | None
    saved_snapshot: Project
    selected: tuple[int, int]
    asset_loader: AssetLoader
    controls_panel: ControlsPanel
    boss_combo: QComboBox

    def validate_team(self) -> list[Build]: ...
    def selected_name_keys(self) -> set[str]: ...
    def rebuild_team_fields(self) -> None: ...
    def sync_controls(self) -> None: ...
    def populate_combo_items(self) -> None: ...
    def schedule_render(self) -> None: ...
    def load_profile(self) -> None: ...
    def set_project_path(self, path: Path | None) -> None: ...


class ProjectFiles:
    """The project file flows, wired once to the window they act on.

    Takes the window twice, as `parent` for the dialogs and the status bar
    and as `editor` for everything else, because a Protocol cannot inherit
    from `QWidget`. The `HistoryController` is a constructor argument like
    the rest, which keeps `MainWindow._history` private.
    """

    def __init__(self, parent: QMainWindow, editor: ProjectEditor, history: HistoryController) -> None:
        self._parent = parent
        self._editor = editor
        self._history = history

    def save(self) -> None:
        """Overwrite the project's own file, or ask for one when it has none."""
        if self._editor.project_path is None:
            self.save_as()
            return
        self._write_project(self._editor.project_path)

    def save_as(self) -> None:
        """Ask for a path, write there, and adopt it as the project's file."""
        default = str(self._editor.project_path or "thumbnail-project.json")
        path, _ = QFileDialog.getSaveFileName(self._parent, "Save project", default, "JSON (*.json)")
        if not path:
            return
        self._write_project(Path(path))

    def _write_project(self, path: Path) -> None:
        editor = self._editor
        controls = editor.controls_panel
        with contextlib.suppress(ValueError):
            editor.validate_team()
        editor.project.uid = controls.uid_edit.text().strip()
        editor.project.output_name = controls.output_name.text().strip() or "genshin_thumbnail"
        storage.save_project(editor.project, path)
        editor.set_project_path(path)
        editor.saved_snapshot = copy.deepcopy(editor.project)
        self._parent.statusBar().showMessage("Project saved", 5000)

    def open(self) -> None:
        parent = self._parent
        editor = self._editor
        controls = editor.controls_panel
        path, _ = QFileDialog.getOpenFileName(parent, "Open project", "", "JSON (*.json)")
        if not path:
            return
        try:
            project = storage.load_project(Path(path))
            editor.project = project
            editor.set_project_path(Path(path))
            editor.selected = (project.active_team if project.mode == "stygian" else 0, 0)
            editor.assets = {}
            controls.abyss_radio.blockSignals(True)
            controls.stygian_radio.blockSignals(True)
            controls.abyss_radio.setChecked(project.mode == "abyss")
            controls.stygian_radio.setChecked(project.mode == "stygian")
            controls.abyss_radio.blockSignals(False)
            controls.stygian_radio.blockSignals(False)
            controls.uid_edit.setText(project.uid)
            controls.output_name.setText(project.output_name)
            editor.boss_combo.setVisible(project.mode == "stygian")
            editor.boss_combo.setCurrentIndex(project.active_team)
            editor.rebuild_team_fields()
            editor.sync_controls()
            cached = storage.load_profile_cache(project.uid)
            if cached is None:
                parent.statusBar().showMessage(
                    "Project opened \u00b7 no cached profile found for this UID", 8000
                )
                self._history.reset()
                editor.saved_snapshot = copy.deepcopy(editor.project)
                return
            builds, last_update = cached
            editor.builds = {build.name.casefold(): build for build in builds}
            editor.populate_combo_items()
            age_minutes = max(0.0, (datetime.now(timezone.utc) - last_update).total_seconds() / 60)
            local = last_update.astimezone().strftime("%Y-%m-%d %H:%M")
            controls.profile_status.setText(
                f"{len(builds)} builds · from cache · last updated {local} · {age_minutes:.0f} min ago"
            )
            editor.asset_loader.ensure()
            editor.schedule_render()
            if age_minutes > 60 and dialogs.confirm_cache_refresh(parent, age_minutes):
                editor.load_profile()
                if editor.builds:
                    editor.asset_loader.ensure()
            self._history.reset()
            editor.saved_snapshot = copy.deepcopy(editor.project)
            parent.statusBar().showMessage("Project opened", 5000)
        except Exception as error:
            dialogs.show_error(parent, "Could not open project", error)

    def export(self) -> None:
        parent = self._parent
        editor = self._editor
        output_name = editor.controls_panel.output_name
        try:
            editor.validate_team()
            if set(editor.selected_name_keys()) - set(editor.assets):
                # The download can no longer be awaited here, so start it and
                # let the user come back once the preview has filled in.
                editor.asset_loader.ensure()
                dialogs.show_error(parent, "Character art is still downloading", "Try the export again in a moment.")
                return
            stem = safe_name(output_name.text().strip() or "genshin_thumbnail")
            default_dir = editor.project_path.parent if editor.project_path else Path.cwd()
            target = dialogs.ask_export_target(parent, editor.project.mode, default_dir, stem)
            if target is None:
                return
            directory, chosen_stem = target
            stem = safe_name(chosen_stem)
            output_name.setText(stem)
            editor.project.output_name = stem
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            written = export_project(editor.project, editor.assets, directory)
            dialogs.show_export_finished(parent, written)
            parent.statusBar().showMessage(f"Exported {len(written)} thumbnail(s)", 7000)
        except Exception as error:
            dialogs.show_error(parent, "Export failed", error)
        finally:
            QApplication.restoreOverrideCursor()
