"""The panel geometry and the reachable pan range.

Single source of the panel layout: the GUI's placement sliders and the
renderer's own crop both read their bounds from here, so they cannot disagree.
"""

from __future__ import annotations

import math

BASE_W = 1280
BASE_H = 720

# Design-space constants (px at scale 1, multiplied by `scale` where used).
LINE = 3
CARD_BORDER = LINE
CARD_GAP = 2 * LINE
BACKGROUND_COLOR = (14, 14, 18, 255)  # #0e0e12

# Size of an Enka splash art. Used as a fallback wherever the real art is not
# available (a placement whose asset has not been downloaded yet, or a legacy
# project file, which stores no art dimensions).
STANDARD_ART_SIZE = (2048, 1024)

# The crop window may leave the art by this fraction of the panel size on
# every side. Cover-fit alone leaves almost no vertical slack for 2:1 splash
# art (only target_h * (zoom - 1)), which made vertical panning useless;
# overscanning exposes a bounded strip of the glow/background layer instead.
PAN_OVERSCAN = 0.10


def panel_metrics(compact: bool, scale: int = 1) -> tuple[int, int, int]:
    """Row height, panel width and slant overhang of one character panel."""
    height = BASE_H * scale
    row_height = height // 2 if compact else height
    panel_width = (340 if compact else 360) * scale
    slant = (38 if compact else 52) * scale
    return row_height, panel_width, slant


def panel_target_size(compact: bool, scale: int = 1) -> tuple[int, int]:
    """Pixel size of the art crop for one panel, slant overhang included."""
    row_height, panel_width, slant = panel_metrics(compact, scale)
    return panel_width + slant * 2, row_height


def cover_scale(source_size: tuple[int, int], target: tuple[int, int], zoom: float) -> float:
    """Factor that scales the source art to cover the target box, times the zoom."""
    source_w, source_h = source_size
    target_w, target_h = target
    return max(target_w / source_w, target_h / source_h) * zoom


def scaled_size(source_size: tuple[int, int], image_scale: float) -> tuple[int, int]:
    """Both axes multiplied by the same factor, so the zoom never changes the
    art's aspect ratio.

    The result may end up smaller than the panel, which is intentional: the
    crop window then overhangs the art and the panel background and glow show
    through the margin, which is preferable to stretching the portrait.
    """
    source_w, source_h = source_size
    return (max(1, int(source_w * image_scale + 0.5)), max(1, int(source_h * image_scale + 0.5)))


def resized_art_size(
    art_size: tuple[int, int], compact: bool, zoom: float, scale: int = 1
) -> tuple[int, int]:
    """Pixel size the art is resized to before it is cropped into one panel."""
    target = panel_target_size(compact, scale)
    return scaled_size(art_size, cover_scale(art_size, target, zoom))


def offset_limits(resized: tuple[int, int], target: tuple[int, int]) -> tuple[float, float]:
    """Largest panel-relative offset per axis that still moves the crop.

    The slack is the absolute difference between the art and the panel, so both
    directions read the same way: art larger than the panel can be panned by
    the part hanging over its edges, art smaller than the panel by the margin
    it leaves inside them, and `PAN_OVERSCAN` adds a strip beyond that either
    way. Signed slack would go negative for art smaller than the panel minus
    the overscan, which inverts the `min(limit, max(-limit, offset))` clamp in
    `cover_resize_offset()`.
    """
    return (
        abs(resized[0] - target[0]) / (2 * target[0]) + PAN_OVERSCAN,
        abs(resized[1] - target[1]) / (2 * target[1]) + PAN_OVERSCAN,
    )


def zoom_offset_limits(
    source_size: tuple[int, int], target: tuple[int, int], zoom: float
) -> tuple[float, float]:
    """Reachable +/- offset per axis for source art cover-fit into `target`
    at `zoom`, in fractions of the target size."""
    return offset_limits(scaled_size(source_size, cover_scale(source_size, target, zoom)), target)


def max_offset(
    art_size: tuple[int, int], compact: bool, zoom: float, scale: int = 1
) -> tuple[float, float]:
    """Reachable +/- offset per axis, in fractions of the panel size.

    Shares its formula with the clamp in `cover_resize_offset()`, so the GUI
    slider bounds and the renderer can never disagree about the reachable range.
    """
    return zoom_offset_limits(art_size, panel_target_size(compact, scale), zoom)


def panel_polygon(
    index: int,
    row: int,
    num_rows: int,
    width: int,
    row_height: int,
    step: float,
    slant: int,
    gap: float,
    border: float,
) -> list[tuple[int, int]]:
    """Compute one card's outline, inset by half the gap/border on every
    shared or outer edge so neighbouring cards never touch.

    Vertical (slanted) edges are inset horizontally by more than the plain
    gap/2, scaled by the secant of the slant angle, so the resulting inset
    is perpendicular to the slanted edge rather than a raw horizontal shift.
    """
    half_gap = gap / 2
    half_border = border / 2
    y0 = row * row_height + (half_border if row == 0 else half_gap)
    y1 = (row + 1) * row_height - (half_border if row == num_rows - 1 else half_gap)

    perp_scale = math.hypot(row_height, 2 * slant) / row_height if slant else 1.0

    x0 = index * step
    x1 = (index + 1) * step

    if index == 0:
        left_top = left_bottom = half_border
    else:
        left_inset = half_gap * perp_scale
        left_top = x0 + slant + left_inset
        left_bottom = x0 - slant + left_inset

    if index == 3:
        right_top = right_bottom = width - half_border
    else:
        right_inset = half_gap * perp_scale
        right_top = x1 + slant - right_inset
        right_bottom = x1 - slant - right_inset

    return [
        (round(left_top), round(y0)),
        (round(right_top), round(y0)),
        (round(right_bottom), round(y1)),
        (round(left_bottom), round(y1)),
    ]


def panel_origin(index: int, row: int, row_height: int, step: float, slant: int) -> tuple[int, int]:
    """Where a panel-sized layer sits on the canvas. Slot 0's x is negative,
    because the slant makes the panel overhang the canvas on the left (and
    slot 3's makes it overhang on the right)."""
    return round(index * step - slant), row * row_height
