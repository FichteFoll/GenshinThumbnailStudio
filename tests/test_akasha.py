from genshin_thumbnail_studio.akasha import exact_art_url, parse_builds, refinement


def raw_build(name: str, icon: str, costume_id=None) -> dict:
    return {
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
