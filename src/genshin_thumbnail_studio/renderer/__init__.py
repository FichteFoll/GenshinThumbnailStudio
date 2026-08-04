from __future__ import annotations

import functools
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from ..models import Asset, Placement, Project
from .cache import (
    ART_CACHE_MAX,
    BADGE_CACHE_MAX,
    BORDER_CACHE_MAX,
    MASK_CACHE_MAX,
    PANEL_CACHE_MAX,
    WEAPON_ICON_CACHE_MAX,
    WORK_CACHE_MAX,
    CacheKey,
    art_cache,
    badge_cache,
    border_cache,
    cache_get,
    cache_put,
    clear_render_cache,
    mask_cache,
    panel_cache,
    weapon_icon_cache,
    work_cache,
)
from .colors import (
    ELEMENT_COLORS,
    RARITY_COLORS,
    card_color,
    hex_to_rgba,
    rarity_color,
)
from .coverage import (
    GEOMETRY_SUPERSAMPLE,
    paint_through_coverage,
    supersampled_box,
    supersampled_coverage,
    supersampled_coverage_for,
)
from .geometry import (
    BACKGROUND_COLOR,
    BASE_H,
    BASE_W,
    CARD_BORDER,
    CARD_GAP,
    LINE,
    PAN_OVERSCAN,
    STANDARD_ART_SIZE,
    cover_scale,
    max_offset,
    offset_limits,
    panel_metrics,
    panel_origin,
    panel_polygon,
    panel_target_size,
    resized_art_size,
    scaled_size,
)

# The names that moved into the submodules above, re-exported so the package's
# public surface stays exactly what renderer.py exposed before the split. The
# rest of the implementation still lives in this module.
__all__ = [
    "ART_CACHE_MAX",
    "BACKGROUND_COLOR",
    "BADGE_CACHE_MAX",
    "BASE_H",
    "BASE_W",
    "BORDER_CACHE_MAX",
    "CARD_BORDER",
    "CARD_GAP",
    "ELEMENT_COLORS",
    "GEOMETRY_SUPERSAMPLE",
    "LINE",
    "MASK_CACHE_MAX",
    "PANEL_CACHE_MAX",
    "PAN_OVERSCAN",
    "RARITY_COLORS",
    "STANDARD_ART_SIZE",
    "WEAPON_ICON_CACHE_MAX",
    "WORK_CACHE_MAX",
    "CacheKey",
    "art_cache",
    "badge_cache",
    "border_cache",
    "cache_get",
    "cache_put",
    "card_color",
    "clear_render_cache",
    "cover_scale",
    "hex_to_rgba",
    "mask_cache",
    "max_offset",
    "offset_limits",
    "paint_through_coverage",
    "panel_cache",
    "panel_metrics",
    "panel_origin",
    "panel_polygon",
    "panel_target_size",
    "rarity_color",
    "resized_art_size",
    "scaled_size",
    "supersampled_box",
    "supersampled_coverage",
    "supersampled_coverage_for",
    "weapon_icon_cache",
    "work_cache",
]


# The GUI clamps a placement's zoom to 0.70..1.80, so a preview working copy
# scaled for 1.80 is never upsampled by an edit made through the GUI.
MAX_PLACEMENT_ZOOM = 1.80

# The panel glow is immediately Gaussian-blurred at a radius far wider than a
# few pixels, so any detail resampled into it is destroyed anyway. Building it
# at a quarter of the panel resolution (and blurring at a correspondingly
# smaller radius) produces the same soft wash for a fraction of the work.
GLOW_DOWNSCALE = 4

# How much wider than the character crop the blurred glow layer is framed.
GLOW_ZOOM_FACTOR = 0.78

# Guards the shared FreeTypeFont that find_font() memoizes - not the render
# caches above. Pillow does not document a font object as safe to measure or
# draw with from two threads at once, so add_badges() serializes its whole
# font-using span on this lock. It is always taken before _cache_lock (never
# the other way round), and nothing under it re-enters add_badges().
_font_lock = threading.Lock()


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


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" ._")
    return cleaned or "thumbnail"


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
    resized_w, resized_h = scaled_size(image.size, image_scale)
    limit_x, limit_y = offset_limits((resized_w, resized_h), size)
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
    """A panel for a slot with no downloaded asset yet: same size and mask
    logic as make_panel(), but without character art, glow, shadow, or shade,
    since there is no Asset to read art from."""
    target = panel_target_size(compact, scale)
    panel = panel_background(target, member.color, compact)
    return apply_panel_mask(panel, index, row, num_rows, canvas_width, row_height, step, slant, scale)


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
    art = cache_get(art_cache, art_key)
    if art is None:
        art = Image.open(asset.art_path).convert("RGBA")
        cache_put(art_cache, art_key, art, ART_CACHE_MAX)
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
    working = cache_get(work_cache, work_key)
    if working is None:
        # Pillow's Image.resize() stub leaves its overload partially unknown.
        working = art.resize(work, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
        cache_put(work_cache, work_key, working, WORK_CACHE_MAX)
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
    icon = cache_get(weapon_icon_cache, icon_key)
    if icon is None:
        icon = Image.open(asset.weapon_path).convert("RGBA")
        # Enka weapon PNGs can pad their visible art asymmetrically on the canvas,
        # so center on the art's own alpha bounding box, not the canvas it ships in.
        alpha_bbox = icon.getbbox()
        if alpha_bbox is not None:
            icon = icon.crop(alpha_bbox)
        icon.thumbnail((icon_d, icon_d), Image.Resampling.LANCZOS)
        cache_put(weapon_icon_cache, icon_key, icon, WEAPON_ICON_CACHE_MAX)
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
                cached = cache_get(badge_cache, tile_key)
                if cached is None:
                    cached = badge_tile(geometry, asset, color, font, scale, compact)
                    cache_put(badge_cache, tile_key, cached, BADGE_CACHE_MAX)
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
            panel = cache_get(panel_cache, cache_key)
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
                cache_put(panel_cache, cache_key, panel, PANEL_CACHE_MAX)
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
