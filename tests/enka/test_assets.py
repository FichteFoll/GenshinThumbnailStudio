"""Tests for `enka.assets.download_assets()`."""

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

import genshin_thumbnail_studio.enka.assets as assets
from genshin_thumbnail_studio.enka.errors import EnkaError
from genshin_thumbnail_studio.models import Build

from .helpers import make_build


def image_writer(art_size: tuple[int, int] = (800, 600)) -> Callable[[str, Path], None]:
    """A stand-in for `http.download()` that saves a valid image of its own."""

    def fake_download(url: str, destination: Path) -> None:
        size = (32, 32) if "weapon" in url else art_size
        color = (0, 0, 0, 0) if "weapon" in url else (10, 20, 30, 255)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Explicit format: the destination may be a temp path whose suffix
        # Pillow cannot map to one.
        Image.new("RGBA", size, color).save(destination, format="PNG")

    return fake_download


def files_under(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def test_download_assets_announces_each_build_once_both_its_files_are_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is nothing left to key: the callback hands back the build itself,
    and the build is what a caller asks for the paths."""
    monkeypatch.setattr(assets, "download", image_writer())

    builds = [make_build("Alpha"), make_build("Alpha", "Bow DPS"), make_build("Beta")]
    received: list[Build] = []

    returned = assets.download_assets(builds, tmp_path, on_build=received.append)

    assert returned is None
    assert received == builds
    assert all(
        build.art_path(tmp_path).exists() and build.weapon_path(tmp_path).exists() for build in received
    )


def test_download_assets_publishes_both_files_where_the_build_says_they_belong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assets, "download", image_writer())
    build = make_build("Alpha")

    assets.download_assets([build], tmp_path)

    assert files_under(tmp_path) == sorted([build.art_path(tmp_path), build.weapon_path(tmp_path)])


def test_a_validation_failure_publishes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R4: art too small to use must leave neither a file at its destination nor
    a temp file behind, so that "the file exists" can mean "it is usable"."""
    monkeypatch.setattr(assets, "download", image_writer(art_size=(320, 240)))
    build = make_build("Alpha")

    with pytest.raises(EnkaError):
        assets.download_assets([build], tmp_path)

    assert files_under(tmp_path) == []


def test_a_download_failing_mid_write_leaves_the_earlier_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4: a writer that dies half-way through publishes nothing, and does not
    take the art that was already cached with it."""
    build = make_build("Alpha")
    art = build.art_path(tmp_path)
    art.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (800, 600), (1, 2, 3, 255)).save(art, format="PNG")
    art_bytes = art.read_bytes()

    def failing_download(url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"\x89PNG half a")
        raise EnkaError(f"Could not download {url}: connection reset")

    monkeypatch.setattr(assets, "download", failing_download)

    with pytest.raises(EnkaError):
        assets.download_assets([build], tmp_path)

    assert art.read_bytes() == art_bytes
    assert files_under(tmp_path) == [art]
