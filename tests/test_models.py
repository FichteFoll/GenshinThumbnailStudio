"""Tests for `genshin_thumbnail_studio.models`."""

import hashlib
from datetime import datetime
from pathlib import Path

from genshin_thumbnail_studio.models import LIVE_BUILD_NAME, Build, Placement, Profile, Project


def make_build(
    name: str = "Furina",
    art_url: str = "https://enka.network/ui/furina.png",
    weapon_url: str = "https://enka.network/ui/weapon.png",
) -> Build:
    return Build(
        name=name,
        constellation=0,
        refinement=1,
        weapon_name="Weapon",
        costume_id=None,
        art_url=art_url,
        weapon_url=weapon_url,
    )


def test_build_round_trip() -> None:
    build = Build(
        name="Furina",
        constellation=2,
        refinement=3,
        weapon_name="Splendor of Tranquil Waters",
        costume_id="costume-42",
        art_url="https://example.com/furina.png",
        weapon_url="https://example.com/weapon.png",
        build_name="Vape",
        build_id="build-123",
        element="Hydro",
        rarity=5,
        weapon_rarity=4,
    )
    restored = Build.from_dict(build.to_dict())
    assert restored == build
    assert build.details() == ("costume-42", "Splendor of Tranquil Waters", 2, 3)

    build_with_nones = Build(
        name="Navia",
        constellation=0,
        refinement=1,
        weapon_name="Crimson Moon's Semblance",
        costume_id=None,
        art_url="https://example.com/navia.png",
        weapon_url="https://example.com/weapon2.png",
    )
    restored_with_nones = Build.from_dict(build_with_nones.to_dict())
    assert restored_with_nones == build_with_nones
    assert build_with_nones.build_name == LIVE_BUILD_NAME


def test_build_paths_reproduce_the_cache_naming_scheme() -> None:
    """R3: the derived paths are byte-for-byte the ones the downloader computed
    for itself before, so an existing cache keeps working. The literals below
    are what `enka.assets._asset_path()` produced."""
    build = make_build(
        name="Furina",
        art_url="https://enka.network/ui/UI_Gacha_AvatarImg_Furina.png",
        weapon_url="https://enka.network/ui/UI_EquipIcon_Sword_Test.jpg",
    )
    root = Path("/cache/assets")

    assert build.art_path(root) == root / "characters" / "Furina-7d50180696917f6b.png"
    assert build.weapon_path(root) == root / "weapons" / "Furina-7cf6974cc25429e1.jpg"


def test_build_paths_fall_back_to_png_for_an_unusable_url_extension() -> None:
    build = make_build(
        art_url="https://enka.network/ui/no-extension",
        weapon_url="https://enka.network/ui/other.webp",
    )
    root = Path("/cache/assets")

    assert build.art_path(root).name == "Furina-ff5c6a2adadd28e9.png"
    assert build.weapon_path(root).name == "Furina-00dd3b8d95eef6e5.webp"


def test_the_url_digest_is_what_keeps_two_builds_of_one_character_apart() -> None:
    root = Path("/cache/assets")
    live = make_build(art_url="https://enka.network/ui/furina.png", weapon_url="https://enka.network/ui/a.png")
    skinned = make_build(art_url="https://enka.network/ui/furina-skin.png", weapon_url="https://enka.network/ui/b.png")

    assert live.art_path(root) != skinned.art_path(root)
    assert live.weapon_path(root) != skinned.weapon_path(root)

    # Two builds that download the same files share them, whatever else differs.
    same = make_build(art_url=live.art_url, weapon_url=live.weapon_url)
    same.build_name = "Vape"
    same.constellation = 6
    assert same.art_path(root) == live.art_path(root)
    assert same.weapon_path(root) == live.weapon_path(root)


def test_a_name_full_of_separators_still_yields_one_path_segment() -> None:
    url = "https://enka.network/ui/traveler.png"
    build = make_build(name="../../Traveler (Anemo)/", art_url=url, weapon_url=url)
    root = Path("/cache/assets")

    art = build.art_path(root)
    assert art.parent == root / "characters"
    assert art.name == f"Traveler_Anemo-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}.png"


def test_build_from_dict_tolerates_a_payload_without_the_newer_keys() -> None:
    build = Build.from_dict(
        {
            "name": "Navia",
            "constellation": 0,
            "refinement": 1,
            "weapon_name": "Verdict",
            "costume_id": None,
            "art_url": "https://example.com/navia.png",
            "weapon_url": "https://example.com/weapon.png",
            "build_md5": "no longer a field",
        }
    )
    assert build.build_name == LIVE_BUILD_NAME
    assert build.build_id == ""


def test_project_round_trip() -> None:
    project = Project.blank("stygian", "123456789")
    project.teams[1][2].name = "Test Character"
    project.teams[1][2].offset_x = 0.42
    project.teams[1][2].flip = True
    project.output_height = 1440
    assert project.to_dict()["schemaVersion"] == 4
    restored = Project.from_dict(project.to_dict())
    assert restored.mode == "stygian"
    assert len(restored.teams) == 3
    assert restored.teams[1][2].name == "Test Character"
    assert restored.teams[1][2].offset_x == 0.42
    assert restored.teams[1][2].flip is True
    assert restored.teams[1][3].flip is False
    assert restored.output_height == 1440
    assert restored.output_size == (2560, 1440)


def test_project_round_trips_the_profile_name_and_the_placement_build() -> None:
    """R3/R9: the Enka username lives in a field of its own, and every placement
    carries the build it was framed with, so the framing survives the profile
    changing on Enka."""
    project = Project.blank("abyss", "700000042")
    project.profile_name = "Algoinde"
    build = Build(
        name="Furina",
        constellation=2,
        refinement=3,
        weapon_name="Splendor of Tranquil Waters",
        costume_id="200301",
        art_url="https://enka.network/ui/furina.png",
        weapon_url="https://enka.network/ui/weapon.png",
        build_name="Vape",
        build_id="build-7",
        element="Hydro",
        rarity=5,
        weapon_rarity=5,
    )
    project.teams[0][0].name = "Furina"
    project.teams[0][0].build = build

    value = project.to_dict()
    assert value["schemaVersion"] == 4
    assert value["profileName"] == "Algoinde"

    restored = Project.from_dict(value)
    assert restored.profile_name == "Algoinde"
    assert restored.uid == "700000042"
    assert restored.teams[0][0].build == build
    assert restored.teams[0][1].build is None
    # The profile name takes priority over the UID (R4).
    assert restored.identifier == "Algoinde"
    restored.profile_name = ""
    assert restored.identifier == "700000042"


def test_placement_from_dict_ignores_unknown_keys() -> None:
    """A raw legacy payload must load with default framing rather than raise;
    storage.load_project() is what converts the old focal point."""
    placement = Placement.from_dict({"name": "Furina", "fx": 0.9, "fy": 0.1, "zoom": 1.2})
    assert placement.name == "Furina"
    assert placement.zoom == 1.2
    assert placement.offset_x == Placement().offset_x
    assert placement.offset_y == Placement().offset_y


def test_placement_from_dict_defaults_the_flip() -> None:
    """The flip is optional in both directions, so a member dict written before
    it existed loads as unflipped rather than raising."""
    placement = Placement.from_dict({"name": "Furina", "offset_x": 0.1, "zoom": 1.2})
    assert placement.flip is False


def test_project_output_height_defaults_to_1080p() -> None:
    project = Project.blank("abyss")
    assert project.output_height == 1080
    assert project.output_size == (1920, 1080)


def test_project_from_dict_v1_keeps_720p() -> None:
    """Version 1 files were rendered at the then-hardcoded 720p, so loading
    one must not silently change its output size. Only newly created
    projects pick up the 1080p default."""
    project = Project.blank("abyss")
    value = project.to_dict()
    value.pop("outputHeight")
    value["schemaVersion"] = 1
    restored = Project.from_dict(value)
    assert restored.output_height == 720
    assert restored.output_size == (1280, 720)

    del value["schemaVersion"]
    restored_missing_version = Project.from_dict(value)
    assert restored_missing_version.output_height == 720


def test_blank_abyss_placements_default_to_full_zoom() -> None:
    abyss = Project.blank("abyss")
    assert all(member.zoom == 1.0 for team in abyss.teams for member in team)

    stygian = Project.blank("stygian")
    assert all(member.zoom == 1.18 for team in stygian.teams for member in team)

    assert Placement().zoom == 1.0


def test_abyss_shape() -> None:
    project = Project.blank("abyss")
    project.ensure_shape()
    assert len(project.teams) == 2
    assert all(len(team) == 4 for team in project.teams)


def test_profile_live_builds_are_the_showcase_in_order() -> None:
    """The merged dict keeps the showcase recoverable: live first, saved after."""
    furina_live = make_build("Furina")
    furina_saved = make_build("Furina", art_url="https://enka.network/ui/furina-alt.png")
    furina_saved.build_name = "Bow DPS"
    nahida_live = make_build("Nahida")
    xilonen_saved = make_build("Xilonen")
    xilonen_saved.build_name = "Support"
    profile = Profile(
        identifier="700000042",
        uid="700000042",
        username="",
        builds={
            "furina": [furina_live, furina_saved],
            "nahida": [nahida_live],
            "xilonen": [xilonen_saved],
        },
        fetched_at=datetime(2026, 8, 3, 10, 30, 15),
    )

    assert profile.live_builds() == [furina_live, nahida_live]
