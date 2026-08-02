from genshin_thumbnail_studio.models import Project


def test_project_round_trip() -> None:
    project = Project.blank("stygian", "123456789")
    project.teams[1][2].name = "Test Character"
    project.teams[1][2].fx = 0.42
    restored = Project.from_dict(project.to_dict())
    assert restored.mode == "stygian"
    assert len(restored.teams) == 3
    assert restored.teams[1][2].name == "Test Character"
    assert restored.teams[1][2].fx == 0.42


def test_abyss_shape() -> None:
    project = Project.blank("abyss")
    project.ensure_shape()
    assert len(project.teams) == 2
    assert all(len(team) == 4 for team in project.teams)
