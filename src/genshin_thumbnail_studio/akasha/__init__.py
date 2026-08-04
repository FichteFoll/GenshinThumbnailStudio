"""All network and browser interaction with Akasha and Enka."""

from __future__ import annotations

# `Build` and `Asset` are re-exported because they are what `load_profile()` and
# `download_assets()` return, and callers import them from this package today.
from ..models import Asset, Build
from .assets import download_assets
from .client import API_ROOT, AkashaWebClient
from .errors import AkashaError, StaleProfileError
from .http import USER_AGENT
from .parsing import (
    KNOWN_ELEMENTS,
    character_element,
    character_rarity,
    exact_art_url,
    parse_builds,
    profile_age_minutes,
    refinement,
    timestamp,
    weapon_rarity,
    weapon_url,
)
from .rarities import ENKA_RARITY_CACHE_MAX_AGE_SECONDS, load_enka_rarities

__all__ = [
    "API_ROOT",
    "ENKA_RARITY_CACHE_MAX_AGE_SECONDS",
    "KNOWN_ELEMENTS",
    "USER_AGENT",
    "AkashaError",
    "AkashaWebClient",
    "Asset",
    "Build",
    "StaleProfileError",
    "character_element",
    "character_rarity",
    "download_assets",
    "exact_art_url",
    "load_enka_rarities",
    "parse_builds",
    "profile_age_minutes",
    "refinement",
    "timestamp",
    "weapon_rarity",
    "weapon_url",
]
