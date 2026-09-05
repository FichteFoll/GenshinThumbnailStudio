"""Every costume and every weapon a build could be edited to carry.

The build editor needs choices the profile does not offer, so they are read off
Enka's own data files rather than off the profile: `characters.json` and
`text_map.json`, which the `enka` library already downloads into the asset root,
plus `weapons.json`, which it does not and which is fetched from Enka's API-docs
repository and cached beside them.

`load_catalog()` never raises: a catalog built from missing, unreadable or
unfetchable files is empty, and an empty catalog still answers every question
with the build's own skin and weapon, so a failed load costs the user the extra
choices and nothing else. That guarantee is `load_catalog()`'s alone; a
`Catalog` handed data of the wrong shape may still raise when asked.
"""

from __future__ import annotations

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from ..models import Build
from .errors import EnkaError
from .freshness import is_fresh
from .http import download
from .parsing import ENKA_ROOT

# Enka publishes the weapon data in its API-docs repository rather than through
# the API the library speaks, so it is the one file this app fetches itself.
WEAPON_DATA_URL = (
    "https://raw.githubusercontent.com/EnkaNetwork/API-docs/refs/heads/master/store/gi/weapons.json"
)

# `characters.json` names a weapon type, `weapons.json` numbers it.
WEAPON_TYPE_IDS = {
    "WEAPON_SWORD_ONE_HAND": 1,
    "WEAPON_CLAYMORE": 2,
    "WEAPON_BOW": 3,
    "WEAPON_POLE": 4,
    "WEAPON_CATALYST": 5,
}

_WEAPON_DATA_FILE = "weapons.json"


@dataclass(frozen=True)
class SkinOption:
    """One entry of the skin combo: the default art or one costume."""

    label: str
    costume_id: str | None
    art_url: str


@dataclass(frozen=True)
class WeaponOption:
    """One entry of the weapon combo."""

    name: str
    weapon_url: str
    rarity: int


def _default_art_url(side_icon_name: str) -> str:
    """The un-skinned gacha art derived from a character's side icon.

    `/ui/UI_AvatarIcon_Side_Ayaka.png` becomes
    `https://enka.network/ui/UI_Gacha_AvatarImg_Ayaka.png`, which is the same
    derivation the `enka` library performs for `icon.gacha`; the data files hold
    no gacha art path of their own.
    """
    stem = Path(side_icon_name).stem
    return f"{ENKA_ROOT}/ui/{stem.replace('AvatarIcon_Side', 'Gacha_AvatarImg')}.png"


def _costume_label(art_path: str, costume_id: str) -> str:
    """A display label for a costume, derived from its art file name.

    None of Enka's data files carry costume names, so the file name is the only
    human-readable thing there is: `UI_Costume_AyakaCostumeFruhling` yields
    `Fruhling`. This is a label and nothing else; nothing is keyed by it.
    """
    stem = Path(art_path).stem
    remainder = stem.removeprefix("UI_Costume_")
    return remainder.rpartition("Costume")[2] or costume_id


class Catalog:
    """Enka's characters, weapons and English names, ready to be asked for options.

    `names` maps a text-map hash, as a string, to the English name.
    """

    def __init__(self, characters: dict[str, Any], weapons: dict[str, Any], names: dict[str, str]) -> None:
        self.characters = characters
        self.weapons = weapons
        self.names = names

    def _entries_for(self, build: Build) -> list[dict[str, Any]]:
        """The character entries this build could have come from.

        A name identifies a character everywhere except for the Traveler, who has
        one entry per body and element. Those are told apart by the art the build
        carries; when that narrowing matches nothing, because the build's art is
        a costume the data no longer lists, every same-named entry is kept rather
        than none.
        """
        wanted = build.name.casefold()
        if not wanted:
            return []
        matches = [entry for entry in self.characters.values() if self._entry_name(entry).casefold() == wanted]
        if len(matches) <= 1:
            return matches
        narrowed = [entry for entry in matches if build.art_url in self._art_urls(entry)]
        return narrowed or matches

    def _entry_name(self, entry: dict[str, Any]) -> str:
        """The entry's English name, empty when the text map does not resolve it."""
        return self.names.get(str(entry.get("NameTextMapHash", "")), "")

    def _art_urls(self, entry: dict[str, Any]) -> set[str]:
        urls = {_default_art_url(str(entry.get("SideIconName", "")))}
        for costume in self._costumes(entry).values():
            art = costume.get("Art")
            if isinstance(art, str) and art:
                urls.add(f"{ENKA_ROOT}{art}")
        return urls

    @staticmethod
    def _costumes(entry: dict[str, Any]) -> dict[str, Any]:
        costumes = entry.get("Costumes")
        return cast("dict[str, Any]", costumes) if isinstance(costumes, dict) else {}

    def skins(self, build: Build) -> list[SkinOption]:
        """The default art plus every costume, with the build's own skin guaranteed."""
        entries = self._entries_for(build)
        if not entries:
            return [SkinOption("Current", build.costume_id, build.art_url)]

        options = [SkinOption("Default", None, _default_art_url(str(entries[0].get("SideIconName", ""))))]
        # One dict across the matching entries, so the Traveler's shared costumes
        # are offered once; the keys are the ids the options are ordered by.
        costumes = {
            costume_id: costume for entry in entries for costume_id, costume in self._costumes(entry).items()
        }
        for costume_id in sorted(costumes):
            art = costumes[costume_id].get("Art")
            if not isinstance(art, str) or not art:
                continue
            options.append(SkinOption(_costume_label(art, costume_id), costume_id, f"{ENKA_ROOT}{art}"))

        if build.costume_id is not None and build.costume_id not in costumes:
            options.append(SkinOption(build.costume_id, build.costume_id, build.art_url))
        return options

    def weapons_for(self, build: Build) -> list[WeaponOption]:
        """Every weapon of the character's type, with the build's own guaranteed.

        An unknown character offers every weapon rather than none: the popup is
        still usable, it just cannot narrow the list down.
        """
        entries = self._entries_for(build)
        # The first entry that resolves a type, not simply the first entry: the
        # Traveler's leading entries carry no `WeaponType` at all, and reading
        # only `entries[0]` would drop the filter and offer every weapon in the
        # game to the one character this popup exists to serve specially.
        weapon_type = next(
            (
                type_id
                for entry in entries
                if (type_id := WEAPON_TYPE_IDS.get(str(entry.get("WeaponType", "")))) is not None
            ),
            None,
        )

        options: list[WeaponOption] = []
        for entry in self.weapons.values():
            if weapon_type is not None and entry.get("WeaponType") != weapon_type:
                continue
            name = self.names.get(str(entry.get("NameTextMapHash", "")))
            icon = entry.get("AwakenIcon") or entry.get("Icon")
            if not name or not isinstance(icon, str) or not icon:
                continue
            options.append(WeaponOption(name, f"{ENKA_ROOT}{icon}", int(entry.get("Rarity", 0))))
        options.sort(key=lambda option: (-option.rarity, option.name))

        if all(option.name != build.weapon_name for option in options):
            options.insert(0, WeaponOption(build.weapon_name, build.weapon_url, build.weapon_rarity or 0))
        return options

    def element_is_variable(self, build: Build) -> bool:
        """Whether this character's element is the user's to pick.

        Only the Traveler's is: they are the one character whose entries disagree
        about `Element`, because the game decides it by resonance. For everyone
        else the source data is right and the control stays disabled.
        """
        elements = {str(entry.get("Element", "")) for entry in self._entries_for(build)}
        return len(elements) > 1


def _read_mapping(path: Path) -> dict[str, Any]:
    """The JSON object at `path`, or an empty one if it is missing or broken."""
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cast("dict[str, Any]", payload) if isinstance(payload, dict) else {}


def _load_weapons(path: Path) -> dict[str, Any]:
    """The cached weapon data, refreshed once it is missing or older than
    `DATA_MAX_AGE_DAYS`.

    The download lands beside the cache entry and is renamed onto it only once it
    parses, the way `assets.py` publishes an image, so a failed or truncated
    refresh leaves the previous copy usable instead of destroying it.
    """
    if is_fresh(path):
        return _read_mapping(path)

    incoming = path.with_suffix(path.suffix + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        download(WEAPON_DATA_URL, incoming)
        weapons = _read_mapping(incoming)
        if not weapons:
            raise EnkaError(f"{WEAPON_DATA_URL} did not return weapon data.")
        os.replace(incoming, path)
    # Broad on purpose, and it covers the rename as well: this function must not
    # raise, and `download()` only converts `URLError` and `OSError` into
    # `EnkaError`, so an `http.client.HTTPException` from a truncated response
    # would otherwise escape it and leave its partial file behind.
    except Exception:
        incoming.unlink(missing_ok=True)
        return _read_mapping(path)
    return weapons


def load_catalog(asset_root: Path) -> Catalog:
    """Build a `Catalog` from the files under `asset_root`, never raising.

    `characters.json` and `text_map.json` are the `enka` library's own downloads,
    already there by the time a profile has been loaded; `weapons.json` is this
    app's and is refreshed at most every `DATA_MAX_AGE_DAYS`.
    """
    characters = _read_mapping(asset_root / "characters.json")
    text_map = _read_mapping(asset_root / "text_map.json")
    english = text_map.get("en")
    english = cast("dict[str, Any]", english) if isinstance(english, dict) else {}
    names = {str(key): str(value) for key, value in english.items()}
    return Catalog(characters, _load_weapons(asset_root / _WEAPON_DATA_FILE), names)


def invalidate_weapon_data(asset_root: Path) -> None:
    """Drop the cached weapon catalog so the next load re-fetches it.

    `_load_weapons()` already treats a missing file as stale, so removing it is
    the whole operation. A cache drop is never a failure, so an `OSError` from a
    file that cannot be removed is swallowed: the worst case is a stale catalog.
    """
    with contextlib.suppress(OSError):
        (asset_root / _WEAPON_DATA_FILE).unlink(missing_ok=True)
