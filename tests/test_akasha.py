import os
import time
import urllib.error
from pathlib import Path

from genshin_thumbnail_studio.akasha import (
    character_element,
    character_rarity,
    exact_art_url,
    load_enka_rarities,
    parse_builds,
    refinement,
    weapon_rarity,
)


def raw_build(name: str, icon: str, costume_id=None, element=None, character_id=None, weapon_id=None) -> dict:
    build = {
        "_id": "build-id",
        "md5": "build-md5",
        "name": name,
        "icon": icon,
        "costumeId": costume_id,
        "constellation": 2,
        "lastBuildUpdate": 123,
        "weapon": {
            "name": "Test Weapon",
            "icon": "https://enka.network/ui/UI_EquipIcon_Test.png",
            "weaponInfo": {"refinementLevel": {"value": 3}},
        },
    }
    if element is not None:
        build["characterMetadata"] = {"element": element}
    if character_id is not None:
        build["characterId"] = character_id
    if weapon_id is not None:
        build["weapon"]["weaponId"] = weapon_id
    return build


def test_art_url_uses_akasha_asset_stem_not_character_name() -> None:
    build = raw_build("Localized Name", "https://enka.network/ui/UI_AvatarIcon_InternalAsset.png")
    assert exact_art_url(build) == "https://enka.network/ui/UI_Gacha_AvatarImg_InternalAsset.png"


def test_costume_art_url_uses_costume_asset() -> None:
    build = raw_build("Traveler", "https://enka.network/ui/UI_AvatarIcon_PlayerGirlCostumeExample.png", 200701)
    assert exact_art_url(build) == "https://enka.network/ui/UI_Costume_PlayerGirlCostumeExample.png"


def test_refinement_is_converted_from_zero_based_value() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png")
    assert refinement(build) == 4
    parsed = parse_builds({"data": [build]})
    assert parsed[0].constellation == 2
    assert parsed[0].refinement == 4


def test_character_element_reads_known_element() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png", element="Pyro")
    assert character_element(build) == "Pyro"


def test_character_element_rejects_unknown_value() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png", element="NotAnElement")
    assert character_element(build) is None


def test_character_element_missing_metadata_is_none() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png")
    assert character_element(build) is None


def test_weapon_rarity_uses_rarity_map_when_available() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png", weapon_id=11512)
    assert weapon_rarity(build, {"11512": 5}) == 5


def test_weapon_rarity_falls_back_to_third_digit_without_map() -> None:
    assert weapon_rarity(raw_build("A", "u", weapon_id=11512)) == 5
    assert weapon_rarity(raw_build("A", "u", weapon_id=14402)) == 4
    assert weapon_rarity(raw_build("A", "u", weapon_id=13303)) == 3
    assert weapon_rarity(raw_build("A", "u", weapon_id=14101)) == 1


def test_weapon_rarity_falls_back_when_map_does_not_know_id() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png", weapon_id=14402)
    assert weapon_rarity(build, {"99999": 5}) == 4


def test_weapon_rarity_rejects_non_five_digit_ids() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png", weapon_id=123)
    assert weapon_rarity(build) is None


def test_weapon_rarity_missing_weapon_id_is_none() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png")
    assert weapon_rarity(build) is None


def test_character_rarity_uses_quality_map() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png", character_id=10000002)
    assert character_rarity(build, {"10000002": 5}) == 5


def test_character_rarity_unknown_id_is_none() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png", character_id=10000002)
    assert character_rarity(build, {"other": 5}) is None


def test_character_rarity_without_map_is_none() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png", character_id=10000002)
    assert character_rarity(build) is None


def test_parse_builds_fills_element_and_rarities() -> None:
    build = raw_build(
        "Character",
        "https://enka.network/ui/UI_AvatarIcon_Character.png",
        element="Hydro",
        character_id=10000002,
        weapon_id=11512,
    )
    parsed = parse_builds({"data": [build]}, {"10000002": 5}, {"11512": 5})
    assert parsed[0].element == "Hydro"
    assert parsed[0].rarity == 5
    assert parsed[0].weapon_rarity == 5


def test_parse_builds_defaults_to_none_when_nothing_is_known() -> None:
    build = raw_build("Character", "https://enka.network/ui/UI_AvatarIcon_Character.png")
    parsed = parse_builds({"data": [build]})
    assert parsed[0].element is None
    assert parsed[0].rarity is None
    assert parsed[0].weapon_rarity is None


def test_load_enka_rarities_distills_and_caches(tmp_path: Path) -> None:
    cache_path = tmp_path / "enka-rarities.json"
    calls: list[str] = []

    def fake_fetch(url: str):
        calls.append(url)
        if "avatars" in url:
            return {
                "10000002": {"QualityType": "QUALITY_ORANGE"},
                "10000003": {"QualityType": "QUALITY_PURPLE"},
                "10000004": {"NoQualityType": True},
            }
        return {
            "11512": {"Rarity": 5},
            "14402": {"Rarity": 4},
            "99999": {"Rarity": "not-an-int"},
        }

    characters, weapons = load_enka_rarities(cache_path, fetch=fake_fetch)
    assert characters == {"10000002": 5, "10000003": 4}
    assert weapons == {"11512": 5, "14402": 4}
    assert len(calls) == 2
    assert cache_path.exists()

    # A fresh cache is reused without calling fetch again.
    calls.clear()
    characters_again, weapons_again = load_enka_rarities(cache_path, fetch=fake_fetch)
    assert characters_again == characters
    assert weapons_again == weapons
    assert calls == []


def test_load_enka_rarities_falls_back_to_stale_cache_on_error(tmp_path: Path) -> None:
    cache_path = tmp_path / "enka-rarities.json"
    cache_path.write_text('{"characters": {"1": 5}, "weapons": {"2": 4}}', encoding="utf-8")
    old_time = time.time() - 8 * 24 * 60 * 60
    os.utime(cache_path, (old_time, old_time))

    def failing_fetch(_url: str):
        raise urllib.error.URLError("offline")

    characters, weapons = load_enka_rarities(cache_path, fetch=failing_fetch)
    assert characters == {"1": 5}
    assert weapons == {"2": 4}


def test_load_enka_rarities_falls_back_to_empty_maps_without_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "enka-rarities.json"

    def failing_fetch(_url: str):
        raise urllib.error.URLError("offline")

    characters, weapons = load_enka_rarities(cache_path, fetch=failing_fetch)
    assert characters == {}
    assert weapons == {}
