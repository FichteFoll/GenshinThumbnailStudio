"""Resolving what the user typed into a UID and, where there is one, an Enka account."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from .errors import EnkaError
from .http import fetch_json

# The trailing slash is required: enka.network answers a 308 without it.
HOYOS_URL = "https://enka.network/api/profile/{username}/hoyos/"

# Enka numbers its supported games; Genshin Impact is 0.
GENSHIN_HOYO_TYPE = 0


def _as_mapping(value: object) -> dict[str, Any] | None:
    """Narrow an `Any`-typed JSON value to a plain dict, or `None` if it isn't one.

    The explicit cast is what produces a fully known `dict[str, Any]`; a bare
    `isinstance` check narrows to `dict[Unknown, Unknown]`.
    """
    if not isinstance(value, dict):
        return None
    return cast("dict[str, Any]", value)


def is_uid(text: str) -> bool:
    """Whether the entered text is a UID rather than an Enka username.

    All digits means a UID. A length check belongs in the error message of
    whatever fetches with it, not here.
    """
    return text.strip().isdigit()


@dataclass(frozen=True)
class Hoyo:
    """One Genshin account attached to an Enka profile.

    `uid` is empty when the account's UID is not public, in which case only the
    saved builds can be fetched.
    """

    hash: str
    uid: str = ""


def resolve_genshin_hoyo(username: str, fetch: Callable[[str], Any] = fetch_json) -> Hoyo:
    """The Genshin account of the Enka profile `username`.

    The library offers no way to do this, so it goes over the plain profile
    endpoint. `fetch` is injected so the tests need no network.
    """
    try:
        payload = fetch(HOYOS_URL.format(username=username))
    except (OSError, ValueError) as error:
        raise EnkaError(f"Could not look up the Enka profile {username}: {error}") from error

    hoyos = _as_mapping(payload)
    if hoyos is None:
        raise EnkaError(f"Enka returned no usable profile for {username}.")

    for raw_entry in hoyos.values():
        entry = _as_mapping(raw_entry)
        if entry is None or entry.get("hoyo_type") != GENSHIN_HOYO_TYPE:
            continue
        hoyo_hash = entry.get("hash")
        if not isinstance(hoyo_hash, str) or not hoyo_hash:
            continue
        raw_uid = entry.get("uid") if entry.get("uid_public") else None
        return Hoyo(hash=hoyo_hash, uid=str(raw_uid) if raw_uid else "")

    raise EnkaError(f"The Enka profile {username} has no public Genshin account.")
