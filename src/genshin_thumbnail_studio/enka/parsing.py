"""Turning the enka library's models into this app's `Build`.

The library is deliberately not imported here. Every model this module reads is
described by a Protocol covering exactly the attributes it touches, which the
library's pydantic models satisfy structurally. That keeps the module testable
against plain stubs, and makes the Protocols the written-down record of which
part of the library's surface this app depends on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Protocol

from ..models import Build

ENKA_ROOT = "https://enka.network"

# A weapon whose name did not resolve against the current asset data comes back
# as its bare text-map hash, which is of no use to a viewer.
UNKNOWN_WEAPON_NAME = "Unknown weapon"


class ElementLike(Protocol):
    @property
    def name(self) -> str: ...


class IconLike(Protocol):
    @property
    def gacha(self) -> str: ...


class ConstellationLike(Protocol):
    @property
    def unlocked(self) -> bool: ...


class CostumeLike(Protocol):
    @property
    def data(self) -> Mapping[str, Any]: ...


class WeaponLike(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def refinement(self) -> int: ...
    @property
    def rarity(self) -> int: ...
    @property
    def icon(self) -> str: ...


class CharacterLike(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def constellations(self) -> Sequence[ConstellationLike]: ...
    @property
    def costume_id(self) -> int | None: ...
    @property
    def costume(self) -> CostumeLike | None: ...
    @property
    def element(self) -> ElementLike | None: ...
    @property
    def rarity(self) -> int: ...
    @property
    def icon(self) -> IconLike: ...
    @property
    def weapon(self) -> WeaponLike: ...


class SavedBuildLike(Protocol):
    """One entry of what `fetch_builds()` returns."""

    @property
    def id(self) -> int: ...
    @property
    def name(self) -> str: ...
    @property
    def order(self) -> Decimal | str: ...
    @property
    def live(self) -> bool: ...
    @property
    def character(self) -> CharacterLike: ...


def element_name(element: ElementLike | None) -> str | None:
    """The element in the capitalized form `renderer.colors.ELEMENT_COLORS` keys by.

    The library's enum names the seven real elements `ANEMO`, `GEO` and so on,
    and uses `NONE` for a character without one (the Traveler before a resonance).
    """
    if element is None or not element.name or element.name.casefold() == "none":
        return None
    return element.name.capitalize()


def art_url(character: CharacterLike) -> str:
    """The full-size character art, honouring an equipped costume.

    `icon.gacha` is the *default* gacha art and ignores the costume entirely, so
    a skinned character has to be read off `costume.data["Art"]` instead. Never
    read `costume.icon`: it is a computed property over `data["sideIconName"]`,
    a key the current asset data does not carry, so touching it raises
    `KeyError`.
    """
    costume = character.costume
    art = costume.data.get("Art") if costume is not None else None
    if isinstance(art, str) and art:
        return f"{ENKA_ROOT}{art}"
    return character.icon.gacha


def weapon_display_name(weapon: WeaponLike) -> str:
    name = weapon.name.strip()
    if not name or name.isdigit():
        return UNKNOWN_WEAPON_NAME
    return name


def constellation_level(character: CharacterLike) -> int:
    """The number of unlocked constellations; the list always holds six."""
    return sum(1 for constellation in character.constellations if constellation.unlocked)


def build_from_character(character: CharacterLike, *, build_name: str, build_id: str = "") -> Build:
    weapon = character.weapon
    return Build(
        name=character.name,
        constellation=constellation_level(character),
        refinement=weapon.refinement,
        weapon_name=weapon_display_name(weapon),
        costume_id=str(character.costume_id) if character.costume_id else None,
        art_url=art_url(character),
        weapon_url=weapon.icon,
        build_name=build_name,
        build_id=build_id,
        element=element_name(character.element),
        rarity=character.rarity,
        weapon_rarity=weapon.rarity,
    )
