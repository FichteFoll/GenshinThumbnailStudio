from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .models import Project


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


def load_project(path: Path) -> Project:
    value: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Project file must contain a JSON object.")
    return Project.from_dict(value)


def load_presets() -> dict[str, dict[str, float]]:
    path = app_data_dir() / "placements.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_presets(value: dict[str, dict[str, float]]) -> None:
    path = app_data_dir() / "placements.json"
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
