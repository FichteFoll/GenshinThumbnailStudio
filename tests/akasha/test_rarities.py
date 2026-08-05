"""Tests for `akasha.rarities.load_enka_rarities()`."""

import os
import time
import urllib.error
from pathlib import Path
from typing import Any

from genshin_thumbnail_studio.akasha.rarities import load_enka_rarities


def test_load_enka_rarities_distills_and_caches(tmp_path: Path) -> None:
    cache_path = tmp_path / "enka-rarities.json"
    calls: list[str] = []

    def fake_fetch(url: str) -> dict[str, Any]:
        calls.append(url)
        if "avatars" in url:
            return {
                "10000002": {"QualityType": "QUALITY_ORANGE"},
                "10000003": {"QualityType": "QUALITY_PURPLE"},
                "10000004": {"NoQualityType": True},
            }
        return {
            "11512": {"Rarity": 5},
            "14402": {"Rarity": 4},
            "99999": {"Rarity": "not-an-int"},
        }

    characters, weapons = load_enka_rarities(cache_path, fetch=fake_fetch)
    assert characters == {"10000002": 5, "10000003": 4}
    assert weapons == {"11512": 5, "14402": 4}
    assert len(calls) == 2
    assert cache_path.exists()

    # A fresh cache is reused without calling fetch again.
    calls.clear()
    characters_again, weapons_again = load_enka_rarities(cache_path, fetch=fake_fetch)
    assert characters_again == characters
    assert weapons_again == weapons
    assert calls == []


def test_load_enka_rarities_falls_back_to_stale_cache_on_error(tmp_path: Path) -> None:
    cache_path = tmp_path / "enka-rarities.json"
    cache_path.write_text('{"characters": {"1": 5}, "weapons": {"2": 4}}', encoding="utf-8")
    old_time = time.time() - 8 * 24 * 60 * 60
    os.utime(cache_path, (old_time, old_time))

    def failing_fetch(_url: str) -> dict[str, Any]:
        raise urllib.error.URLError("offline")

    characters, weapons = load_enka_rarities(cache_path, fetch=failing_fetch)
    assert characters == {"1": 5}
    assert weapons == {"2": 4}


def test_load_enka_rarities_falls_back_to_empty_maps_without_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "enka-rarities.json"

    def failing_fetch(_url: str) -> dict[str, Any]:
        raise urllib.error.URLError("offline")

    characters, weapons = load_enka_rarities(cache_path, fetch=failing_fetch)
    assert characters == {}
    assert weapons == {}
