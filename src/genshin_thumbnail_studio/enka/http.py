"""Plain `urllib` HTTP helpers shared by the rest of the package."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .errors import EnkaError

# Enka's docs ask API users for a User-Agent that identifies them; nothing here
# has to look like a browser any more.
USER_AGENT = "GenshinThumbnailStudio/0.1 (+https://github.com/)"


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            destination.write_bytes(response.read())
    except (urllib.error.URLError, OSError) as error:
        raise EnkaError(f"Could not download {url}: {error}") from error
