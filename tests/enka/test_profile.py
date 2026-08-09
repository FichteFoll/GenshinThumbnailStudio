"""Tests for `enka.profile`, with the HTTP fetch injected."""

from typing import Any

import pytest

from genshin_thumbnail_studio.enka import profile
from genshin_thumbnail_studio.enka.errors import EnkaError


@pytest.mark.parametrize(
    ("text", "expected"),
    [("700468559", True), ("Algoinde", False), (" 700468559 ", True), ("user123", False), ("", False)],
)
def test_is_uid_accepts_only_digits(text: str, expected: bool) -> None:
    assert profile.is_uid(text) is expected


def hoyos_payload(uid_public: bool = True) -> dict[str, Any]:
    genshin: dict[str, Any] = {"hoyo_type": 0, "hash": "4Rgtre", "uid_public": uid_public, "public": True}
    if uid_public:
        genshin["uid"] = 700468559
    return {"aBcDeF": {"hoyo_type": 3, "hash": "aBcDeF", "uid_public": True, "uid": 111}, "4Rgtre": genshin}


def test_resolve_genshin_hoyo_picks_the_genshin_account() -> None:
    requested: list[str] = []

    def fetch(url: str) -> Any:
        requested.append(url)
        return hoyos_payload()

    hoyo = profile.resolve_genshin_hoyo("Algoinde", fetch=fetch)

    assert hoyo.hash == "4Rgtre"
    assert hoyo.uid == "700468559"
    # Enka answers a 308 without the trailing slash.
    assert requested == ["https://enka.network/api/profile/Algoinde/hoyos/"]


def test_resolve_genshin_hoyo_leaves_a_private_uid_empty() -> None:
    hoyo = profile.resolve_genshin_hoyo("Algoinde", fetch=lambda _: hoyos_payload(uid_public=False))

    assert hoyo.hash == "4Rgtre"
    assert hoyo.uid == ""


def test_resolve_genshin_hoyo_raises_without_a_genshin_account() -> None:
    payload = {"aBcDeF": {"hoyo_type": 3, "hash": "aBcDeF", "uid_public": True, "uid": 111}}

    with pytest.raises(EnkaError, match="Genshin"):
        profile.resolve_genshin_hoyo("Algoinde", fetch=lambda _: payload)


def test_resolve_genshin_hoyo_raises_on_an_unexpected_payload() -> None:
    with pytest.raises(EnkaError):
        profile.resolve_genshin_hoyo("Algoinde", fetch=lambda _: ["not", "a", "mapping"])


def test_resolve_genshin_hoyo_raises_when_the_fetch_fails() -> None:
    def fetch(_: str) -> Any:
        raise OSError("404")

    with pytest.raises(EnkaError, match="Algoinde"):
        profile.resolve_genshin_hoyo("Algoinde", fetch=fetch)
