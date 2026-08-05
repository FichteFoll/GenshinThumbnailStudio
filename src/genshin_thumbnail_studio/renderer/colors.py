"""Element and rarity color tables, and the accent color a card is drawn with."""

from __future__ import annotations

import re

from ..models import Asset, Placement

ELEMENT_COLORS = {
    "anemo": "#74c2a8",
    "geo": "#ffb84d",
    "electro": "#b08fc9",
    "dendro": "#a5c83b",
    "hydro": "#4cc2f1",
    "pyro": "#ff7b52",
    "cryo": "#9fe7ef",
}

RARITY_COLORS = {
    5: "#ffd95d",
    4: "#c69bff",
    3: "#7ab3e0",
    2: "#79c8a0",
    1: "#c4c8cf",
}


def rarity_color(rarity: int | None) -> str:
    """The in-game rarity accent color, falling back to the 5-star gold
    when the rarity is unknown so the current look stays the default."""
    if rarity is None:
        return RARITY_COLORS[5]
    return RARITY_COLORS.get(rarity, RARITY_COLORS[5])


def hex_to_rgba(value: str, alpha: int) -> tuple[int, int, int, int]:
    raw = value.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raise ValueError(f"Invalid color: {value}")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), alpha)


def card_color(member: Placement, asset: Asset) -> str:
    """The card's element-inspired accent color, falling back to the
    placement's own color when the element is unknown or missing."""
    element = asset.build.element
    if element and element.casefold() in ELEMENT_COLORS:
        return ELEMENT_COLORS[element.casefold()]
    return member.color
