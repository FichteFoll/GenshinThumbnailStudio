"""The popup that edits one slot's build: skin, weapon, constellation, refinement.

The profile only offers the builds the player happens to have saved on Enka, so
this dialog lets a slot carry any of them: its choices come from the `Catalog`,
not from the profile, and accepting it yields a new `Build` rather than mutating
the one it was seeded with, which is what keeps the build it was based on
available beside it.

Nothing here imports `MainWindow`, so the window and its controllers can open
the popup without a cycle; like the free functions in `dialogs`, it reports the
user's answer and leaves acting on it to the caller.
"""

from __future__ import annotations

from dataclasses import replace
from typing import cast

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..enka import Catalog, SkinOption, WeaponOption
from ..models import Build

# The seven elements plus the absence of one, which is what a build carries
# before the profile has pinned it down; `renderer.colors` keys the badge colors
# by these names.
ELEMENT_CHOICES = ("None", "Anemo", "Cryo", "Dendro", "Electro", "Geo", "Hydro", "Pyro")

_NO_ELEMENT = ELEMENT_CHOICES[0]


class BuildEditorDialog(QDialog):
    """Edit the details of `build` against the choices `catalog` offers.

    Every combo carries its option object as item data, so `result_build()` reads
    the choice back rather than parsing a label; the labels are display text and
    nothing is keyed by them.
    """

    def __init__(self, build: Build, catalog: Catalog, custom_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build = build
        self._custom_name = custom_name
        self.setWindowTitle(f"Edit {build.name}")

        form = QFormLayout()
        self.skin_combo = self._skin_combo(build, catalog)
        form.addRow("Skin", self.skin_combo)
        self.weapon_combo = self._weapon_combo(build, catalog)
        form.addRow("Weapon", self.weapon_combo)
        self.constellation_spin = _spin_box(0, 6, build.constellation)
        form.addRow("Constellation", self.constellation_spin)
        self.refinement_spin = _spin_box(1, 5, build.refinement)
        form.addRow("Refinement", self.refinement_spin)
        # The element is the user's to pick only for the Traveler, so for
        # everyone else the row is absent rather than present-but-dead: a
        # disabled control still asks to be read and still implies the value
        # could be something else.
        self.element_combo = self._element_combo(build) if catalog.element_is_variable(build) else None
        if self.element_combo is not None:
            form.addRow("Element", self.element_combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _skin_combo(build: Build, catalog: Catalog) -> QComboBox:
        combo = QComboBox()
        for index, option in enumerate(catalog.skins(build)):
            combo.addItem(option.label, option)
            if option.costume_id == build.costume_id:
                combo.setCurrentIndex(index)
        return combo

    @staticmethod
    def _weapon_combo(build: Build, catalog: Catalog) -> QComboBox:
        combo = QComboBox()
        for index, option in enumerate(catalog.weapons_for(build)):
            combo.addItem(option.name, option)
            if option.name == build.weapon_name:
                combo.setCurrentIndex(index)
        return combo

    @staticmethod
    def _element_combo(build: Build) -> QComboBox:
        """The element picker, built only where the source data cannot decide.

        That is the Traveler and only the Traveler, whose element the game
        decides by resonance; everyone else's is a fixed fact of the data and
        gets no control at all.
        """
        combo = QComboBox()
        combo.addItems(ELEMENT_CHOICES)
        current = build.element or _NO_ELEMENT
        if current in ELEMENT_CHOICES:
            combo.setCurrentIndex(ELEMENT_CHOICES.index(current))
        return combo

    def _chosen_element(self) -> str | None:
        if self.element_combo is None:
            return self._build.element
        element = self.element_combo.currentText()
        return None if element == _NO_ELEMENT else element

    def result_build(self) -> Build:
        """A new `Build` carrying the edits, leaving the seeded one untouched.

        It is named `custom_name` and carries no `build_id`: it is this slot's
        own build, not one of the profile's, and nothing on Enka answers for it.
        """
        skin = cast("SkinOption", self.skin_combo.currentData())
        weapon = cast("WeaponOption", self.weapon_combo.currentData())
        return replace(
            self._build,
            costume_id=skin.costume_id,
            art_url=skin.art_url,
            weapon_name=weapon.name,
            weapon_url=weapon.weapon_url,
            weapon_rarity=weapon.rarity,
            constellation=self.constellation_spin.value(),
            refinement=self.refinement_spin.value(),
            element=self._chosen_element(),
            build_name=self._custom_name,
            build_id="",
        )


def _spin_box(minimum: int, maximum: int, value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


def ask_custom_build(parent: QWidget, build: Build, catalog: Catalog, custom_name: str) -> Build | None:
    """Run the editor over `build`, or return None when it was cancelled."""
    dialog = BuildEditorDialog(build, catalog, custom_name, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.result_build()
