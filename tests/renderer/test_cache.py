"""Tests for `renderer.cache`."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageChops

from genshin_thumbnail_studio.models import Asset, Project
from genshin_thumbnail_studio.renderer import cache as render_cache_module
from genshin_thumbnail_studio.renderer import panels as render_panels_module
from genshin_thumbnail_studio.renderer.cache import clear_render_cache
from genshin_thumbnail_studio.renderer.colors import ELEMENT_COLORS
from genshin_thumbnail_studio.renderer.compose import export_project, render_preview

from .helpers import asset_key, create_assets, fill_project, live_build, two_tone_project


def _render_cache(name: str) -> Any:
    """Fetch one of the renderer's cache dicts by name.

    Their declared type is `OrderedDict[tuple, Image.Image]`: a bare `tuple`
    key that basedpyright treats as partially unknown until renderer.py's own
    cleanup commit (tracked separately from this one). `getattr` reads it as
    `Any` instead of leaking that `reportUnknownMemberType` into this file.
    """
    return getattr(render_cache_module, name)


def _patch_counting_open(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Wrap PIL's Image.open with a call-recording proxy, so a test can
    assert on which paths were (re)opened without mocking away the actual
    decoding (the returned image is still real, from the original open)."""
    opened: list[str] = []
    real_open = Image.open

    def counting_open(fp: Any, *args: Any, **kwargs: Any) -> Image.Image:
        opened.append(str(fp))
        return real_open(fp, *args, **kwargs)

    monkeypatch.setattr(Image, "open", counting_open)
    return opened


def _patch_counting_panels(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Wrap the panel builders with call-recording proxies, so a test can
    assert how many panels were actually composited rather than served from
    the panel cache. Image.open counts cannot show this, since the art and
    weapon-icon caches absorb every decode after the first render.

    render_image() resolves both builders as attributes of the panels module at
    call time, so patching them there takes effect for renders already in
    flight."""
    built: list[str] = []
    real_make_panel = render_panels_module.make_panel
    real_placeholder_panel = render_panels_module.placeholder_panel

    def counting_make_panel(*args: Any, **kwargs: Any) -> Image.Image:
        built.append("make_panel")
        return real_make_panel(*args, **kwargs)

    def counting_placeholder_panel(*args: Any, **kwargs: Any) -> Image.Image:
        built.append("placeholder_panel")
        return real_placeholder_panel(*args, **kwargs)

    monkeypatch.setattr(render_panels_module, "make_panel", counting_make_panel)
    monkeypatch.setattr(render_panels_module, "placeholder_panel", counting_placeholder_panel)
    return built


def test_repeated_render_reuses_panel_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)

    opened = _patch_counting_open(monkeypatch)
    built = _patch_counting_panels(monkeypatch)
    first = render_preview(project, assets)
    assert opened  # sanity: the first render actually opened art/weapon files
    assert len(built) == 8  # cold cache: every slot is composited from scratch

    opened.clear()
    built.clear()
    second = render_preview(project, assets)

    assert opened == []  # nothing reopened: every icon decode was a cache hit
    assert built == []  # nothing recomposited: every panel was a cache hit
    assert second.tobytes() == first.tobytes()


def test_changing_one_placement_only_recomputes_that_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)

    render_preview(project, assets)  # warm the cache for every slot

    changed_member = project.teams[0][0]
    changed_member.offset_x = 0.4  # differs from the Placement default of 0.0

    opened = _patch_counting_open(monkeypatch)
    built = _patch_counting_panels(monkeypatch)
    render_preview(project, assets)

    # The decoded art is cached independently of the placement state, so the
    # recomputed slot resamples from the cache instead of reopening the PNG.
    assert opened == []
    # Exactly one of the eight slots was composited again: the one whose fx
    # changed. The other seven were served from the panel cache.
    assert built == ["make_panel"]


def test_clear_render_cache_forces_full_recompute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)

    render_preview(project, assets)  # warm the cache

    clear_render_cache()
    opened = _patch_counting_open(monkeypatch)
    render_preview(project, assets)

    all_art_paths = [str(asset.art_path) for asset in assets.values()]
    assert sorted(path for path in opened if path in set(all_art_paths)) == sorted(all_art_paths)


def test_clear_render_cache_empties_the_render_caches(tmp_path: Path) -> None:
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)

    render_preview(project, assets)
    assert _render_cache("art_cache")
    assert _render_cache("work_cache")  # 1200x900 art downscales for a preview panel
    assert _render_cache("mask_cache")
    assert _render_cache("border_cache")

    clear_render_cache()
    assert not _render_cache("art_cache")
    assert not _render_cache("work_cache")
    assert not _render_cache("mask_cache")
    assert not _render_cache("border_cache")


def test_export_project_clears_the_render_caches_when_done(tmp_path: Path) -> None:
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)

    render_preview(project, assets)
    assert _render_cache("panel_cache")
    assert _render_cache("weapon_icon_cache")
    assert _render_cache("art_cache")
    assert _render_cache("work_cache")
    assert _render_cache("mask_cache")
    assert _render_cache("border_cache")
    assert _render_cache("badge_cache")

    export_project(project, assets, tmp_path / "out")
    assert not _render_cache("panel_cache")
    assert not _render_cache("weapon_icon_cache")
    assert not _render_cache("art_cache")
    assert not _render_cache("work_cache")
    assert not _render_cache("mask_cache")
    assert not _render_cache("border_cache")
    assert not _render_cache("badge_cache")


def test_slots_with_identical_badge_state_share_one_cached_tile(tmp_path: Path) -> None:
    """A badge tile is drawn in tile-local coordinates and positioned only when
    it is composited, so every slot showing the same build, card colour and
    weapon icon must resolve to the same cache entry."""
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    # One asset for every slot: same constellation, refinement, rarities and
    # weapon icon. Its element pins the card colour too, which otherwise
    # differs per slot via the placement colour fallback.
    assets = create_assets(tmp_path, names[:1], elements={names[0]: "Pyro"})
    for member in (member for team in project.teams for member in team):
        member.name = names[0]
        member.build = live_build(names[0])

    render_preview(project, assets)

    assert len(_render_cache("badge_cache")) == 1

    clear_render_cache()
    assert not _render_cache("badge_cache")


def test_badge_cache_key_separates_builds_differing_only_in_c_and_r(tmp_path: Path) -> None:
    """Regression test: the badge cache key must include the constellation and
    the refinement. They are the badge's whole text, yet everything else the
    key covers (colour, rarities, weapon path, scale, compactness) can stay
    identical between two builds, so dropping either from the key would serve
    one build's tile for the other."""
    clear_render_cache()
    name = "Character 0"
    project = Project.blank("abyss")
    for member in (member for team in project.teams for member in team):
        member.name = name
        member.build = live_build(name)
    # A pinned element fixes the card colour across slots, so the only thing
    # varying below is the badge text itself.
    assets = create_assets(tmp_path, [name], elements={name: "Pyro"})
    asset = assets[asset_key(name)]

    def render_with(constellation: int, refinement: int) -> Image.Image:
        # Same tmp_path, hence the same weapon path, and no clear_render_cache()
        # in between: all three renders share one warm badge_cache.
        assets[asset_key(name)] = Asset(
            replace(asset.build, constellation=constellation, refinement=refinement),
            asset.art_path,
            asset.weapon_path,
        )
        return render_preview(project, assets)

    # Single-digit values throughout, so the badge text keeps its width and a
    # stale tile would land pixel-for-pixel on top of the fresh one.
    baseline = render_with(1, 1)
    other_constellation = render_with(6, 1)
    other_refinement = render_with(1, 5)

    assert ImageChops.difference(baseline, other_constellation).getbbox() is not None
    assert ImageChops.difference(baseline, other_refinement).getbbox() is not None


def test_swapping_slots_with_warm_cache_matches_fresh_render(tmp_path: Path) -> None:
    """Regression test: the panel cache key must include the slot's
    position (index/row/num_rows), not just the placement's own fields.
    Otherwise swapping two placements within a team (as the drag-and-drop
    reorder_slots GUI feature does) would reuse the other slot's stale,
    already-positioned cached layer instead of re-rendering at the new
    position."""
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)

    render_preview(project, assets)  # warm the cache for every slot

    project.teams[0][0], project.teams[0][1] = project.teams[0][1], project.teams[0][0]
    warm_cache_result = render_preview(project, assets)

    clear_render_cache()
    fresh_result = render_preview(project, assets)

    assert warm_cache_result.tobytes() == fresh_result.tobytes()


def test_flip_is_part_of_the_panel_cache_key(tmp_path: Path) -> None:
    """Regression test: flipping a placement must not be masked by the cached
    panel of its unflipped self."""
    clear_render_cache()
    project, assets = two_tone_project(tmp_path)

    unflipped = render_preview(project, assets)
    project.teams[0][1].flip = True
    flipped = render_preview(project, assets)  # deliberately no cache clear

    assert ImageChops.difference(unflipped, flipped).getbbox() is not None


def test_changing_asset_element_invalidates_stale_panel_cache(tmp_path: Path) -> None:
    """Regression test: panel_cache must key on the resolved card_color(),
    not the raw placement color. card_color() prefers asset.build.element
    over member.color, so changing only the element (e.g. after an Enka
    profile refresh) while member.color stays the same must not serve a
    stale, wrongly-colored panel from the cache."""
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)  # no elements: Build.element is None

    render_preview(project, assets)  # warm panel_cache with the fallback-color panel

    first_member_color = project.teams[0][0].color
    pyro_color = ELEMENT_COLORS["pyro"]
    assert first_member_color != pyro_color
    assets[asset_key(names[0])].build.element = "Pyro"

    warm = render_preview(project, assets)  # deliberately no cache clear

    clear_render_cache()
    fresh = render_preview(project, assets)

    assert ImageChops.difference(warm, fresh).getbbox() is None
