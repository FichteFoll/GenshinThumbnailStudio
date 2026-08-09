"""The C/R and weapon badges drawn onto each character panel."""

from __future__ import annotations

import functools
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from ..models import Build, Placement
from .cache import (
    BADGE_CACHE_MAX,
    WEAPON_ICON_CACHE_MAX,
    badge_cache,
    cache_get,
    cache_put,
    weapon_icon_cache,
)
from .colors import card_color, hex_to_rgba, rarity_color
from .coverage import paint_through_coverage, supersampled_box, supersampled_coverage_for

# Guards the shared FreeTypeFont that find_font() memoizes - not the render
# caches. Pillow does not document a font object as safe to measure or
# draw with from two threads at once, so add_badges() serializes its whole
# font-using span on this lock. It is always taken before _cache_lock (never
# the other way round), and nothing under it re-enters add_badges().
_font_lock = threading.Lock()


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
    build: Build,
    weapon_path: Path,
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
    constellation_text = f"C{build.constellation}"
    refinement_text = f"R{build.refinement}"
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
        fill=hex_to_rgba(rarity_color(build.rarity), 255),
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, 255),
        anchor="lm",
    )
    draw.text(
        (text_x + constellation_w - stroke_width, text_y),
        refinement_text,
        font=font,
        fill=hex_to_rgba(rarity_color(build.weapon_rarity), 255),
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
    icon_key = (str(weapon_path), icon_d)
    icon = cache_get(weapon_icon_cache, icon_key)
    if icon is None:
        icon = Image.open(weapon_path).convert("RGBA")
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
    art_root: Path,
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
                build = member.build
                if build is None:
                    continue
                weapon_path = build.weapon_path(art_root)
                # Both files, not just the weapon icon: a slot whose art has not
                # arrived renders as a placeholder, which carries no badges.
                if not build.art_path(art_root).exists() or not weapon_path.exists():
                    continue
                center = round(index * step + step / 2)
                top_y = row * row_height + row_height - (68 if compact else 107) * scale
                text = f"C{build.constellation}R{build.refinement}"
                geometry = badge_geometry(draw, text, font, center, top_y, scale, compact)
                color = card_color(member)
                # The weapon path is derived from the character name and the
                # weapon URL, so it identifies the icon's content; the four
                # build fields beside it are the badge's whole remaining text
                # and colouring.
                tile_key = (
                    build.constellation,
                    build.refinement,
                    build.rarity,
                    build.weapon_rarity,
                    color,
                    str(weapon_path),
                    scale,
                    compact,
                )
                cached = cache_get(badge_cache, tile_key)
                if cached is None:
                    cached = badge_tile(geometry, build, weapon_path, color, font, scale, compact)
                    cache_put(badge_cache, tile_key, cached, BADGE_CACHE_MAX)
                tile, coverage = cached
                image.paste(tile, badge_tile_origin(geometry), coverage)
