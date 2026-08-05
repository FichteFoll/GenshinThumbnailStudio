"""Helpers shared by more than one of the akasha test modules."""

from typing import Any

from genshin_thumbnail_studio.models import Build


def raw_build(
    name: str,
    icon: str,
    costume_id: int | None = None,
    element: str | None = None,
    character_id: int | None = None,
    weapon_id: int | None = None,
) -> dict[str, Any]:
    build: dict[str, Any] = {
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


def make_build(name: str) -> Build:
    return Build(
        name=name,
        constellation=0,
        refinement=1,
        weapon_name="Weapon",
        costume_id=None,
        build_id=name,
        build_md5=name,
        last_build_update=None,
        art_url=f"https://example.invalid/{name}-art.png",
        weapon_url=f"https://example.invalid/{name}-weapon.png",
    )
