"""Downloading and validating character art and weapon icons into a local cache."""

from __future__ import annotations

import hashlib
import re
import urllib.parse
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from ..models import Asset, Build
from .errors import AkashaError
from .http import download


def _asset_path(root: Path, kind: str, build: Build, url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    extension = Path(urllib.parse.urlparse(url).path).suffix.lower()
    if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
        extension = ".png"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", build.name).strip("._") or "asset"
    target = root / kind / f"{safe}-{digest}{extension}"
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def download_assets(
    builds: list[Build],
    root: Path,
    progress: Callable[[int, int, str], None] | None = None,
    on_asset: Callable[[str, Asset], None] | None = None,
) -> dict[str, Asset]:
    assets: dict[str, Asset] = {}
    for index, build in enumerate(builds, start=1):
        if progress:
            progress(index, len(builds), build.name)
        art = _asset_path(root, "characters", build, build.art_url)
        weapon = _asset_path(root, "weapons", build, build.weapon_url)
        if not art.exists():
            download(build.art_url, art)
        if not weapon.exists():
            download(build.weapon_url, weapon)
        try:
            with Image.open(art) as image:
                if image.width < 700 or image.height < 500:
                    raise AkashaError(f"Enka returned no full character art for {build.name}.")
            with Image.open(weapon) as image:
                image.verify()
        except (OSError, ValueError) as error:
            art.unlink(missing_ok=True)
            raise AkashaError(f"Downloaded image validation failed for {build.name}.") from error
        key = build.name.casefold()
        assets[key] = Asset(build=build, art_path=art, weapon_path=weapon)
        if on_asset:
            on_asset(key, assets[key])
    return assets
