"""Downloading and validating character art and weapon icons into a local cache."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PIL import Image

from ..models import Asset, Build
from .errors import EnkaError
from .http import download


def _validate_art(path: Path, build: Build) -> None:
    try:
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, ValueError) as error:
        raise EnkaError(f"Downloaded image validation failed for {build.name}.") from error
    if width < 700 or height < 500:
        raise EnkaError(f"Enka returned no full character art for {build.name}.")


def _validate_weapon(path: Path, build: Build) -> None:
    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, ValueError) as error:
        raise EnkaError(f"Downloaded image validation failed for {build.name}.") from error


def _publish(url: str, destination: Path, validate: Callable[[Path], None]) -> None:
    """Download `url` and put it at `destination`, but only once it validates.

    The download lands on a temp file beside its destination and is renamed onto
    it only after validation, so that a file existing at the path a build
    derives means the file is complete and usable. A failure removes the temp
    file and leaves whatever was cached before untouched.
    """
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = destination.with_suffix(destination.suffix + ".part")
    try:
        download(url, incoming)
        validate(incoming)
    except Exception:
        incoming.unlink(missing_ok=True)
        raise
    os.replace(incoming, destination)


def download_assets(
    builds: list[Build],
    root: Path,
    progress: Callable[[int, int, str], None] | None = None,
    on_asset: Callable[[str, Asset], None] | None = None,
) -> dict[str, Asset]:
    """Fetch every build's art into the cache under `root`, keyed by `Build.key`.

    Where each file belongs is the build's own answer (`Build.art_path()` and
    `Build.weapon_path()`), so a download's only job is to put it there.
    """
    assets: dict[str, Asset] = {}
    for index, build in enumerate(builds, start=1):
        if progress:
            progress(index, len(builds), build.name)
        art = build.art_path(root)
        weapon = build.weapon_path(root)
        _publish(build.art_url, art, partial(_validate_art, build=build))
        _publish(build.weapon_url, weapon, partial(_validate_weapon, build=build))
        assets[build.key] = Asset(build=build, art_path=art, weapon_path=weapon)
        if on_asset:
            on_asset(build.key, assets[build.key])
    return assets
