"""A synchronous facade over the async `enka` PyPI client."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

# The PyPI package, not this sub-package of the same name. `GenshinClient` comes
# from its defining module rather than the `enka` facade, which re-exports by
# star import without an `__all__` and so reads as a private import.
from enka import errors as enka_errors
from enka.assets.data import PATH_TO_SOURCE
from enka.assets.gi.manager import GI_ASSETS
from enka.clients.gi import GenshinClient

from ..models import LIVE_BUILD_NAME, Build, Profile
from .errors import EnkaError
from .freshness import any_stale
from .http import USER_AGENT
from .parsing import UNKNOWN_WEAPON_NAME, SavedBuildLike, build_from_character
from .profile import Hoyo, is_uid, resolve_genshin_hoyo


def redirect_asset_files(root: Path) -> list[Path]:
    """Move the library's asset files under `root`, returning their new paths.

    The library hardcodes the CWD-relative `.enka_py/assets` and offers no
    setting for it, so the roughly 5 MB it downloads would land wherever the app
    happens to have been started from. Rewriting each asset's `_path` before the
    first client is started is the only way in; `PATH_TO_SOURCE` has to move with
    it, since `_download_json()` looks the download URL up by the (now stale)
    original path and would otherwise raise `KeyError` on a first run with no
    cached files yet.

    The paths come back in `GI_ASSETS._assets` order so that the caller can age
    the cache: the library itself downloads each file once and then keeps it
    forever, so their mtimes are the only record of how old the data is.
    """
    root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for asset in GI_ASSETS._assets:  # pyright: ignore[reportPrivateUsage]
        old_path = asset._path  # pyright: ignore[reportPrivateUsage]
        new_path = root / old_path.name
        PATH_TO_SOURCE[new_path] = PATH_TO_SOURCE[old_path]
        asset._path = new_path  # pyright: ignore[reportPrivateUsage]
        paths.append(new_path)
    return paths


def _create_client() -> GenshinClient:
    return GenshinClient(headers={"User-Agent": USER_AGENT})


async def _fetch_live_builds(client: GenshinClient, uid: str) -> list[Build]:
    """The player's current showcase, which is what "live" means here.

    The saved-builds endpoint also marks entries `live`, but those are whatever
    the user last pressed "refresh" on, which may be arbitrarily old.
    """
    showcase = await client.fetch_showcase(uid)
    return [
        build_from_character(character, build_name=LIVE_BUILD_NAME) for character in showcase.characters
    ]


def _saved_builds(response: Mapping[str, Sequence[SavedBuildLike]]) -> list[Build]:
    """Flatten the saved-builds response, dropping its stale `live` entries."""
    saved = [entry for entries in response.values() for entry in entries if not entry.live]
    saved.sort(key=lambda entry: float(entry.order))
    return [
        build_from_character(entry.character, build_name=entry.name, build_id=str(entry.id)) for entry in saved
    ]


def _live_builds(response: Mapping[str, Sequence[SavedBuildLike]]) -> list[Build]:
    """The `live` entries `_saved_builds()` drops, as a fallback for whichever
    profile a showcase does not cover.

    They are stale relative to a showcase fetch, which is why they are dropped
    whenever a showcase was reachable. A profile whose UID is not public has no
    showcase to fetch, and one whose UID is public may still have an empty
    showcase; either way, these are the only live data available.

    Their own `name` is the empty string, so the build name comes from here
    instead. No build id is carried over: `Build.details()` ignores `build_id`,
    as do the paths a build derives, so it already compares identically to a
    showcase build without it, and omitting it keeps a saved-build id out of a
    project file recorded for a live build.
    """
    live = [entry for entries in response.values() for entry in entries if entry.live]
    live.sort(key=lambda entry: float(entry.order))
    return [build_from_character(entry.character, build_name=LIVE_BUILD_NAME) for entry in live]


async def _fetch_build_response(
    client: GenshinClient, username: str, owner_hash: str
) -> Mapping[str, Sequence[SavedBuildLike]]:
    return await client.fetch_builds({"username": username, "hash": owner_hash})


def _merge_builds(live: list[Build], saved: list[Build]) -> dict[str, list[Build]]:
    """One list per character, the live build first and the saved ones in order."""
    builds: dict[str, list[Build]] = {}
    for build in [*live, *saved]:
        builds.setdefault(build.name.casefold(), []).append(build)
    return builds


# The library reads its cached data files without guarding every lookup: a
# profile carrying something they predate, such as a new artifact set, makes
# `_post_process_artifact` subscript `None` rather than report a miss.
STALE_ASSET_ERRORS = (TypeError, KeyError)


async def _fetch_builds(
    client: GenshinClient, uid: str, username: str, owner_hash: str
) -> dict[str, list[Build]]:
    """Every build Enka holds for the profile, as one list per character.

    Kept separate from `_load()` so that a refresh of the library's data files
    can run it a second time against the data it just downloaded.
    """
    showcase: list[Build] = []
    response: Mapping[str, Sequence[SavedBuildLike]] = {}
    if uid:
        showcase = await _fetch_live_builds(client, uid)
    if owner_hash:
        response = await _fetch_build_response(client, username, owner_hash)
    live = showcase or _live_builds(response)
    return _merge_builds(live, _saved_builds(response))


def _describes_unknown_data(builds: dict[str, list[Build]]) -> bool:
    """Whether the library failed to name something, which means its data files
    predate the profile.

    `enka`'s `Character.name` defaults to the empty string and
    `_post_process_character()` returns early without setting it when the
    character data misses, and a weapon whose name does not resolve against the
    text map comes back as `UNKNOWN_WEAPON_NAME`.
    """
    return any(
        not build.name or build.weapon_name == UNKNOWN_WEAPON_NAME
        for entries in builds.values()
        for build in entries
    )


async def _fetch_with_one_refresh(
    client: GenshinClient, uid: str, username: str, owner_hash: str
) -> dict[str, list[Build]]:
    """Fetch, and fetch once more against refreshed data files if the first
    attempt tripped over them or came back naming something they do not describe.

    A refresh is a roughly 5 MB download, so it happens at most once per load: a
    second failure propagates.

    `enka_errors.AssetKeyError` is deliberately part of the retry: it subclasses
    `KeyError`, and it is the library's own report of a data miss, the one it
    raises telling the caller to consider calling `update_assets()`. The network
    and API failures (`enka_errors.EnkaAPIError` and the rest, `OSError`) are
    not retried, since a refresh cannot fix them.
    """
    try:
        builds = await _fetch_builds(client, uid, username, owner_hash)
    except STALE_ASSET_ERRORS:
        builds = None
    if builds is not None and not _describes_unknown_data(builds):
        return builds
    await client.update_assets()
    return await _fetch_builds(client, uid, username, owner_hash)


async def _load(
    identifier: str, uid: str, username: str, owner_hash: str, *, refresh_assets: bool
) -> Profile:
    async with _create_client() as client:
        if refresh_assets:
            # `update_assets()` is the library's only way to re-download the data
            # files it otherwise downloads once, on the first run that finds them
            # missing, and then keeps forever.
            await client.update_assets()
            builds = await _fetch_builds(client, uid, username, owner_hash)
        else:
            builds = await _fetch_with_one_refresh(client, uid, username, owner_hash)
    if not builds:
        raise EnkaError(f"Enka holds no characters for {identifier}.")
    return Profile(
        identifier=identifier,
        uid=uid,
        username=username,
        builds=builds,
        fetched_at=datetime.now(),
    )


class EnkaClient:
    """Loads a profile from Enka, blocking until it is there.

    The GUI already blocks on a profile load behind a wait cursor, so the async
    library is driven through one `asyncio.run()` per call rather than pulling
    an event loop into the application.
    """

    def __init__(self, asset_root: Path) -> None:
        self.asset_root = asset_root
        self._asset_paths: list[Path] = redirect_asset_files(asset_root)

    def load_profile(self, identifier: str) -> Profile:
        identifier = identifier.strip()
        if not identifier:
            raise EnkaError("Enter a Genshin UID or an Enka username.")
        uid, username, owner_hash = self._resolve(identifier)
        try:
            return asyncio.run(
                _load(identifier, uid, username, owner_hash, refresh_assets=any_stale(self._asset_paths))
            )
        except enka_errors.PlayerDoesNotExistError as error:
            raise EnkaError(f"Enka knows no player with the UID {uid or identifier}.") from error
        except enka_errors.WrongUIDFormatError as error:
            raise EnkaError(f"{uid or identifier} is not a valid Genshin UID.") from error
        except enka_errors.RateLimitedError as error:
            raise EnkaError("Enka is rate limiting this app; try again in a minute.") from error
        # `EnkaAPIError` and `EnkaPyError` are two unrelated bases, so both are needed.
        except (enka_errors.EnkaAPIError, enka_errors.EnkaPyError, OSError) as error:
            raise EnkaError(f"Could not load {identifier} from Enka: {error}") from error
        except STALE_ASSET_ERRORS as error:
            raise EnkaError(
                f"Enka's data files do not describe something in {identifier}, "
                "even after refreshing them."
            ) from error

    def _resolve(self, identifier: str) -> tuple[str, str, str]:
        """`(uid, username, owner_hash)` for what the user entered.

        A UID identifies no Enka account, so it yields no saved builds; a
        username may have a private UID, which yields no showcase.
        """
        if is_uid(identifier):
            return identifier, "", ""
        hoyo: Hoyo = resolve_genshin_hoyo(identifier)
        return hoyo.uid, identifier, hoyo.hash
