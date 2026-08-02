from __future__ import annotations

import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .models import Asset, Placement, Project


BASE_W = 1280
BASE_H = 720


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", value).strip(" ._")
    return cleaned or "thumbnail"


def hex_to_rgba(value: str, alpha: int) -> tuple[int, int, int, int]:
    raw = value.lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raise ValueError(f"Invalid color: {value}")
    return tuple(int(raw[index : index + 2], 16) for index in (0, 2, 4)) + (alpha,)


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


def panel_polygon(index: int, row: int, width: int, row_height: int, step: float, slant: int) -> list[tuple[int, int]]:
    y0 = row * row_height
    y1 = y0 + row_height
    x0 = int(round(index * step))
    x1 = int(round((index + 1) * step))
    if index == 0:
        return [(0, y0), (x1 + slant, y0), (x1 - slant, y1), (0, y1)]
    if index == 3:
        return [(x0 + slant, y0), (width, y0), (width, y1), (x0 - slant, y1)]
    return [(x0 + slant, y0), (x1 + slant, y0), (x1 - slant, y1), (x0 - slant, y1)]


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
    row_height: int,
    panel_width: int,
    step: float,
    slant: int,
    scale: int,
    compact: bool,
) -> Image.Image:
    art = Image.open(asset.art_path).convert("RGBA")
    target = (panel_width + slant * 2, row_height)
    background = panel_background(target, member.color, compact)
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
    panel = Image.alpha_composite(panel, Image.new("RGBA", panel.size, hex_to_rgba(member.color, 14 if compact else 18)))

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

    width, _ = canvas_size
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    layer.paste(panel, (int(round(index * step - slant)), row * row_height), panel)
    mask = Image.new("L", canvas_size, 0)
    ImageDraw.Draw(mask).polygon(panel_polygon(index, row, width, row_height, step, slant), fill=255)
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), mask))
    return layer


def add_separators(image: Image.Image, teams: list[list[Placement]], row_height: int, step: float, slant: int, scale: int, compact: bool) -> None:
    width, height = image.size
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width - 1, height - 1), outline=(12, 12, 12, 235), width=8 * scale)
    if compact:
        draw.line((0, row_height, width, row_height), fill=(255, 255, 255, 145), width=2 * scale)
        draw.line((0, row_height + 4 * scale, width, row_height + 4 * scale), fill=(0, 0, 0, 150), width=2 * scale)
    for row, team in enumerate(teams):
        y0 = row * row_height
        y1 = y0 + row_height
        for index in (1, 2, 3):
            x = int(round(index * step))
            color = team[index].color
            overshoot = (24 if compact else 40) * scale
            offset = (4 if compact else 5) * scale
            draw.line((x + slant, y0 - overshoot, x - slant, y1 + overshoot), fill=hex_to_rgba(color, 235), width=3 * scale)
            draw.line(
                (x + slant + offset, y0 - overshoot, x - slant + offset, y1 + overshoot),
                fill=(255, 255, 255, 125),
                width=max(1, scale),
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
    box_w = (126 if compact else 170) * scale
    box_h = (58 if compact else 82) * scale
    gap = (8 if compact else 12) * scale
    circle_d = (62 if compact else 88) * scale
    icon_d = (48 if compact else 68) * scale
    for row, team in enumerate(teams):
        for index, member in enumerate(team):
            asset = assets[member.name.casefold()]
            center = int(round(index * step + step / 2))
            group_w = box_w + gap + circle_d
            group_x = center - group_w // 2
            y = row * row_height + row_height - (68 if compact else 107) * scale
            draw.rounded_rectangle(
                (group_x, y, group_x + box_w, y + box_h),
                radius=(14 if compact else 18) * scale,
                fill=(0, 0, 0, 178),
                outline=hex_to_rgba(member.color, 245),
                width=3 * scale,
            )
            draw.text(
                (group_x + (12 if compact else 18) * scale, y + (8 if compact else 10) * scale),
                f"C{asset.build.constellation}R{asset.build.refinement}",
                font=font,
                fill=(255, 227, 111, 255),
                stroke_width=(3 if compact else 4) * scale,
                stroke_fill=(0, 0, 0, 255),
            )
            circle_x = group_x + box_w + gap
            circle_y = y - (2 if compact else 3) * scale
            draw.ellipse(
                (circle_x, circle_y, circle_x + circle_d, circle_y + circle_d),
                fill=(0, 0, 0, 170),
                outline=(255, 255, 255, 240),
                width=2 * scale,
            )
            icon = Image.open(asset.weapon_path).convert("RGBA")
            icon.thumbnail((icon_d, icon_d), Image.Resampling.LANCZOS)
            image.alpha_composite(icon, (circle_x + (circle_d - icon.width) // 2, circle_y + (circle_d - icon.height) // 2))


def render_image(teams: list[list[Placement]], assets: dict[str, Asset], compact: bool, scale: int = 1) -> Image.Image:
    if scale < 1 or scale > 4:
        raise ValueError("Scale must be between 1 and 4.")
    width = BASE_W * scale
    height = BASE_H * scale
    row_height = height // 2 if compact else height
    step = width / 4
    slant = (38 if compact else 52) * scale
    panel_width = (340 if compact else 360) * scale
    canvas = Image.new("RGBA", (width, height), (22, 22, 22, 255))
    for row, team in enumerate(teams):
        for index, member in enumerate(team):
            if not member.name or member.name.casefold() not in assets:
                raise ValueError(f"No downloaded Akasha asset for slot {row + 1}-{index + 1}.")
            panel = make_panel(
                canvas.size,
                member,
                assets[member.name.casefold()],
                index,
                row,
                row_height,
                panel_width,
                step,
                slant,
                scale,
                compact,
            )
            canvas = Image.alpha_composite(canvas, panel)
    add_separators(canvas, teams, row_height, step, slant, scale, compact)
    add_badges(canvas, teams, assets, row_height, step, scale, compact)
    return canvas.convert("RGB").resize((BASE_W, BASE_H), Image.Resampling.LANCZOS)


def render_preview(project: Project, assets: dict[str, Asset]) -> Image.Image:
    project.ensure_shape()
    if project.mode == "abyss":
        return render_image(project.teams, assets, compact=True, scale=1)
    return render_image([project.teams[project.active_team]], assets, compact=False, scale=1)


def export_project(project: Project, assets: dict[str, Asset], directory: Path, quality: int = 94) -> list[Path]:
    project.ensure_shape()
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    if project.mode == "abyss":
        target = directory / f"{safe_name(project.output_name)}.jpg"
        render_image(project.teams, assets, compact=True, scale=2).save(target, quality=quality, optimize=True)
        written.append(target)
    else:
        for index, team in enumerate(project.teams, start=1):
            target = directory / f"{safe_name(project.output_name)}_boss{index}.jpg"
            render_image([team], assets, compact=False, scale=2).save(target, quality=quality, optimize=True)
            written.append(target)
    return written
