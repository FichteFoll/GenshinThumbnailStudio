from __future__ import annotations

import json
import time
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .http import fetch_json
from .parsing import as_mapping

ENKA_AVATARS_URL = "https://raw.githubusercontent.com/EnkaNetwork/API-docs/master/store/gi/avatars.json"
ENKA_WEAPONS_URL = "https://raw.githubusercontent.com/EnkaNetwork/API-docs/master/store/gi/weapons.json"
ENKA_RARITY_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

QUALITY_TYPE_RARITY = {
    "QUALITY_ORANGE": 5,
    "QUALITY_ORANGE_SP": 5,
    "QUALITY_PURPLE": 4,
    "QUALITY_BLUE": 3,
    "QUALITY_GREEN": 2,
    "QUALITY_WHITE": 1,
}


def _distill_avatar_rarities(payload: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    payload_map = as_mapping(payload)
    if payload_map is None:
        return result
    for character_id, entry in payload_map.items():
        entry_map = as_mapping(entry)
        if entry_map is None:
            continue
        quality_type = entry_map.get("QualityType")
        rarity = QUALITY_TYPE_RARITY.get(quality_type) if isinstance(quality_type, str) else None
        if rarity is not None:
            result[str(character_id)] = rarity
    return result


def _distill_weapon_rarities(payload: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    payload_map = as_mapping(payload)
    if payload_map is None:
        return result
    for weapon_id, entry in payload_map.items():
        entry_map = as_mapping(entry)
        if entry_map is None:
            continue
        rarity = entry_map.get("Rarity")
        if isinstance(rarity, int) and 1 <= rarity <= 5:
            result[str(weapon_id)] = rarity
    return result


def load_enka_rarities(
    cache_path: Path, fetch: Callable[[str], Any] = fetch_json
) -> tuple[dict[str, int], dict[str, int]]:
    """Return `(character_rarity_map, weapon_rarity_map)`, both `id (str) -> rarity (int)`.

    Fetches and distills Enka's `store/gi/avatars.json` and `store/gi/weapons.json`,
    caching only the distilled maps at `cache_path`. Reuses the cache while it is
    younger than `ENKA_RARITY_CACHE_MAX_AGE_SECONDS`; on any fetch/parse error falls
    back to a stale cache if one exists, otherwise to two empty maps.
    """
    cached: tuple[dict[str, int], dict[str, int]] | None = None
    if cache_path.exists():
        try:
            stored = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = (stored.get("characters", {}), stored.get("weapons", {}))
            age_seconds = time.time() - cache_path.stat().st_mtime
            if age_seconds < ENKA_RARITY_CACHE_MAX_AGE_SECONDS:
                return cached
        except (OSError, ValueError, AttributeError):
            cached = None

    try:
        characters = _distill_avatar_rarities(fetch(ENKA_AVATARS_URL))
        weapons = _distill_weapon_rarities(fetch(ENKA_WEAPONS_URL))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return cached if cached is not None else ({}, {})

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"characters": characters, "weapons": weapons}), encoding="utf-8")
    except OSError:
        pass
    return characters, weapons
