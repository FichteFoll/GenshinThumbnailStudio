"""Tests for `enka.parsing`, against stubs rather than live library models."""

from genshin_thumbnail_studio.enka import parsing

from .helpers import StubCharacter, StubCostume, StubElement, StubIcon, StubWeapon, constellations


def test_art_url_uses_the_gacha_art_without_a_costume() -> None:
    character = StubCharacter(icon=StubIcon("https://enka.network/ui/UI_Gacha_AvatarImg_Bennett.png"))

    assert parsing.art_url(character) == "https://enka.network/ui/UI_Gacha_AvatarImg_Bennett.png"


def test_art_url_uses_the_costume_art_when_one_is_equipped() -> None:
    character = StubCharacter(
        costume_id=203201,
        costume=StubCostume(data={"Art": "/ui/UI_Costume_BennettCostumeSummer.png"}),
        icon=StubIcon("https://enka.network/ui/UI_Gacha_AvatarImg_Bennett.png"),
    )

    result = parsing.art_url(character)

    assert result == "https://enka.network/ui/UI_Costume_BennettCostumeSummer.png"
    # `icon.gacha` ignores the equipped costume, so it must not be what is used.
    assert result != character.icon.gacha


def test_art_url_falls_back_to_the_gacha_art_for_a_costume_without_art() -> None:
    character = StubCharacter(costume_id=203201, costume=StubCostume(data={"Icon": "UI_AvatarIcon_Bennett"}))

    assert parsing.art_url(character) == character.icon.gacha


def test_element_name_capitalizes_the_enum_name() -> None:
    assert parsing.element_name(StubElement(name="PYRO")) == "Pyro"


def test_element_name_is_none_for_no_element() -> None:
    assert parsing.element_name(StubElement(name="NONE")) is None
    assert parsing.element_name(None) is None


def test_constellation_level_counts_the_unlocked_entries() -> None:
    character = StubCharacter(constellations=constellations(2))

    assert len(character.constellations) == 6
    assert parsing.constellation_level(character) == 2


def test_weapon_display_name_keeps_a_real_name() -> None:
    assert parsing.weapon_display_name(StubWeapon(name="Aqua Simulacra")) == "Aqua Simulacra"


def test_weapon_display_name_rejects_an_unresolved_text_map_hash() -> None:
    assert parsing.weapon_display_name(StubWeapon(name="2918525947")) == "Unknown weapon"
    assert parsing.weapon_display_name(StubWeapon(name="")) == "Unknown weapon"


def test_build_from_character_fills_the_live_build() -> None:
    character = StubCharacter(
        name="Bennett",
        constellations=constellations(6),
        costume_id=203201,
        costume=StubCostume(data={"Art": "/ui/UI_Costume_BennettCostumeSummer.png"}),
        element=StubElement(name="PYRO"),
        rarity=4,
        weapon=StubWeapon(name="Aqua Simulacra", refinement=5, rarity=5),
    )

    build = parsing.build_from_character(character, build_name="Live")

    assert build.name == "Bennett"
    assert build.build_name == "Live"
    assert build.build_id == ""
    assert build.constellation == 6
    assert build.refinement == 5
    assert build.weapon_name == "Aqua Simulacra"
    assert build.costume_id == "203201"
    assert build.element == "Pyro"
    assert build.rarity == 4
    assert build.weapon_rarity == 5
    assert build.art_url == "https://enka.network/ui/UI_Costume_BennettCostumeSummer.png"
    assert build.weapon_url == "https://enka.network/ui/UI_EquipIcon_Test.png"
    assert build.key == "bennett|live"


def test_build_from_character_carries_a_saved_build_name_and_id() -> None:
    character = StubCharacter(name="Amber", constellations=constellations(0))

    build = parsing.build_from_character(character, build_name="Bow DPS", build_id="42")

    assert build.costume_id is None
    assert build.build_id == "42"
    assert build.key == "amber|bow dps"
