"""Tests for the per-character build dropdown on each team slot.

`TeamFieldsController` builds real widgets, so this module needs the offscreen
platform `tests/gui/conftest.py` sets. A `StubEditor` stands in for `MainWindow`
so these tests do not depend on the window's own wiring.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from PySide6.QtWidgets import QVBoxLayout, QWidget

from genshin_thumbnail_studio.gui.history import HistoryController
from genshin_thumbnail_studio.gui.team_fields import TeamFieldsController
from genshin_thumbnail_studio.models import LIVE_BUILD_NAME, Asset, Build, Project

from .helpers import qapp


def make_build(name: str, build_name: str = LIVE_BUILD_NAME) -> Build:
    return Build(
        name=name,
        constellation=1,
        refinement=2,
        weapon_name="Splendor of Tranquil Waters",
        costume_id=None,
        build_name=build_name,
        build_id=f"{name}-{build_name}",
        art_url=f"https://enka.network/ui/{name}.png",
        weapon_url="https://enka.network/ui/weapon.png",
    )


@dataclass
class StubEditor:
    """The minimal `TeamFieldsEditor` the controller needs."""

    project: Project
    builds: dict[str, list[Build]] = field(default_factory=dict)
    assets: dict[str, Asset] = field(default_factory=dict)
    selected: tuple[int, int] = (0, 0)
    build_selected_calls: list[tuple[int, int, Build]] = field(default_factory=list)

    def member_changed(self, team: int, slot: int, name: str) -> None:
        self.project.teams[team][slot].name = name.strip()

    def sync_controls(self) -> None:
        pass

    def schedule_render(self) -> None:
        pass

    def build_selected(self, team: int, slot: int, build: Build) -> None:
        self.build_selected_calls.append((team, slot, build))
        self.project.teams[team][slot].build = build


@dataclass
class Host:
    controller: TeamFieldsController
    editor: StubEditor
    parent: QWidget


@pytest.fixture
def host() -> Iterator[Host]:
    qapp()
    project = Project.blank("abyss")
    project.teams[0][0].name = "Furina"
    project.teams[0][1].name = "Unknown"
    editor = StubEditor(project=project)
    live = make_build("Furina")
    saved_one = make_build("Furina", "Bow DPS")
    saved_two = make_build("Furina", "Sword DPS")
    editor.builds["furina"] = [live, saved_one, saved_two]

    parent = QWidget()
    team_layout = QVBoxLayout()
    history = HistoryController(editor, parent, lambda: None)
    controller = TeamFieldsController(editor, team_layout, history, parent)
    controller.rebuild()

    yield Host(controller=controller, editor=editor, parent=parent)
    parent.deleteLater()
    qapp().processEvents()


def test_the_menu_lists_the_live_and_saved_builds_with_the_live_one_checked(host: Host) -> None:
    """R5, R6, R8: the profile's live build plus its saved builds, live checked."""
    menu = host.controller.build_menu(0, 0)
    actions = menu.actions()

    assert [action.text() for action in actions] == [LIVE_BUILD_NAME, "Bow DPS", "Sword DPS"]
    assert [action.isChecked() for action in actions] == [True, False, False]


def test_triggering_a_build_action_leaves_that_build_on_the_placement(host: Host) -> None:
    menu = host.controller.build_menu(0, 0)
    saved_action = menu.actions()[1]

    saved_action.trigger()

    member = host.editor.project.teams[0][0]
    assert member.build is not None
    assert member.build.build_name == "Bow DPS"
    assert host.editor.build_selected_calls == [(0, 0, member.build)]


def test_a_slot_whose_character_is_not_in_the_profile_has_its_button_disabled(host: Host) -> None:
    slot_widget = host.controller.slot_widgets[0][1]

    assert slot_widget.build_button.isEnabled() is False


def test_typing_a_character_enables_its_build_button(host: Host) -> None:
    """R5: the arrow follows the slot's character, not just the profile load.

    A slot filled in after the profile arrived would otherwise keep the
    disabled arrow it was built with, leaving its build list unreachable.
    """
    slot_widget = host.controller.slot_widgets[0][2]
    assert slot_widget.build_button.isEnabled() is False

    host.controller.combos[0][2].setCurrentText("Furina")

    assert slot_widget.build_button.isEnabled() is True


def test_the_menus_actions_share_one_exclusive_action_group(host: Host) -> None:
    """R6: Qt draws an action's menu entry as a radio button, not a check box,
    exactly when its action group is exclusive."""
    menu = host.controller.build_menu(0, 0)
    actions = menu.actions()

    groups = {action.actionGroup() for action in actions}
    assert len(groups) == 1
    group = groups.pop()
    assert group is not None
    assert group.isExclusive() is True
    assert sum(action.isChecked() for action in actions) == 1


def test_reordering_slots_moves_the_build_buttons_with_them(host: Host) -> None:
    """The names move between slots with their signals blocked, so the arrows
    have to be refreshed by hand or they stay with the old positions."""
    buttons = [widget.build_button for widget in host.controller.slot_widgets[0]]
    assert [button.isEnabled() for button in buttons] == [True, False, False, False]

    host.controller.reorder((0, 0), (0, 3))

    assert [member.name for member in host.editor.project.teams[0]] == ["Unknown", "", "", "Furina"]
    assert [button.isEnabled() for button in buttons] == [False, False, False, True]
