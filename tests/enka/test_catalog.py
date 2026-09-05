"""Tests for `enka.catalog`, against literal data rather than the real files.

Nothing here touches the network or the real asset directory: the `Catalog` is
built from small dicts shaped like Enka's own data, and `load_catalog()` is
exercised against `tmp_path` with `catalog.download` monkeypatched.
"""

import http.client
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from genshin_thumbnail_studio.enka import catalog, freshness
from genshin_thumbnail_studio.enka.errors import EnkaError
from genshin_thumbnail_studio.models import Build

ROOT = "https://enka.network"

AYAKA_ART = f"{ROOT}/ui/UI_Gacha_AvatarImg_Ayaka.png"
FRUHLING_ART = f"{ROOT}/ui/UI_Costume_AyakaCostumeFruhling.png"
SPRING_ART = f"{ROOT}/ui/UI_Costume_AyakaCostumeSpring.png"
BOY_ART = f"{ROOT}/ui/UI_Gacha_AvatarImg_PlayerBoy.png"
GIRL_ART = f"{ROOT}/ui/UI_Gacha_AvatarImg_PlayerGirl.png"

CHARACTERS: dict[str, Any] = {
    "10000002": {
        "NameTextMapHash": 600001,
        "SideIconName": "/ui/UI_AvatarIcon_Side_Ayaka.png",
        "Element": "Ice",
        "WeaponType": "WEAPON_SWORD_ONE_HAND",
        # Deliberately out of id order, to pin the ordering down.
        "Costumes": {
            "200302": {"Art": "/ui/UI_Costume_AyakaCostumeFruhling.png"},
            "200301": {"Art": "/ui/UI_Costume_AyakaCostumeSpring.png"},
        },
    },
    "10000003": {
        "NameTextMapHash": 600002,
        "SideIconName": "/ui/UI_AvatarIcon_Side_Bennett.png",
        "Element": "Fire",
        "WeaponType": "WEAPON_CLAYMORE",
    },
    # The Traveler: several entries per body, which is the only character the
    # name alone does not identify. The first of them carries neither an element
    # nor a weapon type, exactly as the real data file does.
    "10000005": {
        "NameTextMapHash": 600003,
        "SideIconName": "/ui/UI_AvatarIcon_Side_PlayerBoy.png",
    },
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
    "10000007-anemo": {
        "NameTextMapHash": 600003,
        "SideIconName": "/ui/UI_AvatarIcon_Side_PlayerGirl.png",
        "Element": "Wind",
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
    "11999": {
        "NameTextMapHash": 799999,
        "Rarity": 4,
        "WeaponType": 1,
        "Icon": "/ui/UI_EquipIcon_Sword_Ghost.png",
    },
}

NAMES = {
    "600001": "Kamisato Ayaka",
    "600002": "Bennett",
    "600003": "Traveler",
    "700001": "Dull Blade",
    "700002": "Mistsplitter Reforged",
    "700003": "Aquila Favonia",
    "700004": "Wolf's Gravestone",
}


def make_catalog() -> catalog.Catalog:
    return catalog.Catalog(dict(CHARACTERS), dict(WEAPONS), dict(NAMES))


def make_build(
    name: str = "Kamisato Ayaka",
    *,
    costume_id: str | None = None,
    art_url: str = AYAKA_ART,
    weapon_name: str = "Mistsplitter Reforged",
    weapon_url: str = f"{ROOT}/ui/UI_EquipIcon_Sword_Narukami_Awaken.png",
    weapon_rarity: int | None = 5,
) -> Build:
    return Build(
        name=name,
        constellation=0,
        refinement=1,
        weapon_name=weapon_name,
        costume_id=costume_id,
        art_url=art_url,
        weapon_url=weapon_url,
        element="Cryo",
        rarity=5,
        weapon_rarity=weapon_rarity,
    )


def test_skins_offer_the_default_art_and_every_costume() -> None:
    options = make_catalog().skins(make_build())

    assert options == [
        catalog.SkinOption("Default", None, AYAKA_ART),
        catalog.SkinOption("Spring", "200301", SPRING_ART),
        catalog.SkinOption("Fruhling", "200302", FRUHLING_ART),
    ]


def test_skins_keep_a_costume_the_catalog_does_not_list() -> None:
    """The build's own skin can never be lost, however stale the catalog is."""
    build = make_build(costume_id="209999", art_url=f"{ROOT}/ui/UI_Costume_AyakaCostumeUnknown.png")

    options = make_catalog().skins(build)

    assert options[-1] == catalog.SkinOption("209999", "209999", build.art_url)
    assert [option.costume_id for option in options] == [None, "200301", "200302", "209999"]


def test_skins_of_an_unknown_character_degrade_to_the_build_itself() -> None:
    build = make_build(name="Someone Else", costume_id="123", art_url=f"{ROOT}/ui/UI_Custom.png")

    assert make_catalog().skins(build) == [catalog.SkinOption("Current", "123", build.art_url)]


def test_weapons_are_filtered_named_and_sorted() -> None:
    options = make_catalog().weapons_for(make_build())

    assert options == [
        catalog.WeaponOption("Aquila Favonia", f"{ROOT}/ui/UI_EquipIcon_Sword_Falcon.png", 5),
        catalog.WeaponOption(
            "Mistsplitter Reforged", f"{ROOT}/ui/UI_EquipIcon_Sword_Narukami_Awaken.png", 5
        ),
        catalog.WeaponOption("Dull Blade", f"{ROOT}/ui/UI_EquipIcon_Sword_Blunt.png", 1),
    ]


def test_weapons_keep_the_build_s_own_weapon_when_the_catalog_lacks_it() -> None:
    build = make_build(
        weapon_name="Prototype Rancour",
        weapon_url=f"{ROOT}/ui/UI_EquipIcon_Sword_Proto.png",
        weapon_rarity=4,
    )

    options = make_catalog().weapons_for(build)

    assert options[0] == catalog.WeaponOption("Prototype Rancour", build.weapon_url, 4)
    assert len(options) == 4


def test_weapons_of_an_unknown_character_are_not_filtered() -> None:
    build = make_build(
        name="Someone Else",
        weapon_name="Dull Blade",
        weapon_url=f"{ROOT}/ui/UI_EquipIcon_Sword_Blunt.png",
    )

    names = [option.name for option in make_catalog().weapons_for(build)]

    assert "Wolf's Gravestone" in names


def test_weapons_of_the_traveler_are_still_filtered_to_swords() -> None:
    """The type comes from the first entry that names one, not simply the first.

    The Traveler's leading entries carry no `WeaponType`, so reading `entries[0]`
    alone drops the filter and offers every weapon in the game to the one
    character the popup exists to serve specially.
    """
    build = make_build(name="Traveler", art_url=BOY_ART)

    names = [option.name for option in make_catalog().weapons_for(build)]

    assert "Wolf's Gravestone" not in names
    assert "Aquila Favonia" in names


def test_element_is_variable_only_for_the_traveler() -> None:
    catalogue = make_catalog()

    assert catalogue.element_is_variable(make_build(name="Traveler", art_url=BOY_ART))
    assert not catalogue.element_is_variable(make_build())


def test_element_is_not_variable_for_a_single_matching_entry() -> None:
    """Lumine's one Anemo entry: the art narrows the name down to her body."""
    assert not make_catalog().element_is_variable(make_build(name="Traveler", art_url=GIRL_ART))


def test_a_traveler_whose_art_is_unlisted_keeps_every_entry() -> None:
    """A narrowing that matches nothing keeps all matches rather than none, so a
    catalog too old to know the build's skin still knows the element varies."""
    build = make_build(
        name="Traveler",
        costume_id="209999",
        art_url=f"{ROOT}/ui/UI_Costume_PlayerBoyUnknown.png",
    )

    assert make_catalog().element_is_variable(build)


def test_a_costume_label_falls_back_to_its_id() -> None:
    """An art file name with nothing after its last `Costume` leaves no label."""
    characters: dict[str, Any] = {
        "10000003": {
            "NameTextMapHash": 600002,
            "SideIconName": "/ui/UI_AvatarIcon_Side_Bennett.png",
            "Element": "Fire",
            "WeaponType": "WEAPON_CLAYMORE",
            "Costumes": {"203101": {"Art": "/ui/UI_Costume_BennettCostume.png"}},
        }
    }

    options = catalog.Catalog(characters, {}, dict(NAMES)).skins(make_build(name="Bennett"))

    assert options[1] == catalog.SkinOption("203101", "203101", f"{ROOT}/ui/UI_Costume_BennettCostume.png")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_asset_files(root: Path) -> None:
    write_json(root / "characters.json", CHARACTERS)
    write_json(root / "text_map.json", {"en": NAMES, "de": {}})


def stale_weapon_file(root: Path) -> Path:
    """A cached `weapons.json` old enough to be refreshed."""
    path = root / "weapons.json"
    write_json(path, WEAPONS)
    stale = time.time() - (freshness.DATA_MAX_AGE_DAYS + 1) * 86400
    os.utime(path, (stale, stale))
    return path


def recording_download(payload: dict[str, Any], calls: list[str]) -> Callable[[str, Path], None]:
    def fake_download(url: str, destination: Path) -> None:
        calls.append(url)
        write_json(destination, payload)

    return fake_download


def test_load_catalog_downloads_missing_weapon_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_asset_files(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(catalog, "download", recording_download(WEAPONS, calls))

    loaded = catalog.load_catalog(tmp_path)

    assert calls == [catalog.WEAPON_DATA_URL]
    assert (tmp_path / "weapons.json").is_file()
    assert [option.name for option in loaded.weapons_for(make_build())] == [
        "Aquila Favonia",
        "Mistsplitter Reforged",
        "Dull Blade",
    ]


def test_load_catalog_keeps_fresh_weapon_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_asset_files(tmp_path)
    write_json(tmp_path / "weapons.json", WEAPONS)
    calls: list[str] = []
    monkeypatch.setattr(catalog, "download", recording_download(WEAPONS, calls))

    loaded = catalog.load_catalog(tmp_path)

    assert calls == []
    assert len(loaded.weapons_for(make_build())) == 3


def test_load_catalog_falls_back_to_stale_weapon_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_asset_files(tmp_path)
    weapons_file = stale_weapon_file(tmp_path)

    def failing_download(url: str, destination: Path) -> None:
        raise EnkaError(f"Could not download {url}: connection reset")

    monkeypatch.setattr(catalog, "download", failing_download)

    loaded = catalog.load_catalog(tmp_path)

    assert len(loaded.weapons_for(make_build())) == 3
    assert json.loads(weapons_file.read_text(encoding="utf-8")) == WEAPONS


def test_load_catalog_rejects_a_truncated_download(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A response that arrives but does not parse must not replace the cache."""
    write_asset_files(tmp_path)
    weapons_file = stale_weapon_file(tmp_path)

    def truncated_download(url: str, destination: Path) -> None:
        destination.write_text('{"11101": {"Nam', encoding="utf-8")

    monkeypatch.setattr(catalog, "download", truncated_download)

    loaded = catalog.load_catalog(tmp_path)

    assert len(loaded.weapons_for(make_build())) == 3
    assert json.loads(weapons_file.read_text(encoding="utf-8")) == WEAPONS
    assert not (tmp_path / "weapons.json.part").exists()


def test_load_catalog_survives_a_download_that_is_no_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`http.client.HTTPException` is no `OSError`, so `download()` lets it
    through; `load_catalog()` still has to degrade rather than raise."""
    write_asset_files(tmp_path)
    weapons_file = stale_weapon_file(tmp_path)

    def interrupted_download(url: str, destination: Path) -> None:
        destination.write_text('{"11101"', encoding="utf-8")
        raise http.client.IncompleteRead(b'{"11101"')

    monkeypatch.setattr(catalog, "download", interrupted_download)

    loaded = catalog.load_catalog(tmp_path)

    assert len(loaded.weapons_for(make_build())) == 3
    assert json.loads(weapons_file.read_text(encoding="utf-8")) == WEAPONS
    assert not (tmp_path / "weapons.json.part").exists()


def test_load_catalog_degrades_to_empty_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No asset files at all, and a failing download: still a usable catalog."""

    def failing_download(url: str, destination: Path) -> None:
        raise EnkaError(f"Could not download {url}: offline")

    monkeypatch.setattr(catalog, "download", failing_download)

    loaded = catalog.load_catalog(tmp_path)
    build = make_build()

    assert loaded.skins(build) == [catalog.SkinOption("Current", None, build.art_url)]
    assert loaded.weapons_for(build) == [
        catalog.WeaponOption(build.weapon_name, build.weapon_url, 5)
    ]
    assert not loaded.element_is_variable(build)


def test_invalidate_weapon_data_removes_the_cached_file(tmp_path: Path) -> None:
    weapons_file = tmp_path / "weapons.json"
    write_json(weapons_file, WEAPONS)

    catalog.invalidate_weapon_data(tmp_path)

    assert not weapons_file.exists()


def test_invalidate_weapon_data_ignores_a_root_without_one(tmp_path: Path) -> None:
    """A cache drop is never a failure, so nothing to drop is a no-op."""
    catalog.invalidate_weapon_data(tmp_path)

    assert not (tmp_path / "weapons.json").exists()
