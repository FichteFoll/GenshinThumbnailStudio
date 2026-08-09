"""Tests for the per-character build dropdown on each team slot.

`TeamFieldsController` builds real widgets, so this module needs the offscreen
platform `tests/gui/conftest.py` sets. A `StubEditor` stands in for `MainWindow`
so these tests do not depend on the window's own wiring; the two tests that
assert what a custom build does to the *model* drive the real window instead,
because the write they check is the window's.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QVBoxLayout, QWidget

from genshin_thumbnail_studio.enka import Catalog
from genshin_thumbnail_studio.gui import MainWindow, asset_loader, main_window, team_fields, team_slots
from genshin_thumbnail_studio.gui.history import HistoryController
from genshin_thumbnail_studio.gui.team_fields import TeamFieldsController
from genshin_thumbnail_studio.models import CUSTOM_BUILD_NAME, LIVE_BUILD_NAME, Build, Project

from .helpers import close_ignoring_unsaved_changes, qapp


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
    art_root: Path = Path("assets")
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

    def catalog(self) -> Catalog:
        # Empty on purpose: what the popup does with it is `test_build_editor`'s
        # subject, and these tests replace the popup anyway.
        return Catalog({}, {}, {})


def build_actions(menu: QMenu) -> list[QAction]:
    """The menu's build entries, without the separator and the edit item."""
    return [action for action in menu.actions() if action.isCheckable()]


def edit_action(menu: QMenu) -> QAction:
    return menu.actions()[-1]


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
    actions = build_actions(menu)

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
    actions = build_actions(menu)

    groups = {action.actionGroup() for action in actions}
    assert len(groups) == 1
    group = groups.pop()
    assert group is not None
    assert group.isExclusive() is True
    assert sum(action.isChecked() for action in actions) == 1


def test_the_build_button_captions_the_selected_build(host: Host) -> None:
    """R5: the button beside the combo names the build the slot is framed with."""
    assert host.controller.slot_widgets[0][0].build_button.text() == LIVE_BUILD_NAME
    assert host.controller.slot_widgets[0][1].build_button.text() == ""


def test_every_build_button_has_the_same_width(host: Host) -> None:
    """R5: every button is pinned to one width, captioned or not, so that the
    combos beside them end at one edge instead of raggedly following captions."""
    widths = {
        widget.build_button.width() for row in host.controller.slot_widgets for widget in row
    }

    assert widths == {team_slots.BUILD_BUTTON_WIDTH}


def test_selecting_a_build_updates_the_button_caption(host: Host) -> None:
    """R5: the caption follows a fresh selection, which the editor's own
    `sync_controls()` does not refresh."""
    menu = host.controller.build_menu(0, 0)

    menu.actions()[1].trigger()

    assert host.controller.slot_widgets[0][0].build_button.text() == "Bow DPS"


def test_reordering_slots_moves_the_build_buttons_with_them(host: Host) -> None:
    """The names move between slots with their signals blocked, so the arrows
    have to be refreshed by hand or they stay with the old positions."""
    buttons = [widget.build_button for widget in host.controller.slot_widgets[0]]
    assert [button.isEnabled() for button in buttons] == [True, False, False, False]

    host.controller.reorder((0, 0), (0, 3))

    assert [member.name for member in host.editor.project.teams[0]] == ["Unknown", "", "", "Furina"]
    assert [button.isEnabled() for button in buttons] == [False, False, False, True]


def test_the_menu_ends_in_a_separator_and_an_edit_item(host: Host) -> None:
    """R1: the way into the build editor sits below the build entries.

    It is outside the exclusive group and not checkable, because it is a command
    and not one more build the slot could be framed with.
    """
    menu = host.controller.build_menu(0, 0)
    actions = menu.actions()

    assert actions[-2].isSeparator() is True
    assert actions[-1].text() == team_fields.EDIT_ACTION_TEXT
    assert actions[-1].isCheckable() is False
    assert actions[-1].actionGroup() is None


def test_a_slot_without_builds_offers_no_menu_entries_at_all(host: Host) -> None:
    """The popup seeds itself from a build, so a slot with none cannot open it."""
    menu = host.controller.build_menu(0, 1)

    assert menu.actions() == []


def test_the_edit_item_seeds_the_popup_with_the_selected_build_and_adopts_its_answer(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6: the popup's answer becomes the slot's custom build and its selection,
    while the build it was based on stays in the menu."""
    seeded: list[Build] = []

    def fake_ask(parent: QWidget, build: Build, catalog: Catalog, custom_name: str) -> Build:
        seeded.append(build)
        return replace(build, build_name=custom_name, build_id="")

    monkeypatch.setattr(team_fields, "ask_custom_build", fake_ask)
    build_menu = host.controller.build_menu(0, 0)
    build_menu.actions()[1].trigger()  # Frame the slot with "Bow DPS" first.

    edit_menu = host.controller.build_menu(0, 0)
    edit_action(edit_menu).trigger()

    assert [build.build_name for build in seeded] == ["Bow DPS"]
    member = host.editor.project.teams[0][0]
    assert member.build is not None
    assert member.build.build_name == CUSTOM_BUILD_NAME
    assert host.editor.build_selected_calls[-1] == (0, 0, member.build)
    refreshed = host.controller.build_menu(0, 0)
    labels = [action.text() for action in build_actions(refreshed)]
    assert labels == [LIVE_BUILD_NAME, "Bow DPS", "Sword DPS", CUSTOM_BUILD_NAME]
    assert host.controller.slot_widgets[0][0].build_button.text() == CUSTOM_BUILD_NAME


def test_cancelling_the_popup_leaves_the_slot_exactly_as_it_was(
    host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled edit writes nothing, so the slot keeps its framing.

    Without the guard the `None` would be selected as the slot's build,
    un-framing a slot the user only looked at.
    """

    def cancelled(parent: QWidget, build: Build, catalog: Catalog, custom_name: str) -> Build | None:
        return None

    monkeypatch.setattr(team_fields, "ask_custom_build", cancelled)
    build_menu = host.controller.build_menu(0, 0)
    build_menu.actions()[1].trigger()  # Frame the slot with "Bow DPS" first.
    member = host.editor.project.teams[0][0]
    framed = member.build

    edit_menu = host.controller.build_menu(0, 0)
    edit_action(edit_menu).trigger()

    assert member.build is framed
    assert host.editor.build_selected_calls[-1] == (0, 0, framed)
    assert host.controller.slot_widgets[0][0].build_button.text() == "Bow DPS"


def custom_answer(weapon_name: str) -> Callable[[QWidget, Build, Catalog, str], Build]:
    """A stand-in popup that always accepts, changing the weapon and the skin.

    Both URLs move, because both halves of what a slot draws are derived from
    the build: an answer that changed only the weapon would leave the character
    art of two edited slots at one path and say nothing about it.
    """

    def answer(parent: QWidget, build: Build, catalog: Catalog, custom_name: str) -> Build:
        return replace(
            build,
            build_name=custom_name,
            build_id="",
            weapon_name=weapon_name,
            weapon_url=f"https://enka.network/ui/{weapon_name}.png",
            art_url=f"https://enka.network/ui/{weapon_name}-art.png",
        )

    return answer


def no_downloads(builds: list[Build], root: Path, **kwargs: object) -> None:
    """The art of a custom build is never fetched in a test."""


def empty_catalog(asset_root: Path) -> Catalog:
    """`load_catalog()` without its two data files and its download."""
    return Catalog({}, {}, {})


def window_with_two_slots_of_one_character(monkeypatch: pytest.MonkeyPatch) -> MainWindow:
    """A real window whose first two slots both hold Furina, both framed live.

    The tests below it are about what the window writes onto the placements, so
    the stub editor above cannot stand in for it.
    """
    monkeypatch.setattr(asset_loader, "download_assets", no_downloads)
    monkeypatch.setattr(main_window, "load_catalog", empty_catalog)
    window = MainWindow()
    window.builds["furina"] = [make_build("Furina")]
    for slot_index in (0, 1):
        member = window.project.teams[0][slot_index]
        member.name = "Furina"
        member.build = make_build("Furina")
    window.rebuild_team_fields()
    return window


def test_editing_twice_leaves_the_slot_with_one_custom_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R8: the second edit replaces the first custom rather than adding to it."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = window_with_two_slots_of_one_character(monkeypatch)

    monkeypatch.setattr(team_fields, "ask_custom_build", custom_answer("Splendor"))
    first_menu = window.team_fields.build_menu(0, 0)
    edit_action(first_menu).trigger()
    monkeypatch.setattr(team_fields, "ask_custom_build", custom_answer("Fontaine"))
    second_menu = window.team_fields.build_menu(0, 0)
    edit_action(second_menu).trigger()

    member = window.project.teams[0][0]
    assert member.build is not None
    assert member.build.weapon_name == "Fontaine"
    refreshed = window.team_fields.build_menu(0, 0)
    labels = [action.text() for action in build_actions(refreshed)]
    assert labels.count(CUSTOM_BUILD_NAME) == 1

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_retyping_a_slots_character_drops_its_custom_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A custom build is the slot's snapshot, so the stale-snapshot rule that
    already drops a profile build on a retype drops this one too: no slot can be
    offered the build of the character that used to be in it."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = window_with_two_slots_of_one_character(monkeypatch)
    window.builds["nahida"] = [make_build("Nahida")]
    monkeypatch.setattr(team_fields, "ask_custom_build", custom_answer("Splendor"))
    edit_menu = window.team_fields.build_menu(0, 0)
    edit_action(edit_menu).trigger()

    window.member_changed(0, 0, "Nahida")

    member = window.project.teams[0][0]
    assert member.build is not None
    assert member.build.name == "Nahida"
    refreshed = window.team_fields.build_menu(0, 0)
    assert [action.text() for action in build_actions(refreshed)] == [LIVE_BUILD_NAME]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_retyping_the_same_character_keeps_its_custom_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a changed character drops the custom: re-entering the same name,
    however it is spelled, leaves the slot framed with what the popup made."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = window_with_two_slots_of_one_character(monkeypatch)
    monkeypatch.setattr(team_fields, "ask_custom_build", custom_answer("Splendor"))
    edit_menu = window.team_fields.build_menu(0, 0)
    edit_action(edit_menu).trigger()

    window.member_changed(0, 0, "furina")

    member = window.project.teams[0][0]
    assert member.build is not None
    assert member.build.weapon_name == "Splendor"
    refreshed = window.team_fields.build_menu(0, 0)
    labels = [action.text() for action in build_actions(refreshed)]
    assert labels == [LIVE_BUILD_NAME, CUSTOM_BUILD_NAME]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_two_slots_of_one_character_carry_their_own_custom_art(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7: a custom build belongs to its slot, so neither slot can draw the
    other's art or weapon icon."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = window_with_two_slots_of_one_character(monkeypatch)

    monkeypatch.setattr(team_fields, "ask_custom_build", custom_answer("Splendor"))
    first_menu = window.team_fields.build_menu(0, 0)
    edit_action(first_menu).trigger()
    monkeypatch.setattr(team_fields, "ask_custom_build", custom_answer("Fontaine"))
    second_menu = window.team_fields.build_menu(0, 1)
    edit_action(second_menu).trigger()

    first, second = (window.project.teams[0][slot_index].build for slot_index in (0, 1))
    assert first is not None and second is not None
    root = window.art_root
    assert (first.art_path(root), first.weapon_path(root)) != (second.art_path(root), second.weapon_path(root))
    # Both halves, not just the pair: each is derived from the build alone, and
    # a path that went by the slot's character name instead would collide here.
    assert first.art_path(root) != second.art_path(root)
    assert first.weapon_path(root) != second.weapon_path(root)

    close_ignoring_unsaved_changes(window, app, monkeypatch)
