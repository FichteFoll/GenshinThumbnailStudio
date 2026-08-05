from genshin_thumbnail_studio.renderer.art import cover_resize_offset
from genshin_thumbnail_studio.renderer.geometry import (
    PAN_OVERSCAN,
    STANDARD_ART_SIZE,
    max_offset,
    panel_target_size,
)

from .helpers import marked_source


def test_panel_target_size_scales_with_mode_and_scale() -> None:
    assert panel_target_size(compact=True) == (416, 360)
    assert panel_target_size(compact=True, scale=2) == (832, 720)
    assert panel_target_size(compact=False) == (464, 720)
    assert panel_target_size(compact=False, scale=2) == (928, 1440)


def test_max_offset_matches_the_cover_fit_slack_plus_the_overscan() -> None:
    max_x, max_y = max_offset(STANDARD_ART_SIZE, compact=True, zoom=1.06)
    assert abs(max_x - 0.517) < 0.001
    assert abs(max_y - 0.130) < 0.001

    # The crop cannot be panned past the reachable range.
    source = marked_source()
    target = panel_target_size(compact=True)
    at_limit = cover_resize_offset(source, target, max_x, 0.0, 1.06)
    beyond_limit = cover_resize_offset(source, target, max_x + 0.5, 0.0, 1.06)
    assert at_limit.tobytes() == beyond_limit.tobytes()


def test_vertical_max_offset_is_the_overscan_plus_half_the_zoom() -> None:
    # The 2:1 splash art is wider than every panel, so it always fits the panel
    # height exactly at zoom 1 and the only vertical slack comes from the zoom.
    for compact in (True, False):
        for zoom in (1.06, 1.18, 1.80):
            _, max_y = max_offset(STANDARD_ART_SIZE, compact=compact, zoom=zoom)
            assert abs(max_y - (PAN_OVERSCAN + (zoom - 1) / 2)) < 0.001
