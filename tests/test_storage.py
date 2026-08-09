"""Tests for `genshin_thumbnail_studio.storage`."""

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from genshin_thumbnail_studio.models import CUSTOM_BUILD_NAME, Build, Profile, Project
from genshin_thumbnail_studio.renderer import STANDARD_ART_SIZE, panel_target_size, resized_art_size
from genshin_thumbnail_studio.storage import (
    app_data_dir,
    load_last_profile,
    load_presets,
    load_profile_cache,
    load_project,
    migrate_project_data,
    profile_cache_path,
    save_last_profile,
    save_profile_cache,
    save_project,
    settings_path,
)


def make_build(name: str) -> Build:
    return Build(
        name=name,
        constellation=2,
        refinement=1,
        weapon_name="Splendor of Tranquil Waters",
        costume_id=None,
        build_id=f"{name}-build",
        art_url=f"https://enka.network/ui/{name}.png",
        weapon_url="https://enka.network/ui/weapon.png",
        element="Hydro",
        rarity=5,
        weapon_rarity=5,
    )


def make_profile(identifier: str, names: list[str], username: str = "") -> Profile:
    return Profile(
        identifier=identifier,
        uid="" if username else identifier,
        username=username,
        builds={name.casefold(): [make_build(name)] for name in names},
        fetched_at=datetime(2026, 8, 3, 10, 30, 15),
    )


def test_profile_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    profile = make_profile("700000001", ["Furina", "Nahida"])

    save_profile_cache(profile)
    cached = load_profile_cache("700000001")

    assert cached == profile


def test_profile_cache_is_keyed_by_a_sanitized_identifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A username is free text, so it cannot reach the file system unsanitized."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    profile = make_profile("../Algo inde", ["Furina"], username="../Algo inde")

    save_profile_cache(profile)

    path = profile_cache_path("../Algo inde")
    assert path.name == "Algo_inde.json"
    assert path.parent == tmp_path / "app-data" / "cache" / "profiles"
    assert load_profile_cache("../Algo inde") == profile


def test_load_profile_cache_without_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    assert load_profile_cache("700000002") is None


def test_load_profile_cache_with_invalid_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    profile_cache_path("700000003").write_text("{not json", encoding="utf-8")

    assert load_profile_cache("700000003") is None


def _expected_offsets(focal_x: float, focal_y: float, zoom: float, compact: bool) -> tuple[float, float]:
    target_w, target_h = panel_target_size(compact)
    resized_w, resized_h = resized_art_size(STANDARD_ART_SIZE, compact, zoom)
    return ((0.5 - focal_x) * resized_w / target_w, (0.5 - focal_y) * resized_h / target_h)


def test_load_project_migrates_legacy_focal_points(tmp_path: Path) -> None:
    member = {"name": "Furina", "fx": 0.541, "fy": 0.52, "zoom": 1.06, "color": "#78d7ff"}
    payload: dict[str, object] = {
        "schemaVersion": 2,
        "mode": "abyss",
        "uid": "700000042",
        "outputName": "genshin_thumbnail",
        "outputHeight": 1080,
        "activeTeam": 0,
        "teams": [[dict(member) for _ in range(4)] for _ in range(2)],
    }
    path = tmp_path / "legacy-project.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    project = load_project(path)

    expected_x, expected_y = _expected_offsets(0.541, 0.52, 1.06, compact=True)
    migrated = project.teams[0][0]
    assert migrated.name == "Furina"
    assert migrated.offset_x == expected_x
    assert migrated.offset_y == expected_y
    # The documented conversion, with the resized art size unrounded.
    assert abs(migrated.offset_x - (0.5 - 0.541) * 763.2 / 416) < 1e-3
    assert abs(migrated.offset_y - (0.5 - 0.52) * 381.6 / 360) < 1e-3


def test_load_project_keeps_a_saturated_focal_point_at_the_art_edge(tmp_path: Path) -> None:
    # ``fy: 1.0`` meant "the bottom edge of the art": the old renderer clamped
    # the crop to the cover-fit slack. The migrated offset must stay there.
    member = {"name": "Furina", "fx": 0.5, "fy": 1.0, "zoom": 1.06}
    payload: dict[str, object] = {
        "schemaVersion": 2,
        "mode": "abyss",
        "teams": [[dict(member) for _ in range(4)] for _ in range(2)],
    }
    path = tmp_path / "saturated-project.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    project = load_project(path)

    _, target_h = panel_target_size(compact=True)
    _, resized_h = resized_art_size(STANDARD_ART_SIZE, compact=True, zoom=1.06)
    migrated = project.teams[0][0]
    assert migrated.offset_y == -(resized_h - target_h) / (2 * target_h)
    # The crop lands on the same row the legacy focal point produced.
    legacy_top = min(round(1.0 * resized_h - target_h / 2), resized_h - target_h)
    assert round((resized_h - target_h) / 2 - migrated.offset_y * target_h) == legacy_top


def test_migrate_project_data_lifts_a_v3_payload_to_v4() -> None:
    """R12: a v3 file gains the profile name and a per-placement build slot."""
    payload: dict[str, object] = {
        "schemaVersion": 3,
        "mode": "abyss",
        "uid": "700000042",
        "teams": [[{"name": "Furina", "offset_x": 0.1}] * 4] * 2,
    }

    migrated = migrate_project_data(payload)

    assert migrated["schemaVersion"] == 4
    assert migrated["profileName"] == ""
    teams = cast("list[list[dict[str, object]]]", migrated["teams"])
    assert all(member["build"] is None for team in teams for member in team)
    # The already-migrated payload passes through untouched.
    assert migrate_project_data(migrated) == migrated


def test_migrate_project_data_still_converts_a_pre_v3_focal_point() -> None:
    payload: dict[str, object] = {
        "schemaVersion": 2,
        "mode": "abyss",
        "teams": [[{"name": "Furina", "fx": 0.541, "fy": 0.52, "zoom": 1.06}] * 4] * 2,
    }

    migrated = migrate_project_data(payload)

    member = cast("list[list[dict[str, object]]]", migrated["teams"])[0][0]
    assert "fx" not in member and "fy" not in member
    assert (member["offset_x"], member["offset_y"]) == _expected_offsets(0.541, 0.52, 1.06, compact=True)
    assert migrated["schemaVersion"] == 4
    assert member["build"] is None


def test_migrate_project_data_pins_v1_output_height() -> None:
    """Bumping the schema version must not hide a v1 file's 720p rendering
    from `Project.from_dict()`, which keys that rule on the version it reads."""
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "mode": "abyss",
        "uid": "700000042",
        "teams": [[{"name": "Furina"}] * 4] * 2,
    }

    migrated = migrate_project_data(payload)

    assert migrated["outputHeight"] == 720
    assert migrated["schemaVersion"] == 4


def test_last_profile_round_trips(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R13: the identifier the user last loaded is remembered globally."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))

    assert load_last_profile() == ""

    save_last_profile("Algoinde")
    assert load_last_profile() == "Algoinde"

    save_last_profile("700000042")
    assert load_last_profile() == "700000042"


def test_load_last_profile_survives_a_malformed_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    settings_path().write_text("{not json", encoding="utf-8")

    assert load_last_profile() == ""

    settings_path().write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    assert load_last_profile() == ""


def test_load_presets_migrates_legacy_focal_points(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    legacy: dict[str, dict[str, object]] = {
        "abyss|costume-1": {"fx": 0.541, "fy": 0.52, "zoom": 1.06},
        "stygian|costume-2": {"fx": 0.4, "fy": 0.5, "zoom": 1.18},
        "abyss|costume-3": {"offset_x": 0.12, "offset_y": -0.03, "zoom": 1.10},
    }
    (app_data_dir() / "placements.json").write_text(json.dumps(legacy), encoding="utf-8")

    presets = load_presets()

    abyss = presets["abyss|costume-1"]
    assert "fx" not in abyss and "fy" not in abyss
    assert (abyss["offset_x"], abyss["offset_y"]) == _expected_offsets(0.541, 0.52, 1.06, compact=True)

    stygian = presets["stygian|costume-2"]
    assert (stygian["offset_x"], stygian["offset_y"]) == _expected_offsets(0.4, 0.5, 1.18, compact=False)

    # Already migrated entries are passed through untouched.
    assert presets["abyss|costume-3"] == legacy["abyss|costume-3"]


def test_a_custom_build_survives_the_project_file(tmp_path: Path) -> None:
    """R9: a slot's own edited build reopens with the file, art and badges intact.

    It needs no field of its own to do so: it is the placement's snapshot like
    any other build, so the format that already carries a snapshot carries this.
    """
    project = Project.blank(uid="700000042")
    custom = replace(
        make_build("Furina"),
        build_name=CUSTOM_BUILD_NAME,
        build_id="",
        constellation=6,
        refinement=5,
        costume_id="200301",
        art_url="https://enka.network/ui/UI_Costume_FurinaCostumeSummer.png",
    )
    member = project.teams[0][0]
    member.name = "Furina"
    member.build = custom
    path = tmp_path / "project.json"

    save_project(project, path)
    reopened = load_project(path).teams[0][0]

    assert reopened.build == custom
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 4
