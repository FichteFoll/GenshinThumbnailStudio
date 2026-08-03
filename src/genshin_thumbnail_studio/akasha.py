from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile

from .models import Asset, Build


API_ROOT = "https://akasha.cv/api"
ENKA_ROOT = "https://enka.network/ui"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
)

ENKA_AVATARS_URL = "https://raw.githubusercontent.com/EnkaNetwork/API-docs/master/store/gi/avatars.json"
ENKA_WEAPONS_URL = "https://raw.githubusercontent.com/EnkaNetwork/API-docs/master/store/gi/weapons.json"
ENKA_RARITY_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

KNOWN_ELEMENTS = frozenset({"Anemo", "Geo", "Electro", "Dendro", "Hydro", "Pyro", "Cryo"})

QUALITY_TYPE_RARITY = {
    "QUALITY_ORANGE": 5,
    "QUALITY_ORANGE_SP": 5,
    "QUALITY_PURPLE": 4,
    "QUALITY_BLUE": 3,
    "QUALITY_GREEN": 2,
    "QUALITY_WHITE": 1,
}


class AkashaError(RuntimeError):
    pass


class StaleProfileError(AkashaError):
    def __init__(self, age_minutes: float, last_update: datetime) -> None:
        super().__init__(f"Akasha profile is {age_minutes:.0f} minutes old.")
        self.age_minutes = age_minutes
        self.last_update = last_update


def timestamp(value: Any) -> datetime:
    if value in (None, ""):
        raise AkashaError("Akasha did not return a profile update timestamp.")
    if isinstance(value, (int, float)) or str(value).isdigit():
        number = float(value)
        if number > 100_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def profile_age_minutes(payload: dict[str, Any]) -> tuple[float, datetime]:
    try:
        last = timestamp(payload["data"]["account"]["lastProfileUpdate"])
    except (KeyError, TypeError) as error:
        raise AkashaError("Akasha profile metadata is incomplete.") from error
    age = max(0.0, (datetime.now(timezone.utc) - last).total_seconds() / 60)
    return age, last


def refinement(build: dict[str, Any]) -> int:
    raw = build.get("weapon", {}).get("weaponInfo", {}).get("refinementLevel", 0)
    if isinstance(raw, dict):
        raw = raw.get("value", 0)
    try:
        return int(raw) + 1
    except (TypeError, ValueError):
        return 1


def exact_art_url(build: dict[str, Any]) -> str:
    icon = str(build.get("icon", ""))
    basename = Path(urllib.parse.urlparse(icon).path).name
    match = re.fullmatch(r"UI_AvatarIcon_(.+)\.(png|webp|jpg|jpeg)", basename, re.IGNORECASE)
    if not match:
        raise AkashaError(f"Unsupported Akasha character icon: {icon or 'missing'}")
    suffix = match.group(1)
    prefix = "UI_Costume" if build.get("costumeId") not in (None, "", 0, "0") else "UI_Gacha_AvatarImg"
    return f"{ENKA_ROOT}/{prefix}_{suffix}.png"


def weapon_url(build: dict[str, Any]) -> str:
    weapon = build.get("weapon") or {}
    url = weapon.get("icon") or (weapon.get("flat") or {}).get("icon")
    if not url:
        raise AkashaError(f"Weapon icon is missing for {build.get('name', 'character')}.")
    return str(url)


def character_element(raw: dict[str, Any]) -> str | None:
    if not isinstance(raw, dict):
        return None
    metadata = raw.get("characterMetadata")
    if not isinstance(metadata, dict):
        return None
    element = metadata.get("element")
    return element if element in KNOWN_ELEMENTS else None


def weapon_rarity(raw: dict[str, Any], rarity_map: dict[str, int] | None = None) -> int | None:
    if not isinstance(raw, dict):
        return None
    weapon = raw.get("weapon")
    if not isinstance(weapon, dict):
        return None
    weapon_id = weapon.get("weaponId")
    if weapon_id is None:
        return None
    weapon_id_str = str(weapon_id)
    if not re.fullmatch(r"\d{5}", weapon_id_str):
        return None
    if rarity_map:
        found = rarity_map.get(weapon_id_str)
        if isinstance(found, int) and 1 <= found <= 5:
            return found
    # Offline fallback: the third digit of a 5-digit weaponId also encodes
    # rarity, verified to agree with Enka's store on every known weapon.
    digit = int(weapon_id_str[2])
    return digit if 1 <= digit <= 5 else None


def character_rarity(raw: dict[str, Any], quality_map: dict[str, int] | None = None) -> int | None:
    if not quality_map or not isinstance(raw, dict):
        return None
    character_id = raw.get("characterId")
    if character_id is None:
        return None
    found = quality_map.get(str(character_id))
    return found if isinstance(found, int) and 1 <= found <= 5 else None


def _fetch_enka_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _distill_avatar_rarities(payload: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(payload, dict):
        return result
    for character_id, entry in payload.items():
        if isinstance(entry, dict):
            rarity = QUALITY_TYPE_RARITY.get(entry.get("QualityType"))
            if rarity is not None:
                result[str(character_id)] = rarity
    return result


def _distill_weapon_rarities(payload: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    if not isinstance(payload, dict):
        return result
    for weapon_id, entry in payload.items():
        if isinstance(entry, dict):
            rarity = entry.get("Rarity")
            if isinstance(rarity, int) and 1 <= rarity <= 5:
                result[str(weapon_id)] = rarity
    return result


def load_enka_rarities(
    cache_path: Path, fetch: Callable[[str], Any] = _fetch_enka_json
) -> tuple[dict[str, int], dict[str, int]]:
    """Return `(character_rarity_map, weapon_rarity_map)`, both `id (str) -> rarity (int)`.

    Fetches and distills Enka's `store/gi/avatars.json` and `store/gi/weapons.json`,
    caching only the distilled maps at `cache_path`. Reuses the cache while it is
    younger than `ENKA_RARITY_CACHE_MAX_AGE_SECONDS`; on any fetch/parse error falls
    back to a stale cache if one exists, otherwise to two empty maps.
    """
    cached: tuple[dict[str, int], dict[str, int]] | None = None
    if cache_path.exists():
        try:
            stored = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = (stored.get("characters", {}), stored.get("weapons", {}))
            age_seconds = time.time() - cache_path.stat().st_mtime
            if age_seconds < ENKA_RARITY_CACHE_MAX_AGE_SECONDS:
                return cached
        except (OSError, ValueError, AttributeError):
            cached = None

    try:
        characters = _distill_avatar_rarities(fetch(ENKA_AVATARS_URL))
        weapons = _distill_weapon_rarities(fetch(ENKA_WEAPONS_URL))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return cached if cached is not None else ({}, {})

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps({"characters": characters, "weapons": weapons}), encoding="utf-8")
    except OSError:
        pass
    return characters, weapons


def parse_builds(
    payload: dict[str, Any],
    character_rarity_map: dict[str, int] | None = None,
    weapon_rarity_map: dict[str, int] | None = None,
) -> list[Build]:
    raw_builds = payload.get("data")
    if not isinstance(raw_builds, list):
        raise AkashaError("Akasha did not return a build list.")
    newest: dict[str, dict[str, Any]] = {}
    for raw in raw_builds:
        name = str(raw.get("name", "")).strip()
        if not name:
            continue
        key = name.casefold()
        old = newest.get(key)
        if old is None or int(raw.get("lastBuildUpdate") or 0) > int(old.get("lastBuildUpdate") or 0):
            newest[key] = raw

    result = []
    for raw in newest.values():
        weapon = raw.get("weapon") or {}
        costume = raw.get("costumeId")
        result.append(
            Build(
                name=str(raw["name"]),
                constellation=int(raw.get("constellation") or 0),
                refinement=refinement(raw),
                weapon_name=str(weapon.get("name") or "Unknown weapon"),
                costume_id=None if costume in (None, "", 0, "0") else str(costume),
                build_id=str(raw.get("_id") or ""),
                build_md5=str(raw.get("md5") or ""),
                last_build_update=str(raw.get("lastBuildUpdate") or "") or None,
                art_url=exact_art_url(raw),
                weapon_url=weapon_url(raw),
                element=character_element(raw),
                rarity=character_rarity(raw, character_rarity_map),
                weapon_rarity=weapon_rarity(raw, weapon_rarity_map),
                raw=raw,
            )
        )
    return sorted(result, key=lambda item: item.name.casefold())


class AkashaWebClient:
    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self.profile = QWebEngineProfile("GenshinThumbnailStudio")
        self.profile.setCachePath(str(cache_path / "web-cache"))
        self.profile.setPersistentStoragePath(str(cache_path / "web-profile"))
        self.profile.setHttpUserAgent(USER_AGENT)
        self.page = QWebEnginePage(self.profile)

    def _wait_load(self, url: str, timeout_ms: int = 120_000) -> bool:
        loop = QEventLoop()
        result = {"ok": False, "timed_out": False}
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: (result.update(timed_out=True), loop.quit()))

        def finished(ok: bool) -> None:
            result["ok"] = ok
            loop.quit()

        self.page.loadFinished.connect(finished)
        timer.start(timeout_ms)
        self.page.load(QUrl(url))
        loop.exec()
        timer.stop()
        self.page.loadFinished.disconnect(finished)
        if result["timed_out"]:
            raise AkashaError(f"Timeout while loading {url}")
        return bool(result["ok"])

    def _plain_text(self, timeout_ms: int = 30_000) -> str:
        loop = QEventLoop()
        result = {"value": None}
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def ready(value: str) -> None:
            result["value"] = value
            loop.quit()

        timer.start(timeout_ms)
        self.page.toPlainText(ready)
        loop.exec()
        timer.stop()
        if result["value"] is None:
            raise AkashaError("Timeout while reading Akasha response.")
        return str(result["value"])

    def run_javascript(self, script: str, timeout_ms: int = 30_000) -> Any:
        loop = QEventLoop()
        result = {"done": False, "value": None}
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)

        def ready(value: Any) -> None:
            result.update(done=True, value=value)
            loop.quit()

        timer.start(timeout_ms)
        self.page.runJavaScript(script, ready)
        loop.exec()
        timer.stop()
        if not result["done"]:
            raise AkashaError("Timeout while executing browser action.")
        return result["value"]

    def json(self, url: str) -> dict[str, Any]:
        self._wait_load(url)
        text = self._plain_text().strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            title = self.page.title()
            raise AkashaError(f"Akasha returned no JSON ({title or 'unknown page'}).") from error
        if not isinstance(payload, dict):
            raise AkashaError("Akasha returned an unexpected response.")
        if payload.get("error"):
            raise AkashaError(str(payload["error"]))
        return payload

    def load_profile(self, uid: str, max_age_minutes: int = 60, allow_stale: bool = False) -> tuple[list[Build], float, datetime]:
        if not re.fullmatch(r"\d{6,12}", uid):
            raise AkashaError("UID must contain 6 to 12 digits.")
        user = self.json(f"{API_ROOT}/user/{uid}")
        age, last = profile_age_minutes(user)
        if age > max_age_minutes and not allow_stale:
            raise StaleProfileError(age, last)
        query = urllib.parse.urlencode(
            {
                "sort": "critValue",
                "order": "-1",
                "size": "100",
                "page": "1",
                "filter": "",
                "uids": "",
                "p": "",
                "fromId": "",
                "li": "",
                "uid": uid,
            }
        )
        character_rarity_map, weapon_rarity_map = load_enka_rarities(self.cache_path / "enka-rarities.json")
        builds = parse_builds(self.json(f"{API_ROOT}/builds/?{query}"), character_rarity_map, weapon_rarity_map)
        return builds, age, last

    def refresh_profile(self, uid: str, timeout_seconds: int = 90, progress: Callable[[str], None] | None = None) -> bool:
        before = self.json(f"{API_ROOT}/user/{uid}")
        _, old_time = profile_age_minutes(before)
        self._wait_load(f"https://akasha.cv/profile/{uid}")
        deadline = time.monotonic() + 30
        clicked = False
        while time.monotonic() < deadline and not clicked:
            clicked = bool(
                self.run_javascript(
                    "(() => { const e=document.querySelector('[title=\"Refresh builds\"]'); if(!e) return false; e.click(); return true; })()"
                )
            )
            if not clicked:
                QEventLoop().processEvents()
                time.sleep(0.5)
        if not clicked:
            raise AkashaError("Akasha refresh button was not found.")

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if progress:
                progress("Akasha is refreshing the builds ...")
            time.sleep(3)
            try:
                payload = self.json(f"{API_ROOT}/user/{uid}")
                _, current = profile_age_minutes(payload)
                if current > old_time:
                    return True
            except AkashaError:
                pass
        return False


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            destination.write_bytes(response.read())
    except (urllib.error.URLError, OSError) as error:
        raise AkashaError(f"Could not download {url}: {error}") from error


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
            _download(build.art_url, art)
        if not weapon.exists():
            _download(build.weapon_url, weapon)
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
