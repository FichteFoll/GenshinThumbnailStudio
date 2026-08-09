"""Tests for `enka.assets.download_assets()`."""

from pathlib import Path

import pytest
from PIL import Image

import genshin_thumbnail_studio.enka.assets as assets
from genshin_thumbnail_studio.models import Asset

from .helpers import make_build


def test_download_assets_keys_by_build_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(url: str, destination: Path) -> None:
        if "weapon" in url:
            image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        else:
            image = Image.new("RGBA", (800, 600), (10, 20, 30, 255))
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination)

    monkeypatch.setattr(assets, "download", fake_download)

    builds = [make_build("Alpha"), make_build("Alpha", "Bow DPS"), make_build("Beta")]
    received: list[tuple[str, str]] = []

    def on_asset(key: str, asset: Asset) -> None:
        received.append((key, asset.build.name))

    downloaded = assets.download_assets(builds, tmp_path, on_asset=on_asset)

    assert received == [("alpha|live", "Alpha"), ("alpha|bow dps", "Alpha"), ("beta|live", "Beta")]
    assert set(downloaded) == {"alpha|live", "alpha|bow dps", "beta|live"}
    assert downloaded["alpha|bow dps"].build.build_name == "Bow DPS"
