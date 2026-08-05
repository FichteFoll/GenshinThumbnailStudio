"""Tests for `genshin_thumbnail_studio.storage`."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from genshin_thumbnail_studio.models import Build
from genshin_thumbnail_studio.renderer import STANDARD_ART_SIZE, panel_target_size, resized_art_size
from genshin_thumbnail_studio.storage import (
    app_data_dir,
    load_presets,
    load_profile_cache,
    load_project,
    profile_cache_path,
    save_profile_cache,
)


def make_build(name: str) -> Build:
    return Build(
        name=name,
        constellation=2,
        refinement=1,
        weapon_name="Splendor of Tranquil Waters",
        costume_id=None,
        build_id=f"{name}-build",
        build_md5="0123456789abcdef",
        last_build_update="2026-08-01T12:00:00+00:00",
        art_url=f"https://enka.network/ui/{name}.png",
        weapon_url="https://enka.network/ui/weapon.png",
        element="Hydro",
        rarity=5,
        weapon_rarity=5,
        raw={"name": name, "stats": {"critRate": 0.75}},
    )


def test_profile_cache_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    builds = [make_build("Furina"), make_build("Nahida")]
    last_update = datetime(2026, 8, 3, 10, 30, 15, tzinfo=timezone.utc)

    save_profile_cache("700000001", builds, last_update)
    cached = load_profile_cache("700000001")

    assert cached is not None
    loaded_builds, loaded_last_update = cached
    assert loaded_builds == builds
    assert loaded_last_update == last_update


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
