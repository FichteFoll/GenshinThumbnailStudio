"""Tests for `genshin_thumbnail_studio.models`."""

from genshin_thumbnail_studio.models import LIVE_BUILD_NAME, Build, Placement, Project


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
    assert build.key == "furina|vape"
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
    # The live build is the default, and its key is the character alone.
    assert build_with_nones.key == "navia|live"


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
