from __future__ import annotations

import collections
import functools
import math
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias, TypeVar

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .models import Asset, Placement, Project

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

ELEMENT_COLORS = {
    "anemo": "#74c2a8",
    "geo": "#ffb84d",
    "electro": "#b08fc9",
    "dendro": "#a5c83b",
    "hydro": "#4cc2f1",
    "pyro": "#ff7b52",
    "cryo": "#9fe7ef",
}

RARITY_COLORS = {
    5: "#ffd95d",
    4: "#c69bff",
    3: "#7ab3e0",
    2: "#79c8a0",
    1: "#c4c8cf",
}


# The GUI clamps a placement's zoom to 0.70..1.80, so a preview working copy
# scaled for 1.80 is never upsampled by an edit made through the GUI.
MAX_PLACEMENT_ZOOM = 1.80

# The panel glow is immediately Gaussian-blurred at a radius far wider than a
# few pixels, so any detail resampled into it is destroyed anyway. Building it
# at a quarter of the panel resolution (and blurring at a correspondingly
# smaller radius) produces the same soft wash for a fraction of the work.
GLOW_DOWNSCALE = 4

# Pillow's ImageDraw has no antialiasing, so the near-vertical slanted card
# edges come out stair-stepped. Drawing that geometry at 4x into a
# single-channel coverage image and box-downsampling it yields proper edge
# coverage; "L" rather than "RGBA" makes it ~6x cheaper for the same result,
# and the outcome is cached anyway because it only depends on the layout.
GEOMETRY_SUPERSAMPLE = 4

# How much wider than the character crop the blurred glow layer is framed.
GLOW_ZOOM_FACTOR = 0.78


def glow_zoom(zoom: float) -> float:
    """The zoom the panel glow is cover-fit at, for a placement zoom.

    The glow is deliberately framed wider than the crop, so the wash around the
    portrait shows a different part of the art, but it must still cover the
    whole panel. Since both art axes scale by the same factor, zoom 1.0 is the
    smallest factor that still covers the panel, so the floor wins for every
    placement zoom up to `1 / GLOW_ZOOM_FACTOR` and the factor itself only
    applies above that. Below a placement zoom of 1.0 the floor even leaves the
    glow more zoomed in than the crop, which is what keeps the panel covered
    while the portrait shrinks inside it.
    """
    return max(1.0, zoom * GLOW_ZOOM_FACTOR)


def rarity_color(rarity: int | None) -> str:
    """The in-game rarity accent color, falling back to the 5-star gold
    when the rarity is unknown so the current look stays the default."""
    if rarity is None:
        return RARITY_COLORS[5]
    return RARITY_COLORS.get(rarity, RARITY_COLORS[5])


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" ._")
    return cleaned or "thumbnail"


def hex_to_rgba(value: str, alpha: int) -> tuple[int, int, int, int]:
    raw = value.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raise ValueError(f"Invalid color: {value}")
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), alpha)


def card_color(member: Placement, asset: Asset) -> str:
    """The card's element-inspired accent color, falling back to the
    placement's own color when the element is unknown or missing."""
    element = asset.build.element
    if element and element.casefold() in ELEMENT_COLORS:
        return ELEMENT_COLORS[element.casefold()]
    return member.color


@functools.lru_cache(maxsize=8)
def find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """The bold system font at `size`, memoized: probing the filesystem and
    loading the TrueType face on every render is pure overhead, since the same
    handful of sizes (one per scale) is requested over and over.

    Memoizing shares one FreeTypeFont between callers, and Pillow does not
    document those as thread-safe. Sharing is safe because every use of the
    returned object - the lookup itself, the text measurement and the drawing -
    happens inside `with _font_lock:` in add_badges(), the only production
    caller, so no two threads ever touch the same font concurrently."""
    candidates = [
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
        Path(r"C:\Windows\Fonts\Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


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


def _scaled_size(source_size: tuple[int, int], image_scale: float) -> tuple[int, int]:
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
    return _scaled_size(art_size, cover_scale(art_size, target, zoom))


def _offset_limits(resized: tuple[int, int], target: tuple[int, int]) -> tuple[float, float]:
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


def max_offset(
    art_size: tuple[int, int], compact: bool, zoom: float, scale: int = 1
) -> tuple[float, float]:
    """Reachable +/- offset per axis, in fractions of the panel size.

    Shares its formula with the clamp in `cover_resize_offset()`, so the GUI
    slider bounds and the renderer can never disagree about the reachable range.
    """
    return _offset_limits(
        resized_art_size(art_size, compact, zoom, scale), panel_target_size(compact, scale)
    )


def cover_resize_offset(
    image: Image.Image,
    size: tuple[int, int],
    offset_x: float,
    offset_y: float,
    zoom: float,
    resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> Image.Image:
    """Cover-fit `image` into `size`, panned by signed offsets.

    The offsets are fractions of the target size, positive meaning the visible
    content moves right/down. They are clamped to the reachable range first,
    which includes `PAN_OVERSCAN`, so the crop window may extend past the
    resized art by that margin. That overscanned strip is left transparent,
    letting the panel background and glow show through without any extra
    compositing.
    """
    source_w, source_h = image.size
    target_w, target_h = size
    image_scale = cover_scale(image.size, size, zoom)
    resized_w, resized_h = _scaled_size(image.size, image_scale)
    limit_x, limit_y = _offset_limits((resized_w, resized_h), size)
    offset_x = min(limit_x, max(-limit_x, offset_x))
    offset_y = min(limit_y, max(-limit_y, offset_y))
    left = round((resized_w - target_w) / 2 - offset_x * target_w)
    top = round((resized_h - target_h) / 2 - offset_y * target_h)

    # Resampling only the crop window's source region is far cheaper than
    # scaling the whole image and throwing most of it away. The window is
    # mapped back with source_w / resized_w rather than 1 / image_scale
    # because resized_w/resized_h are rounded integers, and dividing by them
    # keeps the mapping exact at the right and bottom edges.
    # It is clipped to the art first, since Image.resize() rejects a box that
    # leaves the source, which the overscan margin makes possible.
    visible_left = max(0, left)
    visible_top = max(0, top)
    visible_right = min(resized_w, left + target_w)
    visible_bottom = min(resized_h, top + target_h)
    if visible_right <= visible_left or visible_bottom <= visible_top:
        return Image.new("RGBA", size, (0, 0, 0, 0))
    box = (
        visible_left * source_w / resized_w,
        visible_top * source_h / resized_h,
        visible_right * source_w / resized_w,
        visible_bottom * source_h / resized_h,
    )
    visible_size = (visible_right - visible_left, visible_bottom - visible_top)
    # Pillow's Image.resize() stub leaves its overload partially unknown.
    visible = image.resize(visible_size, resample, box=box)  # pyright: ignore[reportUnknownMemberType]
    if visible_size == size:
        return visible

    panned = Image.new("RGBA", size, (0, 0, 0, 0))
    panned.paste(visible, (visible_left - left, visible_top - top))
    return panned


def panel_art(
    art: Image.Image,
    target: tuple[int, int],
    member: Placement,
    zoom: float,
    resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> Image.Image:
    """One panel's crop of the character art, mirrored when the placement is
    flipped.

    Flipping is defined as mirroring the source artwork, which would leave the
    framing untouched. Mirroring the panel-sized crop and negating the
    horizontal offset is the same image for a fraction of the cost, because
    negating a panel-relative offset mirrors the crop window about the panel
    center:
    ``mirror(crop(art, -offset_x)) == crop(mirror(art), offset_x)``.
    Mirroring the crop also keeps the shared, read-only art cache untouched.
    """
    offset_x = -member.offset_x if member.flip else member.offset_x
    crop = cover_resize_offset(art, target, offset_x, member.offset_y, zoom, resample)
    if member.flip:
        crop = crop.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return crop


@functools.lru_cache(maxsize=64)
def art_pixel_size(path: str) -> tuple[int, int]:
    """The art file's dimensions, read from its header without decoding it.

    Kept out of the render caches on purpose: those hold images and are emptied
    by `clear_render_cache()`, while a given file's dimensions never change.
    """
    with Image.open(path) as image:
        return image.size


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


def supersampled_coverage_for(
    size: tuple[int, int], draw_shape: Callable[[ImageDraw.ImageDraw, int], None]
) -> Image.Image:
    """An antialiased "L" coverage map of `size`, drawn by `draw_shape(draw, factor)`
    in coordinates multiplied by `factor`.

    Drawing outside the map is clipped by ImageDraw, which is what lets the
    slanted card outlines overhang their own layer.
    """
    big_size = (size[0] * GEOMETRY_SUPERSAMPLE, size[1] * GEOMETRY_SUPERSAMPLE)
    big = Image.new("L", big_size, 0)
    draw_shape(ImageDraw.Draw(big), GEOMETRY_SUPERSAMPLE)
    # Pillow's Image.resize() stub leaves its overload partially unknown.
    return big.resize(size, Image.Resampling.BOX)  # pyright: ignore[reportUnknownMemberType]


def supersampled_coverage(
    size: tuple[int, int], points: list[tuple[int, int]], width: int | None = None
) -> Image.Image:
    """An antialiased "L" coverage map of `size` for the polygon `points`:
    filled when `width` is None, otherwise a `width`-pixel outline stroke.
    """

    def draw_shape(draw: ImageDraw.ImageDraw, factor: int) -> None:
        big_points = [(x * factor, y * factor) for x, y in points]
        if width is None:
            draw.polygon(big_points, fill=255)
        else:
            draw.polygon(big_points, outline=255, width=width * factor)

    return supersampled_coverage_for(size, draw_shape)


def supersampled_box(box: tuple[int, int, int, int], factor: int) -> tuple[int, int, int, int]:
    """`box` blown up by `factor` for a supersampled draw. Pillow's shape
    coordinates are inclusive, so scaling the raw values would leave the far
    edges one supersampled pixel short and shrink the shape by a whole
    downsampled pixel."""
    x0, y0, x1, y1 = box
    return (x0 * factor, y0 * factor, (x1 + 1) * factor - 1, (y1 + 1) * factor - 1)


def _hard_mask(mask: Image.Image) -> Image.Image:
    """`mask` with every partially covered pixel promoted to full coverage."""

    def lut(value: int) -> int:
        return 255 if value else 0

    # Pillow's Image.point() stub leaves its overload partially unknown.
    return mask.point(lut)  # pyright: ignore[reportUnknownMemberType]


def _fully_covered(mask: Image.Image) -> Image.Image:
    """The part of `mask` that is covered completely rather than partially."""

    def lut(value: int) -> int:
        return 255 if value == 255 else 0

    # Pillow's Image.point() stub leaves its overload partially unknown.
    return mask.point(lut)  # pyright: ignore[reportUnknownMemberType]


def paint_through_coverage(
    tile: Image.Image, color: tuple[int, int, int, int], mask: Image.Image, painted: Image.Image
) -> Image.Image:
    """Paint `color` into `tile` through the antialiased `mask` and return the
    grown `painted` coverage.

    `Image.paste()` blends toward what the tile already holds, so on a shape's
    outer silhouette, where that is still transparent black, a half-covered
    pixel would end up at half the colour. The caller then pastes the tile onto
    the card through the very same coverage, which would multiply by that half
    a second time and fade every antialiased edge toward black. Seeding the
    footprint with the flat colour first keeps those pixels at the colour
    itself and leaves the softness to the coverage mask alone.

    The seed is skipped where an earlier shape already covers the pixel
    completely: there the tile holds real content the new shape should blend
    into, which is what antialiases the shapes against each other. A pixel an
    earlier shape only covers partially is part of the badge's silhouette and
    gets seeded, so the outermost shape's colour survives the coverage paste.
    """
    seed = ImageChops.subtract(_hard_mask(mask), _fully_covered(painted))
    tile.paste(color, mask=seed)
    tile.paste(color, mask=mask)
    return ImageChops.lighter(painted, mask)


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
    asset: Asset,
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
    art = source_art(asset, target, member.zoom, scale)
    color = card_color(member, asset)
    background = panel_background(target, color, compact)
    glow_size = (max(1, target[0] // GLOW_DOWNSCALE), max(1, target[1] // GLOW_DOWNSCALE))
    glow = panel_art(
        art,
        glow_size,
        member,
        glow_zoom(member.zoom),
        resample=Image.Resampling.BILINEAR,
    )
    glow = glow.filter(ImageFilter.GaussianBlur((14 if compact else 18) * scale / GLOW_DOWNSCALE))
    glow = ImageEnhance.Color(glow).enhance(1.20 if compact else 1.25)
    # Pillow's Image.resize() stub leaves its overload partially unknown.
    glow = glow.resize(target, Image.Resampling.BILINEAR)  # pyright: ignore[reportUnknownMemberType]
    background = Image.alpha_composite(background, glow)

    crop = panel_art(art, target, member, member.zoom)
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


def panel_origin(index: int, row: int, row_height: int, step: float, slant: int) -> tuple[int, int]:
    """Where a panel-sized layer sits on the canvas. Slot 0's x is negative,
    because the slant makes the panel overhang the canvas on the left (and
    slot 3's makes it overhang on the right)."""
    return round(index * step - slant), row * row_height


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
    mask = _cache_get(_mask_cache, mask_key)
    if mask is None:
        gap = CARD_GAP * scale
        border = CARD_BORDER * scale
        points = panel_polygon(index, row, num_rows, canvas_width, row_height, step, slant, gap, border)
        origin_x, origin_y = panel_origin(index, row, row_height, step, slant)
        local_points = [(x - origin_x, y - origin_y) for x, y in points]
        mask = supersampled_coverage(panel.size, local_points)
        _cache_put(_mask_cache, mask_key, mask, _MASK_CACHE_MAX)
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
    """A panel for a slot with no downloaded asset yet: same size and mask
    logic as make_panel(), but without character art, glow, shadow, or shade,
    since there is no Asset to read art from."""
    target = panel_target_size(compact, scale)
    panel = panel_background(target, member.color, compact)
    return apply_panel_mask(panel, index, row, num_rows, canvas_width, row_height, step, slant, scale)


# Bounded LRU caches for render output that would otherwise be recomputed
# on every preview render regardless of what actually changed: one for
# fully-composited panel layers (make_panel()/placeholder_panel() output),
# one for decoded/resized weapon icons, one for decoded character art, and
# one for preview-sized working copies of that art. Cleared via
# clear_render_cache(), e.g. between tests that assert on cache hit/miss
# counts, and automatically at the end of every export_project() call (even
# if it raises) to release its larger export-scale entries.
#
# Cached panels are panel-sized (~0.6 MB each at preview scale, so the bound is
# ~19 MB) and are composited *into* the canvas rather than being the composite
# operand, so they must never be mutated once cached; canvas.alpha_composite()
# only reads them.
#
# The keys are heterogeneous tuples of primitives (paths, floats, ints, bools)
# assembled ad hoc by each cache's caller, so `tuple[object, ...]` is the
# honest type rather than a made-up, more specific structure.
CacheKey: TypeAlias = tuple[object, ...]

_PANEL_CACHE_MAX = 32
_panel_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

_WEAPON_ICON_CACHE_MAX = 32
_weapon_icon_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

_ART_CACHE_MAX = 12
_art_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

_WORK_CACHE_MAX = 12
_work_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

# The supersampled card mask and card-border overlay depend on the layout
# geometry alone (and, for the border, its colour), never on the placement, so
# after the first frame they are permanent hits even while a portrait is dragged.
_MASK_CACHE_MAX = 16
_mask_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

_BORDER_CACHE_MAX = 16
_border_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

# A slot's C/R + weapon badge depends on the build and the card colour, never
# on the placement's position or zoom, so it survives a drag untouched. Each
# entry is the drawn tile plus the coverage mask that says which of its pixels
# the drawing actually touched (see badge_tile()).
_BADGE_CACHE_MAX = 16
_badge_cache: collections.OrderedDict[CacheKey, tuple[Image.Image, Image.Image]] = collections.OrderedDict()

# Previews render on a background thread while export_project() renders on
# the GUI thread, so all caches can be touched concurrently.
_cache_lock = threading.Lock()

# Guards the shared FreeTypeFont that find_font() memoizes - not the render
# caches above. Pillow does not document a font object as safe to measure or
# draw with from two threads at once, so add_badges() serializes its whole
# font-using span on this lock. It is always taken before _cache_lock (never
# the other way round), and nothing under it re-enters add_badges().
_font_lock = threading.Lock()


def clear_render_cache() -> None:
    """Empty the panel, weapon-icon, character-art, working-copy, card-mask,
    card-border and badge caches."""
    with _cache_lock:
        _panel_cache.clear()
        _weapon_icon_cache.clear()
        _art_cache.clear()
        _work_cache.clear()
        _mask_cache.clear()
        _border_cache.clear()
        _badge_cache.clear()


_CacheValue = TypeVar("_CacheValue")


def _cache_get(cache: collections.OrderedDict[CacheKey, _CacheValue], key: CacheKey) -> _CacheValue | None:
    with _cache_lock:
        if key not in cache:
            return None
        cache.move_to_end(key)
        return cache[key]


def _cache_put(
    cache: collections.OrderedDict[CacheKey, _CacheValue], key: CacheKey, value: _CacheValue, max_size: int
) -> None:
    with _cache_lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)


def source_art(asset: Asset, target: tuple[int, int], zoom: float, scale: int) -> Image.Image:
    """The image make_panel() should resample its panel art from.

    For a preview render this is a working copy pre-downscaled to what the
    largest GUI-reachable zoom needs, so a drag resamples a few megapixels
    less per frame. Exports (and zooms beyond the GUI's clamp, which can only
    come from a hand-edited project file) resample the full-resolution source
    so they never lose detail.

    The cached images are shared between the preview render thread and the
    GUI thread, so they must be treated as read-only. Every consumer produces
    a new image via resize()/crop(), so no copy is made here.
    """
    art_key = (str(asset.art_path),)
    art = _cache_get(_art_cache, art_key)
    if art is None:
        art = Image.open(asset.art_path).convert("RGBA")
        _cache_put(_art_cache, art_key, art, _ART_CACHE_MAX)
    if scale != 1 or zoom > MAX_PLACEMENT_ZOOM:
        return art

    source_w, source_h = art.size
    # Same cover scale cover_resize_offset() computes, but at the maximum zoom
    # rather than this placement's, so one working copy serves every zoom.
    work_scale = cover_scale(art.size, target, MAX_PLACEMENT_ZOOM)
    work = (round(source_w * work_scale), round(source_h * work_scale))
    if work[0] >= source_w or work[1] >= source_h:
        return art

    work_key = (str(asset.art_path), *work)
    working = _cache_get(_work_cache, work_key)
    if working is None:
        # Pillow's Image.resize() stub leaves its overload partially unknown.
        working = art.resize(work, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
        _cache_put(_work_cache, work_key, working, _WORK_CACHE_MAX)
    return working


def add_card_borders(
    image: Image.Image,
    teams: list[list[Placement]],
    assets: dict[str, Asset],
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
            asset = assets.get(member.name.casefold()) if member.name else None
            color = card_color(member, asset) if asset else member.color
            origin_x, origin_y = panel_origin(index, row, row_height, step, slant)
            # overlay_size is fully derived from step, slant and row_height.
            overlay_key = (index, row, num_rows, width, row_height, step, slant, scale, color)
            overlay = _cache_get(_border_cache, overlay_key)
            if overlay is None:
                points = panel_polygon(index, row, num_rows, width, row_height, step, slant, gap, border)
                local_points = [(x - origin_x, y - origin_y) for x, y in points]
                overlay = Image.new("RGBA", overlay_size, hex_to_rgba(color, 255))
                overlay.putalpha(supersampled_coverage(overlay_size, local_points, width=round(border)))
                _cache_put(_border_cache, overlay_key, overlay, _BORDER_CACHE_MAX)
            # Same clipping as the panels: slot 0 overhangs the canvas on the
            # left and needs a source offset, slot 3 overhangs on the right and
            # is clipped by the in-place composite itself.
            image.alpha_composite(overlay, (max(0, origin_x), origin_y), (max(0, -origin_x), 0))


@dataclass(frozen=True)
class BadgeGeometry:
    """Computed layout for one C/R badge, in canvas pixels."""

    box: tuple[int, int, int, int]  # (x0, y0, x1, y1)
    text_center: tuple[int, int]
    circle: tuple[int, int, int, int]  # (x0, y0, x1, y1)
    group_x: int
    group_w: int


def badge_geometry(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    center_x: int,
    top_y: int,
    scale: int,
    compact: bool,
) -> BadgeGeometry:
    padding = (12 if compact else 18) * scale
    min_box_w = (126 if compact else 170) * scale
    box_h = (58 if compact else 82) * scale
    gap = (8 if compact else 12) * scale
    circle_d = (62 if compact else 88) * scale
    stroke_width = (3 if compact else 4) * scale

    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_w = int(right - left)
    box_w = max(min_box_w, text_w + 2 * padding)

    group_w = box_w + gap + circle_d
    group_x = center_x - group_w // 2

    box_x0, box_y0 = group_x, top_y
    box_x1, box_y1 = group_x + box_w, top_y + box_h

    circle_x = group_x + box_w + gap
    circle_y = top_y - (2 if compact else 3) * scale

    return BadgeGeometry(
        box=(box_x0, box_y0, box_x1, box_y1),
        text_center=((box_x0 + box_x1) // 2, (box_y0 + box_y1) // 2),
        circle=(circle_x, circle_y, circle_x + circle_d, circle_y + circle_d),
        group_x=group_x,
        group_w=group_w,
    )


def badge_tile_origin(geometry: BadgeGeometry) -> tuple[int, int]:
    """Where a badge tile sits on the canvas: the top-left of the union of the
    C/R box and the weapon circle, the latter of which starts slightly above
    the box."""
    return geometry.group_x, min(geometry.box[1], geometry.circle[1])


def badge_tile(
    geometry: BadgeGeometry,
    asset: Asset,
    color: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    scale: int,
    compact: bool,
) -> tuple[Image.Image, Image.Image]:
    """Draw one slot's C/R box and weapon circle into a standalone tile.

    Returns the tile and an "L" coverage mask marking the pixels the drawing
    touched. ImageDraw *replaces* pixels on an RGBA image rather than blending
    into them, so the badge's semi-transparent fills are opaque once the canvas
    is flattened to RGB; pasting the tile through its coverage mask reproduces
    that exactly, while alpha-compositing it would instead let the card art
    show through the badge.

    The box and the circle are drawn supersampled, so their edge pixels are
    only partially covered on purpose: the paste in add_badges() then blends
    them into the card art, which is what antialiases the shapes.

    Everything is drawn in tile-local coordinates, so the tile depends only on
    the build, the card colour and the render scale, not on the slot it ends
    up in.

    Inside the shapes the paste reproduces the drawn RGB exactly, but where a
    semi-transparent weapon icon pokes out of the circle it writes the icon's
    own alpha instead of the blended alpha an alpha_composite() would leave
    behind. That is invisible today because add_badges() is the last step and
    render_image() flattens to RGB right after; compositing anything on top of
    the badges would make it a real difference.
    """
    origin_x, origin_y = badge_tile_origin(geometry)
    box = (
        geometry.box[0] - origin_x,
        geometry.box[1] - origin_y,
        geometry.box[2] - origin_x,
        geometry.box[3] - origin_y,
    )
    circle = (
        geometry.circle[0] - origin_x,
        geometry.circle[1] - origin_y,
        geometry.circle[2] - origin_x,
        geometry.circle[3] - origin_y,
    )
    # Pillow's shape coordinates are inclusive, so the tile needs one pixel
    # more than the raw extent in each direction.
    size = (max(box[2], circle[2]) + 1, max(box[3], circle[3]) + 1)
    tile = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)

    box_radius = (14 if compact else 18) * scale
    box_width = 3 * scale
    box_fill = supersampled_coverage_for(
        size,
        lambda d, factor: d.rounded_rectangle(
            supersampled_box(box, factor), radius=box_radius * factor, fill=255
        ),
    )
    box_outline = supersampled_coverage_for(
        size,
        lambda d, factor: d.rounded_rectangle(
            supersampled_box(box, factor),
            radius=box_radius * factor,
            outline=255,
            width=box_width * factor,
        ),
    )
    painted = Image.new("L", size, 0)
    painted = paint_through_coverage(tile, (0, 0, 0, 178), box_fill, painted)
    painted = paint_through_coverage(tile, hex_to_rgba(color, 245), box_outline, painted)

    stroke_width = (3 if compact else 4) * scale
    constellation_text = f"C{asset.build.constellation}"
    refinement_text = f"R{asset.build.refinement}"
    constellation_left, _, constellation_right, _ = draw.textbbox(
        (0, 0), constellation_text, font=font, stroke_width=stroke_width
    )
    refinement_left, _, refinement_right, _ = draw.textbbox(
        (0, 0), refinement_text, font=font, stroke_width=stroke_width
    )
    constellation_w = constellation_right - constellation_left
    refinement_w = refinement_right - refinement_left
    # Two separate bounding boxes each carry the stroke's overhang on
    # both sides, so summing them double-counts the stroke width at
    # the seam between the runs; subtract it once to land on the same
    # combined width (and hence the same centering) as the original
    # single-string measurement.
    combined_w = constellation_w + refinement_w - 2 * stroke_width
    text_x = geometry.text_center[0] - origin_x - combined_w // 2
    text_y = geometry.text_center[1] - origin_y
    draw.text(
        (text_x, text_y),
        constellation_text,
        font=font,
        fill=hex_to_rgba(rarity_color(asset.build.rarity), 255),
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, 255),
        anchor="lm",
    )
    draw.text(
        (text_x + constellation_w - stroke_width, text_y),
        refinement_text,
        font=font,
        fill=hex_to_rgba(rarity_color(asset.build.weapon_rarity), 255),
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, 255),
        anchor="lm",
    )

    circle_width = 2 * scale
    circle_fill = supersampled_coverage_for(
        size, lambda d, factor: d.ellipse(supersampled_box(circle, factor), fill=255)
    )
    circle_outline = supersampled_coverage_for(
        size,
        lambda d, factor: d.ellipse(
            supersampled_box(circle, factor), outline=255, width=circle_width * factor
        ),
    )
    painted = paint_through_coverage(tile, (0, 0, 0, 170), circle_fill, painted)
    coverage = paint_through_coverage(tile, hex_to_rgba(color, 240), circle_outline, painted)

    icon_d = (48 if compact else 68) * scale
    icon_key = (str(asset.weapon_path), icon_d)
    icon = _cache_get(_weapon_icon_cache, icon_key)
    if icon is None:
        icon = Image.open(asset.weapon_path).convert("RGBA")
        # Enka weapon PNGs can pad their visible art asymmetrically on the canvas,
        # so center on the art's own alpha bounding box, not the canvas it ships in.
        alpha_bbox = icon.getbbox()
        if alpha_bbox is not None:
            icon = icon.crop(alpha_bbox)
        icon.thumbnail((icon_d, icon_d), Image.Resampling.LANCZOS)
        _cache_put(_weapon_icon_cache, icon_key, icon, _WEAPON_ICON_CACHE_MAX)
    circle_d = circle[2] - circle[0]
    icon_pos = (circle[0] + (circle_d - icon.width) // 2, circle[1] + (circle_d - icon.height) // 2)
    tile.alpha_composite(icon, icon_pos)
    # The icon's square footprint pokes out of the circle at its corners, where
    # the tile is blended onto whatever the card shows rather than replacing it.
    # Coverage set to the icon's own alpha makes the paste do exactly that.
    icon_box = (icon_pos[0], icon_pos[1], icon_pos[0] + icon.width, icon_pos[1] + icon.height)
    coverage.paste(ImageChops.lighter(coverage.crop(icon_box), icon.getchannel("A")), icon_pos)
    return tile, coverage


def add_badges(
    image: Image.Image,
    teams: list[list[Placement]],
    assets: dict[str, Asset],
    row_height: int,
    step: float,
    scale: int,
    compact: bool,
) -> None:
    draw = ImageDraw.Draw(image)
    # The font is shared across threads, so hold _font_lock for every use of it,
    # not just the find_font() lookup: badge_geometry() measures with it and
    # badge_tile() draws with it.
    with _font_lock:
        font = find_font((38 if compact else 54) * scale)
        for row, team in enumerate(teams):
            for index, member in enumerate(team):
                if not member.name or member.name.casefold() not in assets:
                    continue
                asset = assets[member.name.casefold()]
                center = round(index * step + step / 2)
                top_y = row * row_height + row_height - (68 if compact else 107) * scale
                text = f"C{asset.build.constellation}R{asset.build.refinement}"
                geometry = badge_geometry(draw, text, font, center, top_y, scale, compact)
                color = card_color(member, asset)
                tile_key = (
                    asset.build.constellation,
                    asset.build.refinement,
                    asset.build.rarity,
                    asset.build.weapon_rarity,
                    color,
                    str(asset.weapon_path),
                    scale,
                    compact,
                )
                cached = _cache_get(_badge_cache, tile_key)
                if cached is None:
                    cached = badge_tile(geometry, asset, color, font, scale, compact)
                    _cache_put(_badge_cache, tile_key, cached, _BADGE_CACHE_MAX)
                tile, coverage = cached
                image.paste(tile, badge_tile_origin(geometry), coverage)


def render_image(
    teams: list[list[Placement]],
    assets: dict[str, Asset],
    compact: bool,
    scale: int = 1,
    output_size: tuple[int, int] = (BASE_W, BASE_H),
    require_complete: bool = True,
) -> Image.Image:
    if scale < 1 or scale > 4:
        raise ValueError("Scale must be between 1 and 4.")
    width = BASE_W * scale
    height = BASE_H * scale
    row_height, _, slant = panel_metrics(compact, scale)
    step = width / 4
    canvas = Image.new("RGBA", (width, height), BACKGROUND_COLOR)
    num_rows = len(teams)
    for row, team in enumerate(teams):
        for index, member in enumerate(team):
            has_asset = bool(member.name) and member.name.casefold() in assets
            if not has_asset and require_complete:
                raise ValueError(f"No downloaded Akasha asset for slot {row + 1}-{index + 1}.")
            asset = assets[member.name.casefold()] if has_asset else None
            cache_key = (
                index,
                row,
                num_rows,
                member.name.casefold(),
                round(member.offset_x, 4),
                round(member.offset_y, 4),
                round(member.zoom, 4),
                member.flip,
                # Must track what make_panel() actually paints with
                # (card_color(member, asset)), not the raw placement color,
                # or a stale panel can survive an element change.
                card_color(member, asset) if asset else member.color,
                str(asset.art_path) if asset else None,
                row_height,
                step,
                slant,
                scale,
                compact,
            )
            panel = _cache_get(_panel_cache, cache_key)
            if panel is None:
                if asset is not None:
                    panel = make_panel(
                        width,
                        member,
                        asset,
                        index,
                        row,
                        num_rows,
                        row_height,
                        step,
                        slant,
                        scale,
                        compact,
                    )
                else:
                    panel = placeholder_panel(
                        width,
                        member,
                        index,
                        row,
                        num_rows,
                        row_height,
                        step,
                        slant,
                        scale,
                        compact,
                    )
                _cache_put(_panel_cache, cache_key, panel, _PANEL_CACHE_MAX)
            # The panel overhangs the canvas on the left for slot 0 and on the
            # right for slot 3; clipping the left overhang needs a source
            # offset, while the in-place composite clips the right one itself.
            origin_x, origin_y = panel_origin(index, row, row_height, step, slant)
            canvas.alpha_composite(panel, (max(0, origin_x), origin_y), (max(0, -origin_x), 0))
    add_card_borders(canvas, teams, assets, row_height, step, slant, scale)
    add_badges(canvas, teams, assets, row_height, step, scale, compact)
    # Pillow's Image.resize() stub leaves its overload partially unknown.
    return canvas.convert("RGB").resize(output_size, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]


def render_preview(project: Project, assets: dict[str, Asset]) -> Image.Image:
    project.ensure_shape()
    if project.mode == "abyss":
        return render_image(project.teams, assets, compact=True, scale=1, require_complete=False)
    return render_image(
        [project.teams[project.active_team]], assets, compact=False, scale=1, require_complete=False
    )


def export_project(project: Project, assets: dict[str, Asset], directory: Path) -> list[Path]:
    project.ensure_shape()
    directory.mkdir(parents=True, exist_ok=True)
    scale = min(4, max(2, math.ceil(2 * project.output_height / BASE_H)))
    output_size = project.output_size
    written: list[Path] = []
    try:
        if project.mode == "abyss":
            target = directory / f"{safe_name(project.output_name)}.png"
            render_image(project.teams, assets, compact=True, scale=scale, output_size=output_size).save(
                target, optimize=True
            )
            written.append(target)
        else:
            for index, team in enumerate(project.teams, start=1):
                target = directory / f"{safe_name(project.output_name)}_boss{index}.png"
                render_image([team], assets, compact=False, scale=scale, output_size=output_size).save(
                    target, optimize=True
                )
                written.append(target)
    finally:
        clear_render_cache()
    return written
