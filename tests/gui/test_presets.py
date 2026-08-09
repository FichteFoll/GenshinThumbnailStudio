"""Tests for `gui.presets.preset_key()` and `PresetStore`, needing no Qt environment.

Both are Qt-free: they construct no widget and need no display, so these tests run
without `QT_QPA_PLATFORM` being set. (PySide6 still
ends up imported, because reaching `gui.presets` executes the `gui` package's
facade, but nothing here uses it.)
"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from genshin_thumbnail_studio.gui.presets import PresetStore, preset_key
from genshin_thumbnail_studio.models import Asset, Build, Mode, Placement, Project


@dataclass
class StubState:
    """The minimal `EditorState` the store needs."""

    project: Project
    builds: dict[str, list[Build]] = field(default_factory=dict)
    assets: dict[str, Asset] = field(default_factory=dict)
    art_root: Path = Path("assets")


def _build(name: str, costume_id: str | None = None) -> Build:
    return Build(
        name=name,
        constellation=0,
        refinement=1,
        weapon_name="Weapon",
        costume_id=costume_id,
        art_url="https://example.invalid/art.png",
        weapon_url="https://example.invalid/weapon.png",
    )


def _state(mode: Mode = "abyss", builds: list[Build] | None = None) -> StubState:
    return StubState(
        project=Project.blank(mode),
        builds={build.name.casefold(): [build] for build in (builds or [])},
    )


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path))


def test_preset_key_uses_the_costume_id_when_the_build_has_one() -> None:
    state = _state(builds=[_build("Furina", "200301")])

    assert preset_key(state, Placement(name="Furina")) == "abyss|200301"


def test_preset_key_falls_back_to_the_name() -> None:
    state = _state(builds=[_build("Furina")])

    assert preset_key(state, Placement(name="Furina")) == "abyss|furina"
    # No build loaded for this name at all.
    assert preset_key(state, Placement(name="Nahida")) == "abyss|nahida"


def test_preset_key_separates_the_two_modes() -> None:
    build = _build("Furina")
    member = Placement(name="Furina")

    abyss = preset_key(_state("abyss", [build]), member)
    stygian = preset_key(_state("stygian", [build]), member)

    assert abyss != stygian
    assert (abyss, stygian) == ("abyss|furina", "stygian|furina")


def test_remember_then_apply_round_trips_all_four_values() -> None:
    state = _state(builds=[_build("Furina")])
    store = PresetStore({})
    source = Placement(name="Furina", offset_x=0.11, offset_y=-0.07, zoom=1.33, flip=True)

    store.remember(state, source)

    target = Placement(name="Furina")
    store.apply_to(state, target)
    assert target.offset_x == 0.11
    assert target.offset_y == -0.07
    assert target.zoom == 1.33
    assert target.flip is True


def test_remember_ignores_a_member_without_a_name() -> None:
    state = _state()
    store = PresetStore({})

    store.remember(state, Placement(name="", offset_x=0.4))

    assert store.entries == {}


def test_apply_leaves_the_member_untouched_without_a_stored_preset() -> None:
    state = _state(builds=[_build("Furina")])
    store = PresetStore({})
    member = Placement(name="Furina", offset_x=0.11, offset_y=-0.07, zoom=1.33, flip=True)

    store.apply_to(state, member)

    assert (member.offset_x, member.offset_y, member.zoom, member.flip) == (0.11, -0.07, 1.33, True)


def test_load_reads_what_a_previous_store_saved() -> None:
    state = _state(builds=[_build("Furina")])
    PresetStore({}).remember(state, Placement(name="Furina", offset_x=0.25, zoom=1.4, flip=True))

    reloaded = PresetStore.load()

    member = Placement(name="Furina")
    reloaded.apply_to(state, member)
    assert member.offset_x == 0.25
    assert member.zoom == 1.4
    assert member.flip is True
