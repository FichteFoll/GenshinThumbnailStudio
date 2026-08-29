"""Fetching a profile from Enka and entering a lineup by hand, as a
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

from ..enka import Build, EnkaClient, is_uid
from ..storage import save_last_profile, save_profile_cache
from . import dialogs
from .asset_loader import AssetLoader
from .build_choices import resolve_build
from .controls_panel import ControlsPanel
from .lineup import parse_lineup
from .state import EditorState
from .team_fields import TeamFieldsController


class ProfileEditor(EditorState, Protocol):
    """What the profile flows read and write on the editor.

    `MainWindow` satisfies it structurally; nothing has to declare it.
    Like the other collaborators, `ProfileLoader` reads the attributes
    through the Protocol on every call rather than capturing them,
    because the window replaces `project` and `builds`
    wholesale in several places; see `state.py`.
    """

    client: EnkaClient
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
        identifier = controls.profile_edit.text().strip()
        # Exactly one of the two: the field holds either a UID or a username,
        # and `Project.identifier` reads the name first.
        editor.project.uid = identifier if is_uid(identifier) else ""
        editor.project.profile_name = "" if is_uid(identifier) else identifier
        controls.load_button.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        showcase: list[Build] = []
        try:
            profile = editor.client.load_profile(identifier)
            editor.builds = profile.builds
            save_profile_cache(profile)
            save_last_profile(identifier)
            for team in editor.project.teams:
                for member in team:
                    if member.name:
                        resolve_build(editor, member)
            editor.team_fields.populate_items()
            label = profile.username or f"UID {profile.uid}"
            local = profile.fetched_at.astimezone().strftime("%Y-%m-%d %H:%M")
            controls.profile_status.setText(
                f"{len(profile.builds)} characters \u00b7 {label} \u00b7 fetched {local}"
            )
            self._parent.statusBar().showMessage("Enka profile loaded", 5000)
            editor.asset_loader.ensure()
            editor.schedule_render()
            showcase = profile.live_builds()
        except Exception as error:
            dialogs.show_error(self._parent, "Could not load profile", error)
        finally:
            QApplication.restoreOverrideCursor()
            controls.load_button.setEnabled(True)
        # Outside the wait cursor, which a modal prompt must not be shown under.
        self._offer_showcase_lineup(showcase)

    def _offer_showcase_lineup(self, showcase: list[Build]) -> None:
        """Offer to fill the teams when the showcase is exactly one lineup long.

        A showcase of that size is the lineup itself, so the only thing left to
        decide is which slot each character belongs in, and dragging the filled
        slots into place answers that faster than a dialog could ask it.
        """
        if len(showcase) != self._expected_lineup_size():
            return
        names = [build.name for build in showcase]
        if not dialogs.confirm_showcase_lineup(self._parent, names):
            return
        self._fill_lineup(names)

    def _expected_lineup_size(self) -> int:
        return 8 if self._editor.project.mode == "abyss" else 12

    def _fill_lineup(self, names: list[str]) -> None:
        """Write the names into the slots in order, one team after the other.

        Through the combos rather than onto the placements, so each slot goes
        through `member_changed()` and resolves its build, presets and art.
        """
        for index, name in enumerate(names):
            team, slot = divmod(index, 4)
            self._editor.team_fields.combos[team][slot].setCurrentText(name)

    def paste_lineup(self) -> None:
        expected = self._expected_lineup_size()
        text = dialogs.ask_lineup_text(self._parent, expected)
        if text is None:
            return
        names = parse_lineup(text)
        if len(names) != expected:
            dialogs.show_error(self._parent, "Invalid lineup", f"Expected {expected} names, found {len(names)}.")
            return
        self._fill_lineup(names)

    def validate_team(self) -> list[Build]:
        """The builds the named slots are framed with, one per distinct download.

        Deduplicated by the pair of URLs, which is what a download is determined
        by, so two slots framed with the same art share one fetch while two
        builds of one character that differ in their art do not.

        Writing each slot's resolved build onto its placement here is what puts
        the build details into every saved project (R9).
        """
        editor = self._editor
        missing: list[str] = []
        selected: dict[tuple[str, str], Build] = {}
        for team_index, row in enumerate(editor.team_fields.combos):
            for slot_index, combo in enumerate(row):
                name = combo.currentText().strip()
                member = editor.project.teams[team_index][slot_index]
                member.name = name
                if member.build and member.build.name.casefold() != name.casefold():
                    member.build = None
                build = resolve_build(editor, member)
                if build is None:
                    missing.append(f"{team_index + 1}-{slot_index + 1}: {name or 'empty'}")
                else:
                    selected[(build.art_url, build.weapon_url)] = build
        if missing:
            raise ValueError("Build not in the loaded profile: " + ", ".join(missing))
        return list(selected.values())
