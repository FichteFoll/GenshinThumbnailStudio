from datetime import datetime, timezone

from genshin_thumbnail_studio.models import Build
from genshin_thumbnail_studio.storage import load_profile_cache, profile_cache_path, save_profile_cache


def make_build(name: str) -> Build:
    return Build(
        name=name,
        constellation=2,
        refinement=1,
        weapon_name="Splendor of Tranquil Waters",
        costume_id=None,
        build_id=f"{name}-build",
        build_md5="0123456789abcdef",
        last_build_update="2026-08-01T12:00:00+00:00",
        art_url=f"https://enka.network/ui/{name}.png",
        weapon_url="https://enka.network/ui/weapon.png",
        element="Hydro",
        rarity=5,
        weapon_rarity=5,
        raw={"name": name, "stats": {"critRate": 0.75}},
    )


def test_profile_cache_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    builds = [make_build("Furina"), make_build("Nahida")]
    last_update = datetime(2026, 8, 3, 10, 30, 15, tzinfo=timezone.utc)

    save_profile_cache("700000001", builds, last_update)
    cached = load_profile_cache("700000001")

    assert cached is not None
    loaded_builds, loaded_last_update = cached
    assert loaded_builds == builds
    assert loaded_last_update == last_update


def test_load_profile_cache_without_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    assert load_profile_cache("700000002") is None


def test_load_profile_cache_with_invalid_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    profile_cache_path("700000003").write_text("{not json", encoding="utf-8")

    assert load_profile_cache("700000003") is None
