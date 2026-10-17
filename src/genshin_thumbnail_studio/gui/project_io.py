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
from datetime import datetime
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow

from .. import storage
from ..enka import is_uid
from ..models import Build, Project
from ..renderer import export_project, safe_name
from . import dialogs
from .asset_loader import AssetLoader
from .build_choices import resolve_build
from .controls_panel import ControlsPanel
from .editor_panel import EditorPanel
from .history import HistoryController
from .state import EditorState


class ProjectEditor(EditorState, Protocol):
    """What the project file flows read and write on the editor.

    `MainWindow` satisfies it structurally; nothing has to declare it.
    Like the other collaborators, `ProjectFiles` reads the attributes
    through the Protocol on every call rather than capturing them,
    because the window replaces `project` and `builds`
    wholesale in several places; see `state.py`.
    """

    project_path: Path | None
    saved_snapshot: Project
    selected: tuple[int, int]
    asset_loader: AssetLoader
    controls_panel: ControlsPanel
    editor_panel: EditorPanel

    def validate_team(self) -> list[Build]: ...
    def rebuild_team_fields(self) -> None: ...
    def sync_controls(self) -> None: ...
    def populate_combo_items(self) -> None: ...
    def schedule_render(self) -> None: ...
    def load_profile(self) -> None: ...
    def set_project_path(self, path: Path | None) -> None: ...
    def is_dirty(self) -> bool: ...
    def save_project(self) -> None: ...


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
        identifier = controls.profile_edit.text().strip()
        editor.project.uid = identifier if is_uid(identifier) else ""
        editor.project.profile_name = "" if is_uid(identifier) else identifier
        editor.project.output_name = controls.output_name.text().strip() or "genshin_thumbnail"
        try:
            storage.save_project(editor.project, path)
        except Exception as error:
            dialogs.show_error(self._parent, "Could not save project", error)
            return
        editor.set_project_path(path)
        editor.saved_snapshot = copy.deepcopy(editor.project)
        self._parent.statusBar().showMessage("Project saved", 5000)

    def new(self) -> None:
        """Reset to a blank abyss project, keeping the profile/UID (R14)."""
        parent = self._parent
        editor = self._editor
        controls = editor.controls_panel
        if not dialogs.confirm_discard_changes(parent, "start a new project", editor.is_dirty, editor.save_project):
            return
        old_project = editor.project
        editor.project = Project.blank("abyss", old_project.uid)
        editor.project.profile_name = old_project.profile_name
        editor.set_project_path(None)
        editor.selected = (0, 0)
        controls.abyss_radio.blockSignals(True)
        controls.stygian_radio.blockSignals(True)
        controls.abyss_radio.setChecked(True)
        controls.stygian_radio.setChecked(False)
        controls.abyss_radio.blockSignals(False)
        controls.stygian_radio.blockSignals(False)
        controls.output_name.setText("genshin_thumbnail")
        controls.resolution_combo.setCurrentIndex(controls.resolution_combo.findData(1080))
        boss_combo = editor.editor_panel.boss_combo
        boss_combo.setVisible(False)
        boss_combo.setCurrentIndex(0)
        editor.rebuild_team_fields()
        editor.sync_controls()
        editor.schedule_render()
        self._history.reset()
        editor.saved_snapshot = copy.deepcopy(editor.project)

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
            controls.abyss_radio.blockSignals(True)
            controls.stygian_radio.blockSignals(True)
            controls.abyss_radio.setChecked(project.mode == "abyss")
            controls.stygian_radio.setChecked(project.mode == "stygian")
            controls.abyss_radio.blockSignals(False)
            controls.stygian_radio.blockSignals(False)
            controls.profile_edit.setText(project.identifier)
            controls.output_name.setText(project.output_name)
            boss_combo = editor.editor_panel.boss_combo
            boss_combo.setVisible(project.mode == "stygian")
            boss_combo.setCurrentIndex(project.active_team)
            editor.rebuild_team_fields()
            editor.sync_controls()
            # By `identifier`, so a project carrying a profile name loads
            # through the name rather than through the UID beside it.
            cached = storage.load_profile_cache(project.identifier)
            if cached is None:
                parent.statusBar().showMessage(
                    "Project opened \u00b7 no cached profile found for this profile", 8000
                )
                self._history.reset()
                editor.saved_snapshot = copy.deepcopy(editor.project)
                return
            editor.builds = cached.builds
            for team in editor.project.teams:
                for member in team:
                    if member.name:
                        resolve_build(editor, member)
            editor.populate_combo_items()
            # `astimezone()` on both sides, because the cache is written from a
            # naive local timestamp and has to compare against the local clock.
            fetched = cached.fetched_at.astimezone()
            age_minutes = max(0.0, (datetime.now().astimezone() - fetched).total_seconds() / 60)
            local = fetched.strftime("%Y-%m-%d %H:%M")
            controls.profile_status.setText(
                f"{len(cached.builds)} characters · from cache · fetched {local} · {age_minutes:.0f} min ago"
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

    def _every_named_slot_has_its_files(self) -> bool:
        """Whether every named slot's art *and* weapon icon are cached.

        `validate_team()` has just written a build onto every named placement,
        so each one can be asked for its own two paths; a file exists there only
        once it has been downloaded and validated.
        """
        editor = self._editor
        root = editor.art_root
        return all(
            member.build is not None
            and member.build.art_path(root).exists()
            and member.build.weapon_path(root).exists()
            for team in editor.project.teams
            for member in team
            if member.name
        )

    def export(self) -> None:
        parent = self._parent
        editor = self._editor
        output_name = editor.controls_panel.output_name
        try:
            editor.validate_team()
            if not self._every_named_slot_has_its_files():
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
            written = export_project(editor.project, editor.art_root, directory)
            parent.statusBar().showMessage(f"Exported {len(written)} thumbnail(s)", 7000)
        except Exception as error:
            dialogs.show_error(parent, "Export failed", error)
        finally:
            QApplication.restoreOverrideCursor()
