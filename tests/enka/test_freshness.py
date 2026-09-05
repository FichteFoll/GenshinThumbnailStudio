"""Tests for `enka.freshness`, the one age threshold the cached data files share."""

from __future__ import annotations

import os
import time
from pathlib import Path

from genshin_thumbnail_studio.enka import freshness


def write_aged(path: Path, age_days: float) -> Path:
    path.write_text("{}", encoding="utf-8")
    stamp = time.time() - age_days * 86400
    os.utime(path, (stamp, stamp))
    return path


def test_a_file_written_now_is_fresh(tmp_path: Path) -> None:
    path = tmp_path / "characters.json"
    path.write_text("{}", encoding="utf-8")

    assert freshness.is_fresh(path)


def test_a_file_past_the_threshold_is_not_fresh(tmp_path: Path) -> None:
    path = write_aged(tmp_path / "characters.json", freshness.DATA_MAX_AGE_DAYS + 1)

    assert not freshness.is_fresh(path)


def test_a_missing_file_is_not_fresh(tmp_path: Path) -> None:
    assert not freshness.is_fresh(tmp_path / "absent.json")


def test_any_stale_is_false_for_an_all_fresh_sequence(tmp_path: Path) -> None:
    paths = [write_aged(tmp_path / f"{index}.json", 1) for index in range(3)]

    assert not freshness.any_stale(paths)


def test_any_stale_is_true_when_one_entry_is_stale(tmp_path: Path) -> None:
    paths = [write_aged(tmp_path / f"{index}.json", 1) for index in range(3)]
    paths.append(write_aged(tmp_path / "old.json", freshness.DATA_MAX_AGE_DAYS + 1))

    assert freshness.any_stale(paths)


def test_an_empty_sequence_holds_nothing_stale() -> None:
    assert not freshness.any_stale([])
