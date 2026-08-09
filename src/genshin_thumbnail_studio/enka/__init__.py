"""All network interaction with Enka Network."""

from __future__ import annotations

# `Build` and `Profile` are re-exported because they are what `load_profile()`
# returns and what `download_assets()` takes, and callers import them from this
# package.
from ..models import Build, Profile
from .assets import download_assets
from .client import EnkaClient, redirect_asset_files
from .errors import EnkaError
from .http import USER_AGENT
from .parsing import (
    UNKNOWN_WEAPON_NAME,
    art_url,
    build_from_character,
    constellation_level,
    element_name,
    weapon_display_name,
)
from .profile import Hoyo, is_uid, resolve_genshin_hoyo

__all__ = [
    "UNKNOWN_WEAPON_NAME",
    "USER_AGENT",
    "Build",
    "EnkaClient",
    "EnkaError",
    "Hoyo",
    "Profile",
    "art_url",
    "build_from_character",
    "constellation_level",
    "download_assets",
    "element_name",
    "is_uid",
    "redirect_asset_files",
    "resolve_genshin_hoyo",
    "weapon_display_name",
]
