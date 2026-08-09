"""Fetching an Akasha profile and entering a lineup by hand, as a
`ProfileLoader` collaborator wired once to the window it acts on.

Nothing here imports `MainWindow`, so the window can call into this module
without a cycle, the same reason `dialogs.py` gives. What the window has to
offer these flows is spelled out by the `ProfileEditor` Protocol below, which
`MainWindow` satisfies structurally.
"""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMainWindow

from ..akasha import AkashaError, AkashaWebClient, Build, StaleProfileError
from ..storage import save_profile_cache
from . import dialogs
from .asset_loader import AssetLoader
from .controls_panel import ControlsPanel
from .lineup import parse_lineup
from .state import EditorState
from .team_fields import TeamFieldsController


class ProfileEditor(EditorState, Protocol):
    """What the profile flows read and write on the editor.

    `MainWindow` satisfies it structurally; nothing has to declare it.
    Like the other collaborators, `ProfileLoader` reads the attributes
    through the Protocol on every call rather than capturing them,
    because the window replaces `project`, `builds` and `assets`
    wholesale in several places; see `state.py`.
    """

    client: AkashaWebClient
    asset_loader: AssetLoader
    controls_panel: ControlsPanel
    team_fields: TeamFieldsController

    def schedule_render(self) -> None: ...


class ProfileLoader:
    """Profile fetching and lineup entry, wired once to the window they act on.

    Takes the window twice, as `parent` for the dialogs and the status bar
    and as `editor` for everything else, because a Protocol cannot inherit
    from `QWidget`, the same reason `project_io.py` gives.
    """

    def __init__(self, parent: QMainWindow, editor: ProfileEditor) -> None:
        self._parent = parent
        self._editor = editor

    def load(self) -> None:
        editor = self._editor
        controls = editor.controls_panel
        uid = controls.uid_edit.text().strip()
        editor.project.uid = uid
        controls.load_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            try:
                builds, age, last = editor.client.load_profile(uid)
            except StaleProfileError as stale:
                choice = dialogs.choose_stale_profile_action(self._parent, stale.age_minutes)
                if choice == "refresh":
                    self._parent.statusBar().showMessage("Refreshing Akasha ...")
                    QApplication.restoreOverrideCursor()
                    if not editor.client.refresh_profile(
                        uid, progress=lambda text: self._parent.statusBar().showMessage(text)
                    ):
                        raise AkashaError("Akasha refresh did not finish within 90 seconds.") from None
                    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                    builds, age, last = editor.client.load_profile(uid)
                elif choice == "stale":
                    builds, age, last = editor.client.load_profile(uid, allow_stale=True)
                else:
                    return
            editor.builds = {build.name.casefold(): build for build in builds}
            save_profile_cache(uid, builds, last)
            editor.assets = {}
            editor.team_fields.populate_items()
            local = last.astimezone().strftime("%Y-%m-%d %H:%M")
            controls.profile_status.setText(
                f"{len(builds)} builds \u00b7 last updated {local} \u00b7 {age:.0f} min ago"
            )
            self._parent.statusBar().showMessage("Akasha profile loaded", 5000)
            editor.asset_loader.ensure()
            editor.schedule_render()
        except Exception as error:
            dialogs.show_error(self._parent, "Could not load profile", error)
        finally:
            QApplication.restoreOverrideCursor()
            controls.load_button.setEnabled(True)

    def paste_lineup(self) -> None:
        editor = self._editor
        expected = 8 if editor.project.mode == "abyss" else 12
        text = dialogs.ask_lineup_text(self._parent, expected)
        if text is None:
            return
        names = parse_lineup(text)
        if len(names) != expected:
            dialogs.show_error(self._parent, "Invalid lineup", f"Expected {expected} names, found {len(names)}.")
            return
        for index, name in enumerate(names):
            team, slot = divmod(index, 4)
            editor.team_fields.combos[team][slot].setCurrentText(name)

    def validate_team(self) -> list[Build]:
        editor = self._editor
        missing: list[str] = []
        selected: list[Build] = []
        for team_index, row in enumerate(editor.team_fields.combos):
            for slot_index, combo in enumerate(row):
                name = combo.currentText().strip()
                editor.project.teams[team_index][slot_index].name = name
                build = editor.builds.get(name.casefold())
                if build is None:
                    missing.append(f"{team_index + 1}-{slot_index + 1}: {name or 'empty'}")
                else:
                    selected.append(build)
        if missing:
            raise ValueError("Build not in the loaded profile: " + ", ".join(missing))
        unique: dict[str, Build] = {build.name.casefold(): build for build in selected}
        return list(unique.values())
