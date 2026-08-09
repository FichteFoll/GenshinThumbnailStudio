"""Downloading and validating character art and weapon icons into a local cache."""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import partial
from pathlib import Path

from PIL import Image

from ..models import Build
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
    on_build: Callable[[Build], None] | None = None,
) -> None:
    """Fetch every build's art and weapon icon into the cache under `root`.

    Nothing is returned and nothing is keyed: where each file belongs is the
    build's own answer (`Build.art_path()` and `Build.weapon_path()`), so a
    download's only job is to put it there and a caller that wants a file only
    has to ask the build for its path. `on_build` fires once both of a build's
    files have been published, which is when a slot framed with it stops being
    a placeholder.
    """
    for index, build in enumerate(builds, start=1):
        if progress:
            progress(index, len(builds), build.name)
        _publish(build.art_url, build.art_path(root), partial(_validate_art, build=build))
        _publish(build.weapon_url, build.weapon_path(root), partial(_validate_weapon, build=build))
        if on_build:
            on_build(build)
