"""Tests for the per-character build editor popup.

`BuildEditorDialog` builds real widgets, so this module needs the offscreen
platform `tests/gui/conftest.py` sets. No test enters an event loop: the dialog
is constructed and its widgets are driven directly, which is the same surface
the Ok button would have handed to `result_build()`, and the two tests that
cover `ask_custom_build()` replace `exec` with a function returning the code the
user's click would have produced.

The `Catalog` it is fed is built from literal dicts shaped like Enka's data, so
nothing here reads the asset directory or the network.
"""

from collections.abc import Callable
from typing import Any, cast

import pytest
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QWidget

from genshin_thumbnail_studio.enka import Catalog, SkinOption, WeaponOption
from genshin_thumbnail_studio.gui import build_editor
from genshin_thumbnail_studio.models import Build

from .helpers import qapp

ROOT = "https://enka.network"

AYAKA_ART = f"{ROOT}/ui/UI_Gacha_AvatarImg_Ayaka.png"
SPRING_ART = f"{ROOT}/ui/UI_Costume_AyakaCostumeSpring.png"
FRUHLING_ART = f"{ROOT}/ui/UI_Costume_AyakaCostumeFruhling.png"
BOY_ART = f"{ROOT}/ui/UI_Gacha_AvatarImg_PlayerBoy.png"

MISTSPLITTER_URL = f"{ROOT}/ui/UI_EquipIcon_Sword_Narukami_Awaken.png"
DULL_BLADE_URL = f"{ROOT}/ui/UI_EquipIcon_Sword_Blunt.png"

CHARACTERS: dict[str, Any] = {
    "10000002": {
        "NameTextMapHash": 600001,
        "SideIconName": "/ui/UI_AvatarIcon_Side_Ayaka.png",
        "Element": "Ice",
        "WeaponType": "WEAPON_SWORD_ONE_HAND",
        "Costumes": {
            "200302": {"Art": "/ui/UI_Costume_AyakaCostumeFruhling.png"},
            "200301": {"Art": "/ui/UI_Costume_AyakaCostumeSpring.png"},
        },
    },
    # The Traveler: the one character whose entries disagree about their element.
    "10000005-anemo": {
        "NameTextMapHash": 600003,
        "SideIconName": "/ui/UI_AvatarIcon_Side_PlayerBoy.png",
        "Element": "Wind",
        "WeaponType": "WEAPON_SWORD_ONE_HAND",
    },
    "10000005-geo": {
        "NameTextMapHash": 600003,
        "SideIconName": "/ui/UI_AvatarIcon_Side_PlayerBoy.png",
        "Element": "Rock",
        "WeaponType": "WEAPON_SWORD_ONE_HAND",
    },
}

WEAPONS: dict[str, Any] = {
    "11101": {
        "NameTextMapHash": 700001,
        "Rarity": 1,
        "WeaponType": 1,
        "Icon": "/ui/UI_EquipIcon_Sword_Blunt.png",
    },
    "11509": {
        "NameTextMapHash": 700002,
        "Rarity": 5,
        "WeaponType": 1,
        "Icon": "/ui/UI_EquipIcon_Sword_Narukami.png",
        "AwakenIcon": "/ui/UI_EquipIcon_Sword_Narukami_Awaken.png",
    },
    "11501": {
        "NameTextMapHash": 700003,
        "Rarity": 5,
        "WeaponType": 1,
        "Icon": "/ui/UI_EquipIcon_Sword_Falcon.png",
    },
    "12503": {
        "NameTextMapHash": 700004,
        "Rarity": 5,
        "WeaponType": 2,
        "Icon": "/ui/UI_EquipIcon_Claymore_Kunwu.png",
    },
}

NAMES = {
    "600001": "Kamisato Ayaka",
    "600003": "Traveler",
    "700001": "Dull Blade",
    "700002": "Mistsplitter Reforged",
    "700003": "Aquila Favonia",
    "700004": "Wolf's Gravestone",
}

CUSTOM_NAME = "Custom"


def make_catalog() -> Catalog:
    return Catalog(dict(CHARACTERS), dict(WEAPONS), dict(NAMES))


def make_build(
    name: str = "Kamisato Ayaka",
    *,
    costume_id: str | None = "200302",
    art_url: str = FRUHLING_ART,
    element: str | None = "Cryo",
) -> Build:
    return Build(
        name=name,
        constellation=2,
        refinement=3,
        weapon_name="Mistsplitter Reforged",
        costume_id=costume_id,
        art_url=art_url,
        weapon_url=MISTSPLITTER_URL,
        build_name="Live",
        build_id="live-1",
        element=element,
        rarity=5,
        weapon_rarity=5,
    )


def make_dialog(build: Build | None = None) -> build_editor.BuildEditorDialog:
    qapp()
    return build_editor.BuildEditorDialog(build or make_build(), make_catalog(), CUSTOM_NAME)


def combo_items(combo: Any) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def form_labels(dialog: build_editor.BuildEditorDialog) -> list[str]:
    """The rows the form actually holds, which is what "shown" means here."""
    form = cast("QFormLayout", dialog.findChild(QFormLayout))
    labels: list[str] = []
    for row in range(form.rowCount()):
        item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        assert item is not None
        labels.append(cast("QLabel", item.widget()).text())
    return labels


def test_the_dialog_is_titled_after_the_character() -> None:
    assert make_dialog().windowTitle() == "Edit Kamisato Ayaka"


def test_skin_combo_lists_the_catalog_s_skins_with_the_build_s_own_selected() -> None:
    dialog = make_dialog()

    assert combo_items(dialog.skin_combo) == ["Default", "Spring", "Fruhling"]
    assert dialog.skin_combo.currentData() == SkinOption("Fruhling", "200302", FRUHLING_ART)


def test_skin_combo_selects_the_default_art_for_an_unskinned_build() -> None:
    dialog = make_dialog(make_build(costume_id=None, art_url=AYAKA_ART))

    assert dialog.skin_combo.currentData() == SkinOption("Default", None, AYAKA_ART)


def test_weapon_combo_lists_the_catalog_s_weapons_with_the_build_s_own_selected() -> None:
    dialog = make_dialog()

    assert combo_items(dialog.weapon_combo) == [
        "Aquila Favonia",
        "Mistsplitter Reforged",
        "Dull Blade",
    ]
    assert dialog.weapon_combo.currentData() == WeaponOption("Mistsplitter Reforged", MISTSPLITTER_URL, 5)


def test_the_spin_boxes_are_seeded_from_the_build_and_bounded() -> None:
    dialog = make_dialog()

    assert (dialog.constellation_spin.value(), dialog.refinement_spin.value()) == (2, 3)
    assert (dialog.constellation_spin.minimum(), dialog.constellation_spin.maximum()) == (0, 6)
    assert (dialog.refinement_spin.minimum(), dialog.refinement_spin.maximum()) == (1, 5)


def test_a_normal_character_gets_no_element_row_at_all() -> None:
    """Not a disabled control: a dead widget still asks to be read, and still
    implies the value could have been something else."""
    dialog = make_dialog()

    assert dialog.element_combo is None
    assert form_labels(dialog) == ["Skin", "Weapon", "Constellation", "Refinement"]


def test_the_traveler_gets_an_element_row() -> None:
    dialog = make_dialog(make_build(name="Traveler", costume_id=None, art_url=BOY_ART, element=None))

    assert dialog.element_combo is not None
    assert combo_items(dialog.element_combo) == list(build_editor.ELEMENT_CHOICES)
    assert dialog.element_combo.currentText() == "None"
    assert form_labels(dialog) == ["Skin", "Weapon", "Constellation", "Refinement", "Element"]


def test_result_build_carries_every_edited_field() -> None:
    build = make_build()
    dialog = make_dialog(build)

    dialog.skin_combo.setCurrentIndex(1)
    dialog.weapon_combo.setCurrentIndex(2)
    dialog.constellation_spin.setValue(6)
    dialog.refinement_spin.setValue(5)

    result = dialog.result_build()

    assert (result.costume_id, result.art_url) == ("200301", SPRING_ART)
    assert (result.weapon_name, result.weapon_url, result.weapon_rarity) == ("Dull Blade", DULL_BLADE_URL, 1)
    assert (result.constellation, result.refinement) == (6, 5)
    assert (result.build_name, result.build_id) == (CUSTOM_NAME, "")
    # Untouched: the popup edits neither who the character is nor their rarity.
    assert (result.name, result.rarity, result.element) == ("Kamisato Ayaka", 5, "Cryo")
    assert build.build_name == "Live", "the source build must not be mutated"


def test_result_build_takes_the_chosen_element_only_where_it_is_editable() -> None:
    dialog = make_dialog(make_build(name="Traveler", costume_id=None, art_url=BOY_ART, element=None))
    assert dialog.element_combo is not None

    dialog.element_combo.setCurrentIndex(list(build_editor.ELEMENT_CHOICES).index("Geo"))

    assert dialog.result_build().element == "Geo"


def test_result_build_maps_the_none_element_to_no_element() -> None:
    dialog = make_dialog(make_build(name="Traveler", costume_id=None, art_url=BOY_ART, element="Anemo"))
    assert dialog.element_combo is not None

    dialog.element_combo.setCurrentIndex(0)

    assert dialog.result_build().element is None


def test_result_build_keeps_an_unlisted_weapon_and_skin_selectable() -> None:
    """A build the catalog does not know about can still be edited losslessly."""
    build = make_build(costume_id="209999", art_url=f"{ROOT}/ui/UI_Costume_AyakaCostumeUnknown.png")
    dialog = make_dialog(build)

    result = dialog.result_build()

    assert (result.costume_id, result.art_url) == ("209999", build.art_url)
    assert (result.weapon_name, result.weapon_url) == ("Mistsplitter Reforged", MISTSPLITTER_URL)
    assert result.build_name == CUSTOM_NAME


def test_the_unchanged_dialog_reproduces_the_build_it_was_seeded_with() -> None:
    build = make_build()

    result = make_dialog(build).result_build()

    assert result.details() == build.details()
    assert (result.art_url, result.weapon_url) == (build.art_url, build.weapon_url)
    assert (result.build_name, result.build_id) == (CUSTOM_NAME, "")


def button_box(dialog: build_editor.BuildEditorDialog) -> QDialogButtonBox:
    box = dialog.findChild(QDialogButtonBox)
    assert isinstance(box, QDialogButtonBox), "the dialog has no button box"
    return box


def test_the_button_box_accepts_and_rejects_the_dialog() -> None:
    """Ok and Cancel have to reach `accept`/`reject`, or the popup cannot close."""
    accepted = make_dialog()
    button_box(accepted).accepted.emit()

    rejected = make_dialog()
    button_box(rejected).rejected.emit()

    assert accepted.result() == QDialog.DialogCode.Accepted
    assert rejected.result() == QDialog.DialogCode.Rejected


def stub_exec(code: QDialog.DialogCode, edit: bool = False) -> Callable[[build_editor.BuildEditorDialog], int]:
    """Stand in for the user's click, without ever entering an event loop."""

    def fake_exec(dialog: build_editor.BuildEditorDialog) -> int:
        if edit:
            dialog.constellation_spin.setValue(6)
        return int(code)

    return fake_exec


def test_ask_custom_build_returns_the_edited_build_when_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    qapp()
    parent = QWidget()
    monkeypatch.setattr(
        build_editor.BuildEditorDialog, "exec", stub_exec(QDialog.DialogCode.Accepted, edit=True)
    )

    answer = build_editor.ask_custom_build(parent, make_build(), make_catalog(), CUSTOM_NAME)

    assert answer is not None
    assert (answer.constellation, answer.build_name, answer.build_id) == (6, CUSTOM_NAME, "")


def test_ask_custom_build_returns_nothing_when_cancelled(monkeypatch: pytest.MonkeyPatch) -> None:
    qapp()
    parent = QWidget()
    monkeypatch.setattr(build_editor.BuildEditorDialog, "exec", stub_exec(QDialog.DialogCode.Rejected))

    assert build_editor.ask_custom_build(parent, make_build(), make_catalog(), CUSTOM_NAME) is None
