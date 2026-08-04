from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from . import renderer
from .models import Build, Placement, Project


def app_data_dir() -> Path:
    override = os.environ.get("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR")
    if override:
        target = Path(override).expanduser()
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        target = base / "GenshinThumbnailStudio"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        target = base / "GenshinThumbnailStudio"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        target = base / "GenshinThumbnailStudio"
    target.mkdir(parents=True, exist_ok=True)
    return target


def cache_dir() -> Path:
    target = app_data_dir() / "cache"
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_project(project: Project, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")


def _clamp_to_cover_fit(offset: float, resized: int, target: int) -> float:
    """Clamp a migrated offset to the range the focal point could reach.

    Focal points were clamped to the cover-fit slack, so a saturated `fy` of
    1.0 meant "the bottom edge of the art". Converting it verbatim would yield
    an offset far outside that slack, which the renderer would then clamp to
    its own, wider limit, shifting the portrait. Clamping here keeps a migrated
    file framed the way it was saved.
    """
    # Absolute, for the same reason as `renderer._offset_limits()`: a zoom below
    # the cover fit makes the resized art smaller than the panel, and a signed
    # slack would go negative there and invert the clamp below.
    limit = abs(resized - target) / (2 * target)
    return max(-limit, min(limit, offset))


def _migrate_focal_point(placement: dict[str, Any], compact: bool) -> dict[str, Any]:
    """Convert a pre-v3 `fx`/`fy` focal point into panel-relative offsets.

    The old focal point was a position in *source-art* space, so the conversion
    depends on the art's aspect ratio. The art is not available when a file is
    read, so the standard Enka splash art is assumed; placements using off-spec
    art shift slightly on first load and can simply be re-dragged.
    """
    if "fx" not in placement and "fy" not in placement:
        return placement
    migrated = {key: value for key, value in placement.items() if key not in {"fx", "fy"}}
    try:
        zoom = float(placement.get("zoom", Placement().zoom))
        target_w, target_h = renderer.panel_target_size(compact)
        resized_w, resized_h = renderer.resized_art_size(renderer.STANDARD_ART_SIZE, compact, zoom)
        if "fx" in placement:
            offset_x = (0.5 - float(placement["fx"])) * resized_w / target_w
            migrated["offset_x"] = _clamp_to_cover_fit(offset_x, resized_w, target_w)
        if "fy" in placement:
            offset_y = (0.5 - float(placement["fy"])) * resized_h / target_h
            migrated["offset_y"] = _clamp_to_cover_fit(offset_y, resized_h, target_h)
    except (TypeError, ValueError):
        return migrated
    return migrated


def _migrate_focal_point_if_dict(value: Any, compact: bool) -> Any:
    if isinstance(value, dict):
        return _migrate_focal_point(cast("dict[str, Any]", value), compact)
    return value


def load_project(path: Path) -> Project:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Project file must contain a JSON object.")
    value = cast(dict[str, Any], raw)
    compact = str(value.get("mode", "abyss")).casefold() == "abyss"
    teams = value.get("teams")
    if isinstance(teams, list):
        teams_list = cast("list[Any]", teams)
        value = dict(value)
        value["teams"] = [
            [_migrate_focal_point_if_dict(member, compact) for member in cast("list[Any]", team)]
            if isinstance(team, list)
            else team
            for team in teams_list
        ]
    return Project.from_dict(value)


def profile_cache_path(uid: str) -> Path:
    target = cache_dir() / "profiles"
    target.mkdir(parents=True, exist_ok=True)
    return target / f"{uid}.json"


def save_profile_cache(uid: str, builds: list[Build], last_update: datetime) -> None:
    path = profile_cache_path(uid)
    payload = {
        "uid": uid,
        "lastProfileUpdate": last_update.isoformat(),
        "builds": [build.to_dict() for build in builds],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_profile_cache(uid: str) -> tuple[list[Build], datetime] | None:
    path = profile_cache_path(uid)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        last_update = datetime.fromisoformat(value["lastProfileUpdate"])
        builds = [Build.from_dict(item) for item in value["builds"]]
        return builds, last_update
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def load_presets() -> dict[str, dict[str, float]]:
    path = app_data_dir() / "placements.json"
    if not path.exists():
        return {}
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    value = cast(dict[str, Any], raw)
    # Presets carry no mode of their own; it is the first half of their key
    # (see gui._preset_key), and the geometry the conversion needs depends on it.
    return {
        key: _migrate_focal_point_if_dict(preset, key.split("|", 1)[0] != "stygian")
        for key, preset in value.items()
    }


def save_presets(value: dict[str, dict[str, float]]) -> None:
    path = app_data_dir() / "placements.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
