"""Turning Akasha's raw JSON payloads into `Build`s.

`exact_art_url()` reconstructs the exact Enka asset stem (including
costume/skin IDs) from the Akasha character icon URL; it is the part most
likely to break if Akasha or Enka change their asset naming.
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from ..models import Build
from .errors import AkashaError

ENKA_ROOT = "https://enka.network/ui"

KNOWN_ELEMENTS = frozenset({"Anemo", "Geo", "Electro", "Dendro", "Hydro", "Pyro", "Cryo"})


def as_mapping(value: object) -> dict[str, Any] | None:
    """Narrow an `Any`-typed JSON value to a plain dict, or `None` if it isn't one.

    A plain `isinstance(value, dict)` check narrows to `dict[Unknown, Unknown]`
    even when the caller re-annotates the result, since pyright's assignment
    narrowing prefers the isinstance-derived type over a wider declared one;
    the explicit `cast` here is what actually produces a fully known `dict[str, Any]`.
    """
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def timestamp(value: Any) -> datetime:
    if value in (None, ""):
        raise AkashaError("Akasha did not return a profile update timestamp.")
    if isinstance(value, (int, float)) or str(value).isdigit():
        number = float(value)
        if number > 100_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def profile_age_minutes(payload: dict[str, Any]) -> tuple[float, datetime]:
    try:
        last = timestamp(payload["data"]["account"]["lastProfileUpdate"])
    except (KeyError, TypeError) as error:
        raise AkashaError("Akasha profile metadata is incomplete.") from error
    age = max(0.0, (datetime.now(timezone.utc) - last).total_seconds() / 60)
    return age, last


def refinement(build: dict[str, Any]) -> int:
    weapon = as_mapping(build.get("weapon")) or {}
    weapon_info = as_mapping(weapon.get("weaponInfo")) or {}
    raw = weapon_info.get("refinementLevel", 0)
    raw_as_map = as_mapping(raw)
    if raw_as_map is not None:
        raw = raw_as_map.get("value", 0)
    try:
        return int(raw) + 1
    except (TypeError, ValueError):
        return 1


def exact_art_url(build: dict[str, Any]) -> str:
    icon = str(build.get("icon", ""))
    basename = Path(urllib.parse.urlparse(icon).path).name
    match = re.fullmatch(r"UI_AvatarIcon_(.+)\.(png|webp|jpg|jpeg)", basename, re.IGNORECASE)
    if not match:
        raise AkashaError(f"Unsupported Akasha character icon: {icon or 'missing'}")
    suffix = match.group(1)
    prefix = "UI_Costume" if build.get("costumeId") not in (None, "", 0, "0") else "UI_Gacha_AvatarImg"
    return f"{ENKA_ROOT}/{prefix}_{suffix}.png"


def weapon_url(build: dict[str, Any]) -> str:
    weapon = as_mapping(build.get("weapon")) or {}
    flat = as_mapping(weapon.get("flat")) or {}
    url = weapon.get("icon") or flat.get("icon")
    if not url:
        raise AkashaError(f"Weapon icon is missing for {build.get('name', 'character')}.")
    return str(url)


def character_element(raw: dict[str, Any]) -> str | None:
    metadata = as_mapping(raw.get("characterMetadata"))
    if metadata is None:
        return None
    element = metadata.get("element")
    return element if element in KNOWN_ELEMENTS else None


def weapon_rarity(raw: dict[str, Any], rarity_map: dict[str, int] | None = None) -> int | None:
    weapon = as_mapping(raw.get("weapon"))
    if weapon is None:
        return None
    weapon_id = weapon.get("weaponId")
    if weapon_id is None:
        return None
    weapon_id_str = str(weapon_id)
    if not re.fullmatch(r"\d{5}", weapon_id_str):
        return None
    if rarity_map:
        found = rarity_map.get(weapon_id_str)
        if isinstance(found, int) and 1 <= found <= 5:
            return found
    # Offline fallback: the third digit of a 5-digit weaponId also encodes
    # rarity, verified to agree with Enka's store on every known weapon.
    digit = int(weapon_id_str[2])
    return digit if 1 <= digit <= 5 else None


def character_rarity(raw: dict[str, Any], quality_map: dict[str, int] | None = None) -> int | None:
    if not quality_map:
        return None
    character_id = raw.get("characterId")
    if character_id is None:
        return None
    found = quality_map.get(str(character_id))
    return found if isinstance(found, int) and 1 <= found <= 5 else None


def parse_builds(
    payload: dict[str, Any],
    character_rarity_map: dict[str, int] | None = None,
    weapon_rarity_map: dict[str, int] | None = None,
) -> list[Build]:
    data = payload.get("data")
    if not isinstance(data, list):
        raise AkashaError("Akasha did not return a build list.")
    raw_builds = cast("list[Any]", data)
    newest: dict[str, dict[str, Any]] = {}
    for raw in raw_builds:
        raw_dict = as_mapping(raw)
        if raw_dict is None:
            continue
        name = str(raw_dict.get("name", "")).strip()
        if not name:
            continue
        key = name.casefold()
        old = newest.get(key)
        if old is None or int(raw_dict.get("lastBuildUpdate") or 0) > int(old.get("lastBuildUpdate") or 0):
            newest[key] = raw_dict

    result: list[Build] = []
    for raw in newest.values():
        weapon = as_mapping(raw.get("weapon")) or {}
        costume = raw.get("costumeId")
        result.append(
            Build(
                name=str(raw["name"]),
                constellation=int(raw.get("constellation") or 0),
                refinement=refinement(raw),
                weapon_name=str(weapon.get("name") or "Unknown weapon"),
                costume_id=None if costume in (None, "", 0, "0") else str(costume),
                build_id=str(raw.get("_id") or ""),
                build_md5=str(raw.get("md5") or ""),
                last_build_update=str(raw.get("lastBuildUpdate") or "") or None,
                art_url=exact_art_url(raw),
                weapon_url=weapon_url(raw),
                element=character_element(raw),
                rarity=character_rarity(raw, character_rarity_map),
                weapon_rarity=weapon_rarity(raw, weapon_rarity_map),
                raw=raw,
            )
        )
    return sorted(result, key=lambda item: item.name.casefold())
