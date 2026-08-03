from genshin_thumbnail_studio.models import Project


def test_project_round_trip() -> None:
    project = Project.blank("stygian", "123456789")
    project.teams[1][2].name = "Test Character"
    project.teams[1][2].fx = 0.42
    project.output_height = 1440
    restored = Project.from_dict(project.to_dict())
    assert restored.mode == "stygian"
    assert len(restored.teams) == 3
    assert restored.teams[1][2].name == "Test Character"
    assert restored.teams[1][2].fx == 0.42
    assert restored.output_height == 1440
    assert restored.output_size == (2560, 1440)


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


def test_abyss_shape() -> None:
    project = Project.blank("abyss")
    project.ensure_shape()
    assert len(project.teams) == 2
    assert all(len(team) == 4 for team in project.teams)
