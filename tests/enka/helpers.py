"""Stubs shared by more than one of the enka test modules.

The stubs satisfy the Protocols in `enka/parsing.py` structurally, which is what
lets the parsing tests run without the third-party library and without fixtures.
"""

from dataclasses import dataclass, field
from typing import Any

from genshin_thumbnail_studio.models import Build


@dataclass
class StubElement:
    name: str


@dataclass
class StubIcon:
    gacha: str


@dataclass
class StubCostume:
    data: dict[str, Any]


@dataclass
class StubConstellation:
    unlocked: bool


@dataclass
class StubWeapon:
    name: str = "Test Weapon"
    refinement: int = 3
    rarity: int = 5
    icon: str = "https://enka.network/ui/UI_EquipIcon_Test.png"


@dataclass
class StubCharacter:
    name: str = "Bennett"
    constellations: list[StubConstellation] = field(default_factory=list)
    costume_id: int | None = None
    costume: StubCostume | None = None
    element: StubElement | None = None
    rarity: int = 4
    icon: StubIcon = field(default_factory=lambda: StubIcon("https://enka.network/ui/UI_Gacha_AvatarImg_Bennett.png"))
    weapon: StubWeapon = field(default_factory=StubWeapon)


@dataclass
class StubSavedBuild:
    """A saved build as `fetch_builds()` returns it."""

    id: int
    name: str
    order: str
    live: bool
    character: StubCharacter
    character_id: int = 10000032


def constellations(unlocked: int) -> list[StubConstellation]:
    """The always-six-entry constellation list, with `unlocked` of them unlocked."""
    return [StubConstellation(unlocked=index < unlocked) for index in range(6)]


def make_build(name: str, build_name: str = "Live") -> Build:
    return Build(
        name=name,
        constellation=0,
        refinement=1,
        weapon_name="Weapon",
        costume_id=None,
        art_url=f"https://example.invalid/{name}-art.png",
        weapon_url=f"https://example.invalid/{name}-weapon.png",
        build_name=build_name,
    )
