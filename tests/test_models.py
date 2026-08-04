from genshin_thumbnail_studio.models import Build, Placement, Project


def test_build_round_trip() -> None:
    build = Build(
        name="Furina",
        constellation=2,
        refinement=3,
        weapon_name="Splendor of Tranquil Waters",
        costume_id="costume-42",
        build_id="build-123",
        build_md5="abcdef0123456789",
        last_build_update="2026-08-01T12:00:00+00:00",
        art_url="https://example.com/furina.png",
        weapon_url="https://example.com/weapon.png",
        element="Hydro",
        rarity=5,
        weapon_rarity=4,
        raw={"nested": {"value": 1}, "list": [1, 2, 3]},
    )
    restored = Build.from_dict(build.to_dict())
    assert restored == build

    build_with_nones = Build(
        name="Navia",
        constellation=0,
        refinement=1,
        weapon_name="Crimson Moon's Semblance",
        costume_id=None,
        build_id="build-456",
        build_md5="0123456789abcdef",
        last_build_update=None,
        art_url="https://example.com/navia.png",
        weapon_url="https://example.com/weapon2.png",
        element=None,
        rarity=None,
        weapon_rarity=None,
        raw={},
    )
    restored_with_nones = Build.from_dict(build_with_nones.to_dict())
    assert restored_with_nones == build_with_nones


def test_project_round_trip() -> None:
    project = Project.blank("stygian", "123456789")
    project.teams[1][2].name = "Test Character"
    project.teams[1][2].offset_x = 0.42
    project.teams[1][2].flip = True
    project.output_height = 1440
    assert project.to_dict()["schemaVersion"] == 3
    restored = Project.from_dict(project.to_dict())
    assert restored.mode == "stygian"
    assert len(restored.teams) == 3
    assert restored.teams[1][2].name == "Test Character"
    assert restored.teams[1][2].offset_x == 0.42
    assert restored.teams[1][2].flip is True
    assert restored.teams[1][3].flip is False
    assert restored.output_height == 1440
    assert restored.output_size == (2560, 1440)


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
