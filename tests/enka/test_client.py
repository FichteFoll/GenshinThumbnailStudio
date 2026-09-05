"""Tests for `enka.client`, with every network step replaced."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from types import TracebackType
from typing import Any

import pytest
from enka.errors import PlayerDoesNotExistError

from genshin_thumbnail_studio.enka import client as client_module
from genshin_thumbnail_studio.enka.errors import EnkaError
from genshin_thumbnail_studio.enka.parsing import UNKNOWN_WEAPON_NAME
from genshin_thumbnail_studio.enka.profile import Hoyo

from .helpers import StubCharacter, StubSavedBuild, constellations, make_build


class FakeGenshinClient:
    """Stands in for `enka.GenshinClient`, which would load assets over the network."""

    def __init__(self) -> None:
        self.builds: Mapping[str, Sequence[StubSavedBuild]] = {}
        self.builds_params: Mapping[str, str] | None = None
        self.update_calls = 0

    async def update_assets(self) -> None:
        self.update_calls += 1

    async def fetch_builds(self, params: Mapping[str, str]) -> Mapping[str, Sequence[StubSavedBuild]]:
        self.builds_params = params
        return self.builds

    async def __aenter__(self) -> FakeGenshinClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeGenshinClient:
    client = FakeGenshinClient()
    monkeypatch.setattr(client_module, "_create_client", lambda: client)
    return client


def enka_client(tmp_path: Path) -> client_module.EnkaClient:
    return client_module.EnkaClient(tmp_path / "assets")


def test_load_profile_by_uid_puts_the_live_build_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    async def fake_live(_client: Any, uid: str) -> list[Any]:
        assert uid == "700468559"
        return [make_build("Bennett"), make_build("Amber")]

    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    profile = enka_client(tmp_path).load_profile("700468559")

    assert fake_client.builds_params is None, "a UID identifier must not take the builds-endpoint path"
    assert profile.uid == "700468559"
    assert profile.username == ""
    assert profile.identifier == "700468559"
    assert sorted(profile.builds) == ["amber", "bennett"]
    assert [build.build_name for build in profile.builds["bennett"]] == ["Live"]


def test_load_profile_by_username_merges_live_before_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    async def fake_live(_client: Any, _uid: str) -> list[Any]:
        return [make_build("Amber")]

    def fake_resolve(_identifier: str) -> Hoyo:
        return Hoyo(hash="4Rgtre", uid="700468559")

    fake_client.builds = {
        "10000021": [saved_build("Bow DPS", "1"), saved_build("Support", "2")],
        "10000032": [saved_build("Healer", "3", character="Bennett")],
    }
    monkeypatch.setattr(client_module, "resolve_genshin_hoyo", fake_resolve)
    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    profile = enka_client(tmp_path).load_profile("Algoinde")

    assert fake_client.builds_params == {"username": "Algoinde", "hash": "4Rgtre"}
    assert profile.uid == "700468559"
    assert profile.username == "Algoinde"
    assert [build.build_name for build in profile.builds["amber"]] == ["Live", "Bow DPS", "Support"]
    assert [build.build_name for build in profile.builds["bennett"]] == ["Healer"]


def test_load_profile_without_a_public_uid_takes_the_endpoints_live_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """R1: a profile with a private UID has no showcase, so the builds endpoint's
    own `live` entries are the only live data there is."""

    async def fake_live(*_args: Any) -> list[Any]:
        raise AssertionError("there is no UID to fetch a showcase for")

    def fake_resolve(_identifier: str) -> Hoyo:
        return Hoyo(hash="4Rgtre", uid="")

    fake_client.builds = {"10000021": [saved_build("Bow DPS", "1"), saved_build("", "-22.0", live=True)]}
    monkeypatch.setattr(client_module, "resolve_genshin_hoyo", fake_resolve)
    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    profile = enka_client(tmp_path).load_profile("Algoinde")

    assert profile.uid == ""
    assert [build.build_name for build in profile.builds["amber"]] == ["Live", "Bow DPS"]


def test_load_profile_with_a_public_uid_and_an_empty_showcase_takes_the_endpoints_live_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """A public UID whose showcase happens to hold no characters falls back to
    the builds endpoint's `live` entries, same as a private UID would."""

    async def fake_live(_client: Any, _uid: str) -> list[Any]:
        return []

    def fake_resolve(_identifier: str) -> Hoyo:
        return Hoyo(hash="4Rgtre", uid="700468559")

    fake_client.builds = {"10000021": [saved_build("Bow DPS", "1"), saved_build("", "-22.0", live=True)]}
    monkeypatch.setattr(client_module, "resolve_genshin_hoyo", fake_resolve)
    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    profile = enka_client(tmp_path).load_profile("Algoinde")

    assert profile.uid == "700468559"
    assert [build.build_name for build in profile.builds["amber"]] == ["Live", "Bow DPS"]


def test_load_profile_with_a_public_uid_prefers_the_showcase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """The showcase is the current live data, so the endpoint's stale `live`
    entry must not be offered a second time beside it."""

    async def fake_live(_client: Any, _uid: str) -> list[Any]:
        return [make_build("Amber")]

    def fake_resolve(_identifier: str) -> Hoyo:
        return Hoyo(hash="4Rgtre", uid="700468559")

    fake_client.builds = {"10000021": [saved_build("Bow DPS", "1"), saved_build("", "-22.0", live=True)]}
    monkeypatch.setattr(client_module, "resolve_genshin_hoyo", fake_resolve)
    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    profile = enka_client(tmp_path).load_profile("Algoinde")

    amber = profile.builds["amber"]
    assert [build.build_name for build in amber] == ["Live", "Bow DPS"]
    assert amber[0].art_url == "https://example.invalid/Amber-art.png", "the showcase build, not the endpoint's"


def test_load_profile_raises_when_nothing_was_returned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_live(*_args: Any) -> list[Any]:
        return []

    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    with pytest.raises(EnkaError):
        enka_client(tmp_path).load_profile("700468559")


def test_load_profile_wraps_a_library_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """An API failure is not a stale-data failure, so refreshing the data files
    cannot fix it and the load must not pay for one."""

    async def fake_live(*_args: Any) -> list[Any]:
        raise PlayerDoesNotExistError

    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)
    client = freshly_cached_client(tmp_path)

    with pytest.raises(EnkaError, match="700468559"):
        client.load_profile("700468559")

    assert fake_client.update_calls == 0


def saved_build(name: str, order: str, live: bool = False, character: str = "Amber") -> StubSavedBuild:
    return StubSavedBuild(
        id=len(name),
        name=name,
        order=order,
        live=live,
        character=StubCharacter(name=character, constellations=constellations(1)),
    )


def test_saved_builds_drops_live_entries_and_sorts_by_order() -> None:
    response = {
        "10000021": [
            saved_build("Second", "20"),
            saved_build("Snapshot", "5", live=True),
            saved_build("First", "3.5"),
        ]
    }

    builds = client_module._saved_builds(response)

    assert [build.build_name for build in builds] == ["First", "Second"]
    assert [build.name for build in builds] == ["Amber", "Amber"]
    assert builds[0].build_id == "5"


def test_live_builds_keeps_only_live_entries_sorted_by_order() -> None:
    """The real payload names its live entries with the empty string, so the
    `"Live"` name has to come from this app rather than from the entry."""
    response = {
        "10000021": [
            saved_build("", "-5.0000000000", live=True),
            saved_build("Saved", "3.5"),
            saved_build("", "-22.0000000000", live=True, character="Bennett"),
        ]
    }

    builds = client_module._live_builds(response)

    assert [build.name for build in builds] == ["Bennett", "Amber"]
    assert [build.build_name for build in builds] == ["Live", "Live"]
    assert [build.build_id for build in builds] == ["", ""]


def test_load_profile_refreshes_the_data_files_when_none_are_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """The library downloads its data files once and keeps them forever, so an
    asset root with nothing in it is as stale as one that predates a patch."""

    async def fake_live(_client: Any, _uid: str) -> list[Any]:
        return [make_build("Amber")]

    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    enka_client(tmp_path).load_profile("700468559")

    assert fake_client.update_calls == 1


def test_load_profile_does_not_refresh_freshly_cached_data_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    async def fake_live(_client: Any, _uid: str) -> list[Any]:
        return [make_build("Amber")]

    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)
    client = enka_client(tmp_path)
    for path in client._asset_paths:  # pyright: ignore[reportPrivateUsage]
        path.write_text("{}", encoding="utf-8")

    client.load_profile("700468559")

    assert fake_client.update_calls == 0


def test_redirect_asset_files_returns_the_paths_it_assigned(tmp_path: Path) -> None:
    root = tmp_path / "assets"

    paths = client_module.redirect_asset_files(root)

    assert paths == [
        asset._path  # pyright: ignore[reportPrivateUsage]
        for asset in client_module.GI_ASSETS._assets  # pyright: ignore[reportPrivateUsage]
    ]
    assert paths, "the library has data files to age"


def test_redirect_asset_files_keeps_the_download_urls_reachable(tmp_path: Path) -> None:
    """The library looks a download URL up by the asset's path, so a redirect
    that moves the path without moving the mapping breaks the first run, when
    nothing is cached yet and every asset still has to be downloaded."""
    root = tmp_path / "assets"

    client_module.redirect_asset_files(root)

    for asset in client_module.GI_ASSETS._assets:  # pyright: ignore[reportPrivateUsage]
        path = asset._path  # pyright: ignore[reportPrivateUsage]
        assert path.parent == root
        assert path in client_module.PATH_TO_SOURCE


FetchLiveBuilds = Callable[[Any, str], Coroutine[Any, Any, list[Any]]]


def sequenced_live_builds(*outcomes: list[Any] | BaseException) -> FetchLiveBuilds:
    """A `_fetch_live_builds` stand-in spelling one outcome per fetch, so that a
    test can say what the retry sees that the first attempt did not."""
    remaining = list(outcomes)

    async def fake_live(_client: Any, _uid: str) -> list[Any]:
        outcome = remaining.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fake_live


def freshly_cached_client(tmp_path: Path) -> client_module.EnkaClient:
    """A client whose data files are all young enough that the TTL alone would
    never refresh them, so a refresh in a test can only come from the retry."""
    client = enka_client(tmp_path)
    for path in client._asset_paths:  # pyright: ignore[reportPrivateUsage]
        path.write_text("{}", encoding="utf-8")
    return client


def test_load_profile_refreshes_and_retries_when_the_library_trips_over_its_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """R2: data files that predate the profile's artifact set make the library
    subscript `None` (`'NoneType' object is not subscriptable`) instead of
    reporting the miss, so the load has to refresh them and fetch again."""
    monkeypatch.setattr(
        client_module,
        "_fetch_live_builds",
        sequenced_live_builds(
            TypeError("'NoneType' object is not subscriptable"), [make_build("Amber")]
        ),
    )

    profile = freshly_cached_client(tmp_path).load_profile("700468559")

    assert sorted(profile.builds) == ["amber"]
    assert fake_client.update_calls == 1


def test_load_profile_refreshes_when_a_character_is_unnamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """R4: a character the cached data does not describe comes back nameless
    rather than as an error."""
    monkeypatch.setattr(
        client_module,
        "_fetch_live_builds",
        sequenced_live_builds([make_build("")], [make_build("Escoffier")]),
    )

    profile = freshly_cached_client(tmp_path).load_profile("700468559")

    assert sorted(profile.builds) == ["escoffier"]
    assert fake_client.update_calls == 1


def test_load_profile_refreshes_when_a_weapon_is_unnamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """R4: a weapon missing from the text map resolves to `UNKNOWN_WEAPON_NAME`."""
    monkeypatch.setattr(
        client_module,
        "_fetch_live_builds",
        sequenced_live_builds(
            [replace(make_build("Amber"), weapon_name=UNKNOWN_WEAPON_NAME)],
            [make_build("Amber")],
        ),
    )

    profile = freshly_cached_client(tmp_path).load_profile("700468559")

    assert [build.weapon_name for build in profile.builds["amber"]] == ["Weapon"]
    assert fake_client.update_calls == 1


def test_load_profile_refreshes_at_most_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """A refresh is a roughly 5 MB download, so a second failure is reported
    rather than retried, and as this package's own error type."""
    error = TypeError("'NoneType' object is not subscriptable")
    monkeypatch.setattr(client_module, "_fetch_live_builds", sequenced_live_builds(error, error))
    client = freshly_cached_client(tmp_path)

    with pytest.raises(EnkaError, match="700468559") as raised:
        client.load_profile("700468559")

    assert raised.value.__cause__ is error
    assert fake_client.update_calls == 1


def test_load_profile_drops_the_weapon_catalog_when_it_refreshes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    """`weapons.json` describes the same patch as the library's data files, so a
    refresh that replaces those has to drop it too."""
    monkeypatch.setattr(
        client_module,
        "_fetch_live_builds",
        sequenced_live_builds([make_build("")], [make_build("Escoffier")]),
    )
    client = freshly_cached_client(tmp_path)
    weapons = client.asset_root / "weapons.json"
    weapons.write_text("{}", encoding="utf-8")

    client.load_profile("700468559")

    assert fake_client.update_calls == 1
    assert not weapons.exists()


def test_load_profile_keeps_the_weapon_catalog_when_it_does_not_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_client: FakeGenshinClient
) -> None:
    monkeypatch.setattr(client_module, "_fetch_live_builds", sequenced_live_builds([make_build("Amber")]))
    client = freshly_cached_client(tmp_path)
    weapons = client.asset_root / "weapons.json"
    weapons.write_text("{}", encoding="utf-8")

    client.load_profile("700468559")

    assert fake_client.update_calls == 0
    assert weapons.is_file()
