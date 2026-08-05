from pathlib import Path

import pytest
from PIL import Image

import genshin_thumbnail_studio.akasha.assets as assets
from genshin_thumbnail_studio.models import Asset

from .helpers import make_build


def test_download_assets_calls_on_asset_per_build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_download(url: str, destination: Path) -> None:
        if "weapon" in url:
            image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        else:
            image = Image.new("RGBA", (800, 600), (10, 20, 30, 255))
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination)

    monkeypatch.setattr(assets, "download", fake_download)

    builds = [make_build("Alpha"), make_build("Beta")]
    received: list[tuple[str, str]] = []

    def on_asset(key: str, asset: Asset) -> None:
        received.append((key, asset.build.name))

    downloaded = assets.download_assets(builds, tmp_path, on_asset=on_asset)

    assert received == [("alpha", "Alpha"), ("beta", "Beta")]
    assert set(downloaded) == {"alpha", "beta"}
    assert downloaded["alpha"].build.name == "Alpha"
    assert downloaded["beta"].build.name == "Beta"
