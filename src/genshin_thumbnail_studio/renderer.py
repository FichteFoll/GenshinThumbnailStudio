from __future__ import annotations

import collections
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .models import Asset, Placement, Project


BASE_W = 1280
BASE_H = 720

# Design-space constants (px at scale 1, multiplied by `scale` where used).
LINE = 3
CARD_BORDER = LINE
CARD_GAP = 2 * LINE
BACKGROUND_COLOR = (14, 14, 18, 255)  # #0e0e12

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
    return tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4)) + (alpha,)


def card_color(member: Placement, asset: Asset) -> str:
    """The card's element-inspired accent color, falling back to the
    placement's own color when the element is unknown or missing."""
    element = asset.build.element
    if element and element.casefold() in ELEMENT_COLORS:
        return ELEMENT_COLORS[element.casefold()]
    return member.color


def find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def cover_resize_focal(
    image: Image.Image,
    size: tuple[int, int],
    focal_x: float,
    focal_y: float,
    zoom: float,
) -> Image.Image:
    source_w, source_h = image.size
    target_w, target_h = size
    source_x = source_w * min(1.0, max(0.0, focal_x))
    source_y = source_h * min(1.0, max(0.0, focal_y))
    image_scale = max(target_w / source_w, target_h / source_h) * zoom
    resized_w = max(target_w, int(source_w * image_scale + 0.5))
    resized_h = max(target_h, int(source_h * image_scale + 0.5))
    resized = image.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
    left = int(round(source_x * image_scale - target_w / 2))
    top = int(round(source_y * image_scale - target_h / 2))
    left = max(0, min(left, resized_w - target_w))
    top = max(0, min(top, resized_h - target_h))
    return resized.crop((left, top, left + target_w, top + target_h))


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
    canvas_size: tuple[int, int],
    member: Placement,
    asset: Asset,
    index: int,
    row: int,
    num_rows: int,
    row_height: int,
    panel_width: int,
    step: float,
    slant: int,
    scale: int,
    compact: bool,
) -> Image.Image:
    art = Image.open(asset.art_path).convert("RGBA")
    target = (panel_width + slant * 2, row_height)
    color = card_color(member, asset)
    background = panel_background(target, color, compact)
    glow = cover_resize_focal(art, target, member.fx, member.fy, member.zoom * 0.78)
    glow = glow.filter(ImageFilter.GaussianBlur((14 if compact else 18) * scale))
    glow = ImageEnhance.Color(glow).enhance(1.20 if compact else 1.25)
    background = Image.alpha_composite(background, glow)

    crop = cover_resize_focal(art, target, member.fx, member.fy, member.zoom)
    crop = ImageEnhance.Color(crop).enhance(1.09 if compact else 1.10)
    crop = ImageEnhance.Contrast(crop).enhance(1.06 if compact else 1.07)
    alpha = crop.getchannel("A")
    shadow = Image.new("RGBA", target, (0, 0, 0, 0))
    shadow_blur = alpha.filter(ImageFilter.GaussianBlur((6 if compact else 8) * scale))
    shadow.putalpha(shadow_blur.point(lambda value: int(value * (0.35 if compact else 0.38))))
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

    return paste_panel_on_canvas(canvas_size, panel, index, row, num_rows, row_height, step, slant, scale)


def paste_panel_on_canvas(
    canvas_size: tuple[int, int],
    panel: Image.Image,
    index: int,
    row: int,
    num_rows: int,
    row_height: int,
    step: float,
    slant: int,
    scale: int,
) -> Image.Image:
    width, _ = canvas_size
    gap = CARD_GAP * scale
    border = CARD_BORDER * scale
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    layer.paste(panel, (int(round(index * step - slant)), row * row_height), panel)
    mask = Image.new("L", canvas_size, 0)
    ImageDraw.Draw(mask).polygon(
        panel_polygon(index, row, num_rows, width, row_height, step, slant, gap, border), fill=255
    )
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    return layer


def placeholder_panel(
    canvas_size: tuple[int, int],
    member: Placement,
    index: int,
    row: int,
    num_rows: int,
    row_height: int,
    panel_width: int,
    step: float,
    slant: int,
    scale: int,
    compact: bool,
) -> Image.Image:
    """A panel for a slot with no downloaded asset yet: same size/shape and
    mask/paste logic as make_panel(), but without character art, glow,
    shadow, or shade, since there is no Asset to read art from."""
    target = (panel_width + slant * 2, row_height)
    panel = panel_background(target, member.color, compact)
    return paste_panel_on_canvas(canvas_size, panel, index, row, num_rows, row_height, step, slant, scale)


# Bounded LRU caches for render output that would otherwise be recomputed
# on every preview render regardless of what actually changed: one for
# fully-composited panel layers (make_panel()/placeholder_panel() output),
# one for decoded/resized weapon icons. Cleared via clear_render_cache(),
# e.g. between tests that assert on cache hit/miss counts.
_PANEL_CACHE_MAX = 32
_panel_cache: collections.OrderedDict[tuple, Image.Image] = collections.OrderedDict()

_WEAPON_ICON_CACHE_MAX = 32
_weapon_icon_cache: collections.OrderedDict[tuple, Image.Image] = collections.OrderedDict()

# Previews render on a background thread while export_project() renders on
# the GUI thread, so both caches can be touched concurrently.
_cache_lock = threading.Lock()


def clear_render_cache() -> None:
    """Empty the panel and weapon-icon render caches."""
    with _cache_lock:
        _panel_cache.clear()
        _weapon_icon_cache.clear()


def _cache_get(cache: collections.OrderedDict[tuple, Image.Image], key: tuple) -> Image.Image | None:
    with _cache_lock:
        if key not in cache:
            return None
        cache.move_to_end(key)
        return cache[key]


def _cache_put(
    cache: collections.OrderedDict[tuple, Image.Image], key: tuple, value: Image.Image, max_size: int
) -> None:
    with _cache_lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)


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
    draw = ImageDraw.Draw(image)
    for row, team in enumerate(teams):
        for index, member in enumerate(team):
            asset = assets.get(member.name.casefold()) if member.name else None
            color = card_color(member, asset) if asset else member.color
            points = panel_polygon(index, row, num_rows, width, row_height, step, slant, gap, border)
            draw.polygon(points, outline=hex_to_rgba(color, 255), width=round(border))


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
    font = find_font((38 if compact else 54) * scale)
    icon_d = (48 if compact else 68) * scale
    stroke_width = (3 if compact else 4) * scale
    for row, team in enumerate(teams):
        for index, member in enumerate(team):
            if not member.name or member.name.casefold() not in assets:
                continue
            asset = assets[member.name.casefold()]
            center = int(round(index * step + step / 2))
            top_y = row * row_height + row_height - (68 if compact else 107) * scale
            text = f"C{asset.build.constellation}R{asset.build.refinement}"
            geometry = badge_geometry(draw, text, font, center, top_y, scale, compact)
            draw.rounded_rectangle(
                geometry.box,
                radius=(14 if compact else 18) * scale,
                fill=(0, 0, 0, 178),
                outline=hex_to_rgba(card_color(member, asset), 245),
                width=3 * scale,
            )
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
            text_x = geometry.text_center[0] - combined_w // 2
            text_y = geometry.text_center[1]
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
            draw.ellipse(
                geometry.circle,
                fill=(0, 0, 0, 170),
                outline=hex_to_rgba(card_color(member, asset), 240),
                width=2 * scale,
            )
            icon_key = (str(asset.weapon_path), icon_d)
            icon = _cache_get(_weapon_icon_cache, icon_key)
            if icon is None:
                icon = Image.open(asset.weapon_path).convert("RGBA")
                icon.thumbnail((icon_d, icon_d), Image.Resampling.LANCZOS)
                _cache_put(_weapon_icon_cache, icon_key, icon, _WEAPON_ICON_CACHE_MAX)
            circle_x, circle_y, circle_x1, _circle_y1 = geometry.circle
            circle_d = circle_x1 - circle_x
            image.alpha_composite(icon, (circle_x + (circle_d - icon.width) // 2, circle_y + (circle_d - icon.height) // 2))


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
    row_height = height // 2 if compact else height
    step = width / 4
    slant = (38 if compact else 52) * scale
    panel_width = (340 if compact else 360) * scale
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
                round(member.fx, 4),
                round(member.fy, 4),
                round(member.zoom, 4),
                member.color,
                str(asset.art_path) if asset else None,
                row_height,
                panel_width,
                step,
                slant,
                scale,
                compact,
            )
            panel = _cache_get(_panel_cache, cache_key)
            if panel is None:
                if asset is not None:
                    panel = make_panel(
                        canvas.size,
                        member,
                        asset,
                        index,
                        row,
                        num_rows,
                        row_height,
                        panel_width,
                        step,
                        slant,
                        scale,
                        compact,
                    )
                else:
                    panel = placeholder_panel(
                        canvas.size,
                        member,
                        index,
                        row,
                        num_rows,
                        row_height,
                        panel_width,
                        step,
                        slant,
                        scale,
                        compact,
                    )
                _cache_put(_panel_cache, cache_key, panel, _PANEL_CACHE_MAX)
            canvas = Image.alpha_composite(canvas, panel)
    add_card_borders(canvas, teams, assets, row_height, step, slant, scale)
    add_badges(canvas, teams, assets, row_height, step, scale, compact)
    return canvas.convert("RGB").resize(output_size, Image.Resampling.LANCZOS)


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
    written = []
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
    return written
