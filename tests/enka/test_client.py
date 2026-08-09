"""Tests for `enka.client`, with every network step replaced."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType
from typing import Any

import pytest
from enka.errors import PlayerDoesNotExistError  # pyright: ignore[reportMissingTypeStubs]

from genshin_thumbnail_studio.enka import client as client_module
from genshin_thumbnail_studio.enka.errors import EnkaError
from genshin_thumbnail_studio.enka.profile import Hoyo

from .helpers import StubCharacter, StubSavedBuild, constellations, make_build


class FakeGenshinClient:
    """Stands in for `enka.GenshinClient`, which would load assets over the network."""

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
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_create_client", lambda: FakeGenshinClient())


def enka_client(tmp_path: Path) -> client_module.EnkaClient:
    return client_module.EnkaClient(tmp_path / "assets")


def test_load_profile_by_uid_puts_the_live_build_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_live(_client: Any, uid: str) -> list[Any]:
        assert uid == "700468559"
        return [make_build("Bennett"), make_build("Amber")]

    async def fake_saved(*_args: Any) -> list[Any]:
        raise AssertionError("a UID identifier must not take the saved-builds path")

    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)
    monkeypatch.setattr(client_module, "_fetch_saved_builds", fake_saved)

    profile = enka_client(tmp_path).load_profile("700468559")

    assert profile.uid == "700468559"
    assert profile.username == ""
    assert profile.identifier == "700468559"
    assert sorted(profile.builds) == ["amber", "bennett"]
    assert [build.build_name for build in profile.builds["bennett"]] == ["Live"]


def test_load_profile_by_username_merges_live_before_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_live(_client: Any, _uid: str) -> list[Any]:
        return [make_build("Amber")]

    async def fake_saved(_client: Any, username: str, owner_hash: str) -> list[Any]:
        assert (username, owner_hash) == ("Algoinde", "4Rgtre")
        return [make_build("Amber", "Bow DPS"), make_build("Amber", "Support"), make_build("Bennett", "Healer")]

    def fake_resolve(_identifier: str) -> Hoyo:
        return Hoyo(hash="4Rgtre", uid="700468559")

    monkeypatch.setattr(client_module, "resolve_genshin_hoyo", fake_resolve)
    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)
    monkeypatch.setattr(client_module, "_fetch_saved_builds", fake_saved)

    profile = enka_client(tmp_path).load_profile("Algoinde")

    assert profile.uid == "700468559"
    assert profile.username == "Algoinde"
    assert [build.build_name for build in profile.builds["amber"]] == ["Live", "Bow DPS", "Support"]
    assert [build.build_name for build in profile.builds["bennett"]] == ["Healer"]


def test_load_profile_without_a_public_uid_offers_only_saved_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_live(*_args: Any) -> list[Any]:
        raise AssertionError("there is no UID to fetch a showcase for")

    async def fake_saved(*_args: Any) -> list[Any]:
        return [make_build("Amber", "Bow DPS")]

    def fake_resolve(_identifier: str) -> Hoyo:
        return Hoyo(hash="4Rgtre", uid="")

    monkeypatch.setattr(client_module, "resolve_genshin_hoyo", fake_resolve)
    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)
    monkeypatch.setattr(client_module, "_fetch_saved_builds", fake_saved)

    profile = enka_client(tmp_path).load_profile("Algoinde")

    assert profile.uid == ""
    assert [build.build_name for build in profile.builds["amber"]] == ["Bow DPS"]


def test_load_profile_raises_when_nothing_was_returned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_live(*_args: Any) -> list[Any]:
        return []

    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    with pytest.raises(EnkaError):
        enka_client(tmp_path).load_profile("700468559")


def test_load_profile_wraps_a_library_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_live(*_args: Any) -> list[Any]:
        raise PlayerDoesNotExistError

    monkeypatch.setattr(client_module, "_fetch_live_builds", fake_live)

    with pytest.raises(EnkaError, match="700468559"):
        enka_client(tmp_path).load_profile("700468559")


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
