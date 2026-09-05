"""How old a cached Enka data file may get before it is downloaded again."""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

# New characters, weapons and artifact sets arrive with a patch every few weeks;
# a week-old copy is never meaningfully wrong, and refreshing it costs a
# download the app would otherwise pay every time it needed the data.
DATA_MAX_AGE_DAYS = 7


def is_fresh(path: Path, max_age_days: float = DATA_MAX_AGE_DAYS) -> bool:
    """Whether `path` exists and is younger than `max_age_days`."""
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return False
    return age < max_age_days * 86400


def any_stale(paths: Iterable[Path]) -> bool:
    """Whether any of `paths` is missing or past the threshold.

    An empty iterable holds nothing stale, so it is `False`.
    """
    return any(not is_fresh(path) for path in paths)
