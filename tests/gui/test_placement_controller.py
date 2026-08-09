"""Tests for `gui.placement.PlacementController`, needing no Qt environment.

The controller is Qt-free: it constructs no widget and needs no display, so these
tests run without `QT_QPA_PLATFORM` being set.
(PySide6 still ends up imported, because reaching `gui.placement` executes the
`gui` package's facade, but nothing here uses it.)
"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from genshin_thumbnail_studio.gui.placement import MAX_ZOOM, MIN_ZOOM, PlacementController
from genshin_thumbnail_studio.models import DEFAULT_ZOOM, Build, Mode, Placement, Project
from genshin_thumbnail_studio.renderer import (
    STANDARD_ART_SIZE,
    art_pixel_size,
    max_offset,
    panel_target_size,
)

from .helpers import create_test_assets, live_build


@dataclass
class StubState:
    """The minimal `EditorState` the controller needs."""

    project: Project
    builds: dict[str, list[Build]] = field(default_factory=dict)
    art_root: Path = Path("assets")


def _state(tmp_path: Path, mode: Mode = "abyss", with_assets: bool = True) -> StubState:
    project = Project.blank(mode)
    member = project.teams[0][0]
    member.name = "Furina"
    member.build = live_build("Furina")
    root = tmp_path / "assets"
    if with_assets:
        create_test_assets(root, ["Furina"])
    return StubState(project=project, art_root=root)


def _approx(expected: float) -> object:
    """Wraps `pytest.approx`, whose own parameters are unannotated in pytest itself."""
    return pytest.approx(expected, abs=1e-9)  # pyright: ignore[reportUnknownMemberType]


def test_offset_bounds_match_the_renderer_for_a_downloaded_asset(tmp_path: Path) -> None:
    state = _state(tmp_path)
    controller = PlacementController(state)
    member = state.project.teams[0][0]

    art_size = art_pixel_size(str(live_build("Furina").art_path(state.art_root)))

    assert controller.offset_bounds(member) == max_offset(art_size, True, member.zoom)


def test_offset_bounds_fall_back_to_the_standard_art_size_without_an_asset(tmp_path: Path) -> None:
    state = _state(tmp_path, with_assets=False)
    controller = PlacementController(state)
    member = state.project.teams[0][0]

    assert controller.offset_bounds(member) == max_offset(STANDARD_ART_SIZE, True, member.zoom)


def test_pan_moves_one_canvas_pixel_per_offset_fraction(tmp_path: Path) -> None:
    state = _state(tmp_path)
    controller = PlacementController(state)
    member = state.project.teams[0][0]
    target_w, _ = panel_target_size(compact=True)
    member.offset_x = 0.0
    # A whole panel width of drag is exactly 1.0 of offset, but that clamps, so
    # drag a fraction that stays inside the reachable range.
    fraction = controller.offset_bounds(member)[0] / 2

    controller.pan(member, fraction * target_w, 0.0)

    assert member.offset_x == _approx(fraction)


def test_pan_clamps_to_the_reachable_bounds(tmp_path: Path) -> None:
    state = _state(tmp_path)
    controller = PlacementController(state)
    member = state.project.teams[0][0]
    max_x, max_y = controller.offset_bounds(member)

    controller.pan(member, 10_000, 10_000)
    assert (member.offset_x, member.offset_y) == (max_x, max_y)

    controller.pan(member, -20_000, -20_000)
    assert (member.offset_x, member.offset_y) == (-max_x, -max_y)


def test_zoom_by_clamps_to_the_gui_range(tmp_path: Path) -> None:
    state = _state(tmp_path)
    controller = PlacementController(state)
    member = state.project.teams[0][0]

    controller.zoom_by(member, 10.0)
    assert member.zoom == MAX_ZOOM

    controller.zoom_by(member, -10.0)
    assert member.zoom == MIN_ZOOM


def test_reset_restores_the_mode_default_zoom_and_clears_the_flip(tmp_path: Path) -> None:
    modes: list[Mode] = ["abyss", "stygian"]
    for mode in modes:
        state = _state(tmp_path, mode)
        controller = PlacementController(state)
        member = state.project.teams[0][0]
        member.offset_x = 0.2
        member.offset_y = 0.2
        member.zoom = 1.5
        member.flip = True

        controller.reset(member)

        defaults = Placement()
        assert member.offset_x == defaults.offset_x
        assert member.offset_y == defaults.offset_y
        assert member.zoom == DEFAULT_ZOOM[mode]
        assert member.flip is False


def test_offset_bounds_follow_a_replaced_project(tmp_path: Path) -> None:
    """The controller reads `state.project` per call, so replacing it takes effect.

    A captured project would keep reporting the abyss bounds here, which is the
    whole reason the collaborators go through the `EditorState` Protocol.
    """
    state = _state(tmp_path)
    controller = PlacementController(state)
    member = state.project.teams[0][0]
    art_size = art_pixel_size(str(live_build("Furina").art_path(state.art_root)))

    before = controller.offset_bounds(member)
    assert before == max_offset(art_size, True, member.zoom)

    stygian = Project.blank("stygian")
    stygian.teams[0][0].name = member.name
    stygian.teams[0][0].build = member.build
    state.project = stygian

    after = controller.offset_bounds(member)
    assert after == max_offset(art_size, False, member.zoom)
    assert after != before
