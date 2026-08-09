"""One character panel end to end: background glow, art, shading and card mask."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from ..models import Placement
from .art import glow_zoom, panel_art, source_art
from .cache import (
    BORDER_CACHE_MAX,
    MASK_CACHE_MAX,
    border_cache,
    cache_get,
    cache_put,
    mask_cache,
)
from .colors import card_color, hex_to_rgba
from .coverage import supersampled_coverage
from .geometry import (
    CARD_BORDER,
    CARD_GAP,
    panel_origin,
    panel_polygon,
    panel_target_size,
    zoom_offset_limits,
)

# The panel glow is immediately Gaussian-blurred at a radius far wider than a
# few pixels, so any detail resampled into it is destroyed anyway. Building it
# at a quarter of the panel resolution (and blurring at a correspondingly
# smaller radius) produces the same soft wash for a fraction of the work.
GLOW_DOWNSCALE = 4


def panel_background(size: tuple[int, int], color: str, compact: bool) -> Image.Image:
    width, height = size
    background = Image.new("RGBA", size, (18, 18, 22, 255))
    draw = ImageDraw.Draw(background)
    accent = hex_to_rgba(color, 255)
    base = 16 if compact else 18
    amplitude = 38 if compact else 42
    center = 0.45 if compact else 0.42
    for y in range(height):
        position = y / max(1, height - 1)
        shade = int(base + amplitude * (1 - abs(position - center)))
        draw.line(
            (0, y, width, y),
            fill=(
                min(255, int(accent[0] * 0.17 + shade)),
                min(255, int(accent[1] * 0.17 + shade)),
                min(255, int(accent[2] * 0.17 + shade)),
                255,
            ),
        )
    return background


def make_panel(
    canvas_width: int,
    member: Placement,
    art_path: Path,
    index: int,
    row: int,
    num_rows: int,
    row_height: int,
    step: float,
    slant: int,
    scale: int,
    compact: bool,
) -> Image.Image:
    target = panel_target_size(compact, scale)
    art = source_art(art_path, target, member.zoom, scale)
    # Both layers below are crops of the same art at different zooms; sharing
    # the portrait's own reachable range clamps them to the same offsets, so
    # the glow stops panning at the same moment the portrait does instead of
    # sticking at its own, narrower limit.
    limits = zoom_offset_limits(art.size, target, member.zoom)
    color = card_color(member)
    background = panel_background(target, color, compact)
    glow_size = (max(1, target[0] // GLOW_DOWNSCALE), max(1, target[1] // GLOW_DOWNSCALE))
    glow = panel_art(
        art,
        glow_size,
        member,
        glow_zoom(member.zoom),
        resample=Image.Resampling.BILINEAR,
        limits=limits,
    )
    glow = glow.filter(ImageFilter.GaussianBlur((14 if compact else 18) * scale / GLOW_DOWNSCALE))
    glow = ImageEnhance.Color(glow).enhance(1.20 if compact else 1.25)
    # Pillow's Image.resize() stub leaves its overload partially unknown.
    glow = glow.resize(target, Image.Resampling.BILINEAR)  # pyright: ignore[reportUnknownMemberType]
    background = Image.alpha_composite(background, glow)

    crop = panel_art(art, target, member, member.zoom, limits=limits)
    crop = ImageEnhance.Color(crop).enhance(1.09 if compact else 1.10)
    crop = ImageEnhance.Contrast(crop).enhance(1.06 if compact else 1.07)
    alpha = crop.getchannel("A")
    shadow = Image.new("RGBA", target, (0, 0, 0, 0))
    shadow_blur = alpha.filter(ImageFilter.GaussianBlur((6 if compact else 8) * scale))
    shadow_opacity = 0.35 if compact else 0.38

    def shadow_lut(value: int) -> int:
        return int(value * shadow_opacity)

    # Pillow's Image.point() stub leaves its overload partially unknown.
    shadow.putalpha(shadow_blur.point(shadow_lut))  # pyright: ignore[reportUnknownMemberType]
    panel = Image.alpha_composite(background, shadow)
    panel = Image.alpha_composite(panel, crop)
    panel = Image.alpha_composite(panel, Image.new("RGBA", panel.size, hex_to_rgba(color, 14 if compact else 18)))

    shade = Image.new("RGBA", panel.size, (0, 0, 0, 0))
    shade_draw = ImageDraw.Draw(shade)
    top_extent = (58 if compact else 120) * scale
    bottom_extent = (94 if compact else 190) * scale
    for y in range(row_height):
        top = max(0, top_extent - y) / top_extent
        bottom = max(0, y - (row_height - bottom_extent)) / bottom_extent
        alpha_value = int((165 if compact else 210) * top + (130 if compact else 125) * bottom)
        if alpha_value:
            shade_draw.line((0, y, panel.width, y), fill=(0, 0, 0, min(255, alpha_value)))
    panel = Image.alpha_composite(panel, shade)

    return apply_panel_mask(panel, index, row, num_rows, canvas_width, row_height, step, slant, scale)


def apply_panel_mask(
    panel: Image.Image,
    index: int,
    row: int,
    num_rows: int,
    canvas_width: int,
    row_height: int,
    step: float,
    slant: int,
    scale: int,
) -> Image.Image:
    """Cut the slanted card shape out of `panel`, in place, and return it.

    The polygon is computed in canvas coordinates and then translated into
    panel-local ones, so the mask depends only on the layout geometry and is
    shared by every placement that lands in the same slot.
    """
    mask_key = (index, row, num_rows, canvas_width, row_height, step, slant, scale, panel.size)
    mask = cache_get(mask_cache, mask_key)
    if mask is None:
        gap = CARD_GAP * scale
        border = CARD_BORDER * scale
        points = panel_polygon(index, row, num_rows, canvas_width, row_height, step, slant, gap, border)
        origin_x, origin_y = panel_origin(index, row, row_height, step, slant)
        local_points = [(x - origin_x, y - origin_y) for x, y in points]
        mask = supersampled_coverage(panel.size, local_points)
        cache_put(mask_cache, mask_key, mask, MASK_CACHE_MAX)
    panel.putalpha(ImageChops.multiply(panel.getchannel("A"), mask))
    return panel


def placeholder_panel(
    canvas_width: int,
    member: Placement,
    index: int,
    row: int,
    num_rows: int,
    row_height: int,
    step: float,
    slant: int,
    scale: int,
    compact: bool,
) -> Image.Image:
    """A panel for a slot whose art has not been downloaded yet: same size and
    mask logic as make_panel(), but without character art, glow, shadow, or
    shade, since there is no file to read art from."""
    target = panel_target_size(compact, scale)
    panel = panel_background(target, member.color, compact)
    return apply_panel_mask(panel, index, row, num_rows, canvas_width, row_height, step, slant, scale)


def add_card_borders(
    image: Image.Image,
    teams: list[list[Placement]],
    row_height: int,
    step: float,
    slant: int,
    scale: int,
) -> None:
    width, _ = image.size
    gap = CARD_GAP * scale
    border = CARD_BORDER * scale
    num_rows = len(teams)
    # A card outline never reaches further than one step plus the slant
    # overhang on either side of its own origin, so the overlay only needs to
    # be that wide rather than canvas-wide. The extra pixel absorbs the
    # rounding of the fractional step and origin plus the half stroke width
    # that the outline extends past the polygon on the right.
    overlay_size = (math.ceil(step) + 2 * slant + 1, row_height)
    for row, team in enumerate(teams):
        for index, member in enumerate(team):
            color = card_color(member)
            origin_x, origin_y = panel_origin(index, row, row_height, step, slant)
            # overlay_size is fully derived from step, slant and row_height.
            overlay_key = (index, row, num_rows, width, row_height, step, slant, scale, color)
            overlay = cache_get(border_cache, overlay_key)
            if overlay is None:
                points = panel_polygon(index, row, num_rows, width, row_height, step, slant, gap, border)
                local_points = [(x - origin_x, y - origin_y) for x, y in points]
                overlay = Image.new("RGBA", overlay_size, hex_to_rgba(color, 255))
                overlay.putalpha(supersampled_coverage(overlay_size, local_points, width=round(border)))
                cache_put(border_cache, overlay_key, overlay, BORDER_CACHE_MAX)
            # Same clipping as the panels: slot 0 overhangs the canvas on the
            # left and needs a source offset, slot 3 overhangs on the right and
            # is clipped by the in-place composite itself.
            image.alpha_composite(overlay, (max(0, origin_x), origin_y), (max(0, -origin_x), 0))
