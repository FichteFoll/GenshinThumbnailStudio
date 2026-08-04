from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageChops, ImageDraw

from genshin_thumbnail_studio import renderer
from genshin_thumbnail_studio.models import Asset, Build, Placement, Project
from genshin_thumbnail_studio.renderer import (
    BACKGROUND_COLOR,
    BASE_W,
    CARD_BORDER,
    CARD_GAP,
    ELEMENT_COLORS,
    PAN_OVERSCAN,
    RARITY_COLORS,
    STANDARD_ART_SIZE,
    apply_panel_mask,
    badge_geometry,
    clear_render_cache,
    cover_resize_offset,
    export_project,
    find_font,
    glow_zoom,
    hex_to_rgba,
    max_offset,
    panel_art,
    panel_background,
    panel_metrics,
    panel_origin,
    panel_polygon,
    panel_target_size,
    render_image,
    render_preview,
    resized_art_size,
)


class CompactLayout(NamedTuple):
    row_height: int
    step: float
    slant: int
    gap: float
    border: float
    panel_width: int


def compact_layout(scale: int = 1) -> CompactLayout:
    """render_image()'s layout numbers for a compact (two-row abyss) canvas,
    taken from the renderer's own helpers so probes follow the layout."""
    row_height, panel_width, slant = panel_metrics(compact=True, scale=scale)
    return CompactLayout(
        row_height=row_height,
        step=BASE_W * scale / 4,
        slant=slant,
        gap=CARD_GAP * scale,
        border=CARD_BORDER * scale,
        panel_width=panel_width,
    )


def create_assets(
    directory: Path,
    names: list[str],
    elements: dict[str, str] | None = None,
    rarities: dict[str, tuple[int | None, int | None]] | None = None,
) -> dict[str, Asset]:
    result = {}
    for index, name in enumerate(names):
        art_path = directory / f"art-{index}.png"
        weapon_path = directory / f"weapon-{index}.png"
        art = Image.new("RGBA", (1200, 900), (25 + index * 10, 70, 100, 255))
        draw = ImageDraw.Draw(art)
        draw.ellipse((250, 80, 950, 850), fill=(130 + index * 8, 180, 220, 255))
        art.save(art_path)
        weapon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        ImageDraw.Draw(weapon).polygon([(128, 10), (190, 220), (128, 190), (66, 220)], fill="white")
        weapon.save(weapon_path)
        rarity, weapon_rarity = (rarities or {}).get(name, (None, None))
        build = Build(
            name=name,
            constellation=index % 7,
            refinement=index % 5 + 1,
            weapon_name="Weapon",
            costume_id=None,
            build_id=str(index),
            build_md5=str(index),
            last_build_update=None,
            art_url="https://example.invalid/art.png",
            weapon_url="https://example.invalid/weapon.png",
            element=(elements or {}).get(name),
            rarity=rarity,
            weapon_rarity=weapon_rarity,
        )
        result[name.casefold()] = Asset(build, art_path, weapon_path)
    return result


def fill_project(project: Project, names: list[str]) -> None:
    for index, member in enumerate(member for team in project.teams for member in team):
        member.name = names[index]


def test_panel_target_size_scales_with_mode_and_scale() -> None:
    assert panel_target_size(compact=True) == (416, 360)
    assert panel_target_size(compact=True, scale=2) == (832, 720)
    assert panel_target_size(compact=False) == (464, 720)
    assert panel_target_size(compact=False, scale=2) == (928, 1440)


def _marker_center_x(image: Image.Image) -> float:
    """Horizontal center of the red marker stripe in a crop's middle row."""
    row = image.height // 2
    columns = [x for x in range(image.width) if image.getpixel((x, row))[0] > 200]
    assert columns, "marker stripe not visible in the crop"
    return (columns[0] + columns[-1]) / 2


def _marked_source() -> Image.Image:
    source = Image.new("RGBA", STANDARD_ART_SIZE, (0, 0, 40, 255))
    center_x = STANDARD_ART_SIZE[0] // 2
    ImageDraw.Draw(source).rectangle(
        (center_x - 20, 0, center_x + 19, STANDARD_ART_SIZE[1] - 1), fill=(255, 0, 0, 255)
    )
    return source


def test_cover_resize_offset_centers_and_pans() -> None:
    source = _marked_source()
    target = panel_target_size(compact=True)

    centered = cover_resize_offset(source, target, 0.0, 0.0, 1.0)
    assert abs(_marker_center_x(centered) - target[0] / 2) <= 1

    # A positive offset moves the visible content right by offset * panel width.
    shifted = cover_resize_offset(source, target, 0.1, 0.0, 1.0)
    assert abs(_marker_center_x(shifted) - _marker_center_x(centered) - 0.1 * target[0]) <= 1

    mirrored = cover_resize_offset(source, target, -0.1, 0.0, 1.0)
    assert abs(_marker_center_x(mirrored) - _marker_center_x(centered) + 0.1 * target[0]) <= 1


def test_max_offset_matches_the_cover_fit_slack_plus_the_overscan() -> None:
    max_x, max_y = max_offset(STANDARD_ART_SIZE, compact=True, zoom=1.06)
    assert abs(max_x - 0.517) < 0.001
    assert abs(max_y - 0.130) < 0.001

    # The crop cannot be panned past the reachable range.
    source = _marked_source()
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


def _marker_center_y(image: Image.Image) -> float:
    """Vertical center of the red marker stripe in a crop's middle column."""
    column = image.width // 2
    rows = [y for y in range(image.height) if image.getpixel((column, y))[0] > 200]
    assert rows, "marker stripe not visible in the crop"
    return (rows[0] + rows[-1]) / 2


def _horizontally_marked_source() -> Image.Image:
    source = Image.new("RGBA", STANDARD_ART_SIZE, (0, 0, 40, 255))
    center_y = STANDARD_ART_SIZE[1] // 2
    ImageDraw.Draw(source).rectangle(
        (0, center_y - 20, STANDARD_ART_SIZE[0] - 1, center_y + 19), fill=(255, 0, 0, 255)
    )
    return source


def _row_alpha(image: Image.Image, y: int) -> set[int]:
    return {image.getpixel((x, y))[3] for x in range(image.width)}


def test_vertical_overscan_pans_past_the_art_edge() -> None:
    zoom = 1.06
    source = _horizontally_marked_source()
    target = panel_target_size(compact=True)
    _, max_y = max_offset(STANDARD_ART_SIZE, compact=True, zoom=zoom)
    resized_h = resized_art_size(STANDARD_ART_SIZE, compact=True, zoom=zoom)[1]
    cover_fit_slack = (resized_h - target[1]) / (2 * target[1])

    centered = cover_resize_offset(source, target, 0.0, 0.0, zoom)
    assert _row_alpha(centered, 0) == {255}
    assert _row_alpha(centered, target[1] - 1) == {255}

    # Panning up runs the crop window off the bottom of the art, panning down
    # off the top; the exposed strip is transparent so the glow shows through.
    panned_up = cover_resize_offset(source, target, 0.0, -max_y, zoom)
    assert _row_alpha(panned_up, target[1] - 1) == {0}
    panned_down = cover_resize_offset(source, target, 0.0, max_y, zoom)
    assert _row_alpha(panned_down, 0) == {0}

    # The travel is well beyond what the bare cover-fit slack allowed.
    travel = _marker_center_y(centered) - _marker_center_y(panned_up)
    assert travel > cover_fit_slack * target[1] + 1
    assert abs(travel - max_y * target[1]) <= 1


def test_default_offsets_still_center_the_crop() -> None:
    source = _marked_source()
    target = panel_target_size(compact=True)
    centered = cover_resize_offset(source, target, 0.0, 0.0, 1.06)
    assert abs(_marker_center_x(centered) - target[0] / 2) <= 1


def gradient_image(width: int, height: int) -> Image.Image:
    # Smooth and different along both axes, so a swapped or inverted axis in
    # the crop mapping changes the output. Deliberately not noise: LANCZOS
    # ringing around isolated pixels makes noise sources differ by ~40/255
    # between an upfront resize and a box resize even when both are correct.
    image = Image.new("RGBA", (width, height))
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            pixels[x, y] = (
                10 + int(200 * x / max(1, width - 1)),
                10 + int(200 * y / max(1, height - 1)),
                10 + int(100 * (x + y) / max(1, width + height - 2)),
                255,
            )
    return image


def reference_cover_resize_offset(
    image: Image.Image,
    size: tuple[int, int],
    offset_x: float,
    offset_y: float,
    zoom: float,
) -> Image.Image:
    """The pre-optimisation implementation: resize the whole image, then crop.

    Image.crop() zero-pads a window that leaves the art, which is what the
    optimised version has to reproduce for the overscanned strip.
    """
    source_w, source_h = image.size
    target_w, target_h = size
    image_scale = max(target_w / source_w, target_h / source_h) * zoom
    resized_w = max(1, int(source_w * image_scale + 0.5))
    resized_h = max(1, int(source_h * image_scale + 0.5))
    limit_x = max(0.0, (resized_w - target_w) / (2 * target_w) + PAN_OVERSCAN)
    limit_y = max(0.0, (resized_h - target_h) / (2 * target_h) + PAN_OVERSCAN)
    offset_x = min(limit_x, max(-limit_x, offset_x))
    offset_y = min(limit_y, max(-limit_y, offset_y))
    resized = image.resize((resized_w, resized_h), Image.Resampling.LANCZOS)
    left = int(round((resized_w - target_w) / 2 - offset_x * target_w))
    top = int(round((resized_h - target_h) / 2 - offset_y * target_h))
    return resized.crop((left, top, left + target_w, top + target_h))


def test_cover_resize_offset_matches_resize_then_crop() -> None:
    # The compact abyss panel size, against a source both larger and smaller
    # than it, so both the downscale and the upscale branch of the cover
    # scaling are covered.
    target = (416, 360)
    for source in (gradient_image(1200, 900), gradient_image(120, 90)):
        for zoom in (0.70, 1.00, 1.80):
            # The outer values are past the reachable range, so the clamp
            # decides the window and it overscans the art by PAN_OVERSCAN.
            for offset_x in (-2.0, -0.3, 0.0, 0.3, 2.0):
                for offset_y in (-2.0, -0.3, 0.0, 0.3, 2.0):
                    case = (source.size, zoom, offset_x, offset_y)
                    result = cover_resize_offset(source, target, offset_x, offset_y, zoom)
                    assert result.size == target, case
                    expected = reference_cover_resize_offset(source, target, offset_x, offset_y, zoom)
                    difference = ImageChops.difference(result, expected)
                    # Resampling the source region directly is not bit-exact
                    # against resizing everything up front, but on smooth
                    # content the two stay within a couple of levels.
                    assert max(band.getextrema()[1] for band in difference.split()) <= 4, case


def test_zoom_scales_both_art_axes_identically() -> None:
    """Zoom is a real zoom: it never changes the art's aspect ratio, not even
    where the scaled art no longer covers the panel."""
    for compact in (True, False):
        for art_size in (STANDARD_ART_SIZE, (1200, 900)):
            for zoom in (0.70, 0.85, 1.00, 1.06, 1.80):
                resized = resized_art_size(art_size, compact=compact, zoom=zoom)
                case = (compact, art_size, zoom, resized)
                source_ratio = art_size[0] / art_size[1]
                # Both axes round independently, so the width may differ from
                # the ratio-implied width by half a pixel per axis, widened here
                # by the ratio the height is compared through.
                assert abs(resized[0] - resized[1] * source_ratio) <= 1 + source_ratio, case


def test_zoom_below_cover_leaves_the_panel_uncovered() -> None:
    """Below zoom 1.0 the 2:1 splash art no longer reaches the panel's top and
    bottom edges. The uncovered strip stays transparent instead of the art
    being stretched to fill it."""
    target = panel_target_size(compact=True)
    source = Image.new("RGBA", STANDARD_ART_SIZE, (0, 0, 40, 255))

    crop = cover_resize_offset(source, target, 0.0, 0.0, 0.85)

    assert _row_alpha(crop, 0) == {0}
    assert _row_alpha(crop, target[1] - 1) == {0}
    assert _row_alpha(crop, target[1] // 2) == {255}


def test_abyss_render_and_export(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    preview = render_preview(project, assets)
    assert preview.size == (1280, 720)
    written = export_project(project, assets, tmp_path / "out")
    assert len(written) == 1
    assert written[0].exists()
    assert written[0].suffix == ".png"
    with Image.open(written[0]) as image:
        assert image.format == "PNG"


def test_export_uses_configured_output_resolution(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    project.output_height = 1440
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    written = export_project(project, assets, tmp_path / "out")
    assert len(written) == 1
    with Image.open(written[0]) as image:
        assert image.size == (2560, 1440)


def test_card_gap_shows_background_between_panels(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    preview = render_preview(project, assets)

    # Boundary between the first row's slot 0 and slot 1 (step = 1280 / 4 = 320),
    # sampled at the row's mid-height where the slanted card edges are centered
    # on the shared boundary. If the gap ever collapsed to zero this pixel
    # would show card art/background glow instead of the near-black canvas.
    pixel = preview.getpixel((320, 180))
    assert isinstance(pixel, tuple)
    assert pixel[:3] == BACKGROUND_COLOR[:3]


def test_element_color_used_for_card_border(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names, elements={names[0]: "Pyro"})
    preview = render_preview(project, assets)

    # The leftmost card's outer edge is inset by only half the border width
    # (commit 4), so a pixel a couple of px in from the canvas edge, at a
    # height clear of the top/bottom corner rounding, lands squarely on the
    # border stroke.
    pixel = preview.getpixel((3, 100))
    assert isinstance(pixel, tuple)
    assert pixel[:3] == hex_to_rgba(ELEMENT_COLORS["pyro"], 255)[:3]


def test_unknown_element_falls_back_to_placement_color(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)  # no elements set -> Build.element is None
    preview = render_preview(project, assets)

    placement_color = project.teams[0][0].color
    pixel = preview.getpixel((3, 100))
    assert isinstance(pixel, tuple)
    assert pixel[:3] == hex_to_rgba(placement_color, 255)[:3]
    # Sanity check the fallback pixel is not coincidentally an element color,
    # so this test would fail if card_color stopped falling back correctly.
    assert pixel[:3] != hex_to_rgba(ELEMENT_COLORS["pyro"], 255)[:3]


def test_stygian_exports_three_files(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(12)]
    project = Project.blank("stygian")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    written = export_project(project, assets, tmp_path / "out")
    assert len(written) == 3
    assert all(path.exists() for path in written)


def test_badge_render_and_geometry_for_long_constellation_string(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    # Not a value the app would normally produce, but the box must not
    # overflow the canvas even for an unusually long "CxRy" string.
    long_string_asset = assets[names[0].casefold()]
    long_string_asset.build.constellation = 10
    long_string_asset.build.refinement = 5

    preview = render_preview(project, assets)
    assert preview.size == (1280, 720)

    # Mirror add_badges' own geometry for the leftmost slot of the first
    # (compact, two-row) abyss team, where a wide box is most likely to
    # push past the canvas edge.
    scale = 1
    compact = True
    row_height, step, *_ = compact_layout(scale)
    font = find_font((38 if compact else 54) * scale)
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    center = int(round(0 * step + step / 2))
    top_y = 0 * row_height + row_height - (68 if compact else 107) * scale
    geometry = badge_geometry(draw, "C10R5", font, center_x=center, top_y=top_y, scale=scale, compact=compact)
    short_geometry = badge_geometry(draw, "C0R1", font, center_x=center, top_y=top_y, scale=scale, compact=compact)

    box_x0, box_y0, box_x1, box_y1 = geometry.box
    circle_x0, circle_y0, circle_x1, circle_y1 = geometry.circle
    assert geometry.group_w > short_geometry.group_w  # content-driven width grows for the longer string
    assert 0 <= box_x0 <= box_x1 <= 1280
    assert 0 <= box_y0 <= box_y1 <= 720
    assert 0 <= circle_x0 <= circle_x1 <= 1280
    assert 0 <= circle_y0 <= circle_y1 <= 720
    assert box_y0 <= geometry.text_center[1] <= box_y1
    assert box_x0 <= geometry.text_center[0] <= box_x1


def _color_present_in_box(
    image: Image.Image, box: tuple[int, int, int, int], color_hex: str, tolerance: int = 40
) -> bool:
    target = hex_to_rgba(color_hex, 255)
    x0, y0, x1, y1 = box
    for y in range(max(0, y0), min(image.height, y1)):
        for x in range(max(0, x0), min(image.width, x1)):
            pixel = image.getpixel((x, y))
            assert isinstance(pixel, tuple)
            if all(abs(pixel[channel] - target[channel]) <= tolerance for channel in range(3)):
                return True
    return False


def test_badge_constellation_and_refinement_use_distinct_rarity_colors(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    # 5-star character, 4-star weapon: two rarities that map to visibly
    # distinct colors (gold vs. purple), unlike the fallback gold-on-gold
    # look this test would silently pass under if both runs still shared
    # one color.
    assets = create_assets(tmp_path, names, rarities={names[0]: (5, 4)})
    preview = render_preview(project, assets)

    # Leftmost slot of the first (compact) abyss row; mirrors the geometry
    # used in the long-string badge test above.
    scale = 1
    compact = True
    row_height, step, *_ = compact_layout(scale)
    font = find_font((38 if compact else 54) * scale)
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    center = int(round(0 * step + step / 2))
    top_y = 0 * row_height + row_height - (68 if compact else 107) * scale
    build = assets[names[0].casefold()].build
    text = f"C{build.constellation}R{build.refinement}"
    geometry = badge_geometry(draw, text, font, center_x=center, top_y=top_y, scale=scale, compact=compact)

    assert _color_present_in_box(preview, geometry.box, RARITY_COLORS[5])
    assert _color_present_in_box(preview, geometry.box, RARITY_COLORS[4])


def test_preview_renders_placeholder_panel_for_missing_asset(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    # Leave the first slot's asset undownloaded; every other slot has one.
    assets = create_assets(tmp_path, names[1:])

    preview = render_preview(project, assets)
    assert preview.size == (1280, 720)

    # A point well inside the first (placeholder) slot, away from borders and
    # the shared-edge gap, mapped from panel-local to canvas coordinates the
    # same way make_panel()/placeholder_panel() paste onto the canvas
    # (index * step - slant, row * row_height).
    slant = compact_layout().slant
    target = panel_target_size(compact=True)
    placeholder_color = project.teams[0][0].color
    expected = panel_background(target, placeholder_color, compact=True)
    local_point = (188, 180)
    canvas_point = (local_point[0] - slant, local_point[1])

    assert preview.getpixel(canvas_point) == expected.getpixel(local_point)[:3]

    # A slot with a real asset still composites character art on top of its
    # background gradient, so its pixel must differ from a plain
    # panel_background-only render at the same local point.
    real_color = project.teams[0][1].color
    plain_background = panel_background(target, real_color, compact=True)
    real_canvas_point = (1 * 320 - slant + local_point[0], local_point[1])
    assert preview.getpixel(real_canvas_point) != plain_background.getpixel(local_point)[:3]


def test_leftmost_slot_is_not_shifted_by_its_negative_panel_origin(tmp_path: Path) -> None:
    """Slot 0's panel origin (index * step - slant) is negative, so its
    panel-sized layer is composited with a source offset instead of a plain
    destination offset. A panel's content depends only on its size, colour,
    placement and art, never on its slot, so giving slot 1 the same asset lets
    its (non-negative origin) rendering pin down slot 0's alignment.

    The art carries a horizontal gradient, without which every probed row
    would be constant and a horizontal shift invisible."""
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    art = Image.new("RGBA", (1200, 900), (0, 0, 0, 255))
    art_draw = ImageDraw.Draw(art)
    for x in range(art.width):
        art_draw.line((x, 0, x, art.height), fill=(x * 255 // art.width, 40, 200, 255))
    art.save(assets[names[0].casefold()].art_path)
    project.teams[0][1].name = project.teams[0][0].name
    project.teams[0][1].color = project.teams[0][0].color

    preview = render_preview(project, assets)

    # Preview geometry for a compact (two-row) abyss team at scale 1.
    row_height, step, slant, _, _, panel_width = compact_layout()
    first_origin_x, _ = panel_origin(0, row=0, row_height=row_height, step=step, slant=slant)
    second_origin_x, _ = panel_origin(1, row=0, row_height=row_height, step=step, slant=slant)
    # Horizontal centre of the panel: well inside both cards, clear of the
    # borders and of the slanted shared edges at every probed height.
    local_x = (panel_width + slant * 2) // 2

    for local_y in (row_height // 4, row_height // 2, 3 * row_height // 4):
        first = preview.getpixel((first_origin_x + local_x, local_y))
        second = preview.getpixel((second_origin_x + local_x, local_y))
        assert first == second, local_y
        # Guard against this becoming vacuous: with `source` dropped, slot 0's
        # panel would be shifted right by `slant`, so the pixel `slant` to the
        # right is exactly what a broken composite would put at `first`. It
        # must therefore differ from the correctly aligned value.
        shifted = preview.getpixel((first_origin_x + local_x + slant, local_y))
        assert shifted != second, local_y


def test_panel_mask_slanted_edge_is_antialiased() -> None:
    """The panel mask itself is supersampled, so a panel's alpha fades across
    its slanted edges instead of stepping straight from 0 to 255.

    The rendered-preview probe below cannot cover this: the opaque border
    stroke is centred on the mask boundary and hides the mask's own edge, so
    aliasing only the mask would go unnoticed there.
    """
    clear_render_cache()  # the mask is cached across tests
    row_height, step, slant, gap, border, panel_width = compact_layout()
    index, row, num_rows, scale = 2, 0, 2, 1
    panel = Image.new("RGBA", (panel_width + 2 * slant, row_height), (255, 255, 255, 255))

    apply_panel_mask(panel, index, row, num_rows, BASE_W, row_height, step, slant, scale)

    points = panel_polygon(index, row, num_rows, BASE_W, row_height, step, slant, gap, border)
    origin_x, _ = panel_origin(index, row, row_height, step, slant)
    alpha = panel.getchannel("A")
    # Both slanted edges, at two heights each, so an edge that only happened to
    # blend at one spot would not pass.
    for top, bottom in ((points[0], points[3]), (points[1], points[2])):
        for y in (60, 300):
            edge_x = top[0] + (bottom[0] - top[0]) * (y - top[1]) / (bottom[1] - top[1]) - origin_x
            window = [alpha.getpixel((x, y)) for x in range(round(edge_x) - 2, round(edge_x) + 3)]
            assert any(0 < value < 255 for value in window), (top, y, window)


def test_slanted_card_edge_is_antialiased(tmp_path: Path) -> None:
    """The slanted card edges and their border strokes are supersampled, so
    crossing one horizontally must show at least one blended pixel between the
    canvas background and the fully opaque border colour. An aliased edge would
    step straight from one to the other."""
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)  # no elements -> placement colours
    preview = render_preview(project, assets)

    # The left edge of the first row's slot 2, which slants across the shared
    # boundary at x = 2 * step. Both the layout numbers and the polygon come
    # from the renderer's own geometry, so the probe follows the layout rather
    # than hard-coded pixels.
    row_height, step, slant, gap, border, _ = compact_layout()
    points = panel_polygon(2, 0, 2, BASE_W, row_height, step, slant, gap, border)
    (top_x, top_y), (bottom_x, bottom_y) = points[0], points[3]
    background = BACKGROUND_COLOR[:3]
    border = hex_to_rgba(project.teams[0][2].color, 255)[:3]

    # Two heights, so a horizontal edge that only happened to be antialiased at
    # one of them would not pass.
    for y in (60, 300):
        edge_x = top_x + (bottom_x - top_x) * (y - top_y) / (bottom_y - top_y)
        run = [(x, preview.getpixel((x, y))) for x in range(round(edge_x) - 8, round(edge_x) + 9)]
        outside = [x for x, pixel in run if pixel == background]
        inside = [x for x, pixel in run if pixel == border]
        assert outside and inside, (y, run)
        last_outside, first_inside = max(outside), min(inside)
        assert last_outside < first_inside, (y, run)
        blended = [preview.getpixel((x, y)) for x in range(last_outside + 1, first_inside)]
        assert blended, (y, run)
        for pixel in blended:
            assert all(
                min(background[channel], border[channel])
                <= pixel[channel]
                <= max(background[channel], border[channel])
                for channel in range(3)
            ), (y, pixel)


def test_glow_shows_through_a_transparent_gap_in_the_character_art(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    # Below 1 / GLOW_ZOOM_FACTOR the glow's floor keeps it near the crop's own
    # framing, so zoom in far enough that the two framings clearly differ.
    for member in (member for team in project.teams for member in team):
        member.zoom = 1.6
    assets = create_assets(tmp_path, names)
    # The glow is only ever visible where the character art is transparent, so
    # give every asset opaque red art with a transparent hole punched into it.
    for asset in assets.values():
        art = Image.new("RGBA", (1200, 900), (255, 40, 40, 255))
        ImageDraw.Draw(art).ellipse((500, 350, 700, 550), fill=(0, 0, 0, 0))
        art.save(asset.art_path)

    preview = render_preview(project, assets)

    # The glow is framed wider than the crop at this zoom, so its hole is
    # smaller. Probe where the character art is transparent but the glow is
    # not, derived from the renderer's own framing rather than from hard-coded
    # pixels, which would depend on the default offsets.
    member = project.teams[0][1]
    target = panel_target_size(compact=True)
    art = Image.open(assets[member.name.casefold()].art_path).convert("RGBA")
    crop = cover_resize_offset(art, target, member.offset_x, member.offset_y, member.zoom)
    glow = cover_resize_offset(
        art, target, member.offset_x, member.offset_y, glow_zoom(member.zoom)
    )
    row = target[1] // 2
    uncovered = [
        x
        for x in range(target[0])
        if crop.getpixel((x, row))[3] == 0 and glow.getpixel((x, row))[3] == 255
    ]
    assert uncovered, "no pixel where the art is transparent but the glow is not"
    local_point = (uncovered[len(uncovered) // 2], row)

    # Mapped to canvas coordinates the same way the panel is pasted
    # (index * step - slant, row * row_height).
    slant = panel_metrics(compact=True)[2]
    canvas_point = (1 * 320 - slant + local_point[0], local_point[1])
    plain_background = panel_background(target, member.color, compact=True)

    pixel = preview.getpixel(canvas_point)
    background_pixel = plain_background.getpixel(local_point)
    assert isinstance(pixel, tuple)
    assert isinstance(background_pixel, tuple)
    assert pixel != background_pixel[:3]
    # The art's red is the only red in this panel, so it can only have reached
    # a pixel the character art does not cover via the blurred glow layer.
    assert pixel[0] > background_pixel[0] + 10


def test_glow_never_leaves_the_panel_uncovered() -> None:
    for zoom in (0.70, 1.00, 1.28, 1.80):
        assert glow_zoom(zoom) >= 1.0
        for compact in (True, False):
            target = panel_target_size(compact)
            resized = resized_art_size(STANDARD_ART_SIZE, compact, glow_zoom(zoom))
            assert resized[0] >= target[0], (zoom, compact, resized, target)
            assert resized[1] >= target[1], (zoom, compact, resized, target)


def test_render_image_requires_complete_assets_by_default(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names[1:])  # missing the first slot's asset

    try:
        render_image(project.teams, assets, compact=True, scale=1)
    except ValueError:
        pass
    else:
        raise AssertionError("Expected render_image() to raise for a missing asset by default")

    try:
        export_project(project, assets, tmp_path / "out")
    except ValueError:
        pass
    else:
        raise AssertionError("Expected export_project() to raise for a missing asset")


def test_weapon_circle_outline_uses_element_color(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names, elements={names[0]: "Pyro"})
    preview = render_preview(project, assets)

    # Same leftmost-slot geometry as the badge tests above, but probing the
    # weapon icon's circle rather than the C/R box.
    scale = 1
    compact = True
    row_height, step, *_ = compact_layout(scale)
    font = find_font((38 if compact else 54) * scale)
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    center = int(round(0 * step + step / 2))
    top_y = 0 * row_height + row_height - (68 if compact else 107) * scale
    build = assets[names[0].casefold()].build
    text = f"C{build.constellation}R{build.refinement}"
    geometry = badge_geometry(draw, text, font, center_x=center, top_y=top_y, scale=scale, compact=compact)

    # Probe a thin strip on the circle's left edge, which is outline only: the
    # weapon icon is thumbnailed and centered, so its own (white) art never
    # reaches this far out.
    circle_x0, circle_y0, _, circle_y1 = geometry.circle
    mid_y = (circle_y0 + circle_y1) // 2
    ring = (circle_x0, mid_y - 2, circle_x0 + 4, mid_y + 2)

    assert _color_present_in_box(preview, ring, ELEMENT_COLORS["pyro"])
    # The outline was plain white before; make sure it no longer is, so this
    # test fails if the element color stops being applied.
    assert not _color_present_in_box(preview, ring, "#ffffff", tolerance=12)


def _patch_counting_open(monkeypatch) -> list[str]:
    """Wrap PIL's Image.open with a call-recording proxy, so a test can
    assert on which paths were (re)opened without mocking away the actual
    decoding (the returned image is still real, from the original open)."""
    opened: list[str] = []
    real_open = Image.open

    def counting_open(fp, *args, **kwargs):
        opened.append(str(fp))
        return real_open(fp, *args, **kwargs)

    monkeypatch.setattr(renderer.Image, "open", counting_open)
    return opened


def _patch_counting_panels(monkeypatch) -> list[str]:
    """Wrap the panel builders with call-recording proxies, so a test can
    assert how many panels were actually composited rather than served from
    the panel cache. Image.open counts cannot show this, since the art and
    weapon-icon caches absorb every decode after the first render.

    render_image() resolves both builders as module globals at call time, so
    patching them on the module takes effect for renders already in flight."""
    built: list[str] = []
    real_make_panel = renderer.make_panel
    real_placeholder_panel = renderer.placeholder_panel

    def counting_make_panel(*args, **kwargs):
        built.append("make_panel")
        return real_make_panel(*args, **kwargs)

    def counting_placeholder_panel(*args, **kwargs):
        built.append("placeholder_panel")
        return real_placeholder_panel(*args, **kwargs)

    monkeypatch.setattr(renderer, "make_panel", counting_make_panel)
    monkeypatch.setattr(renderer, "placeholder_panel", counting_placeholder_panel)
    return built


def test_repeated_render_reuses_panel_cache(tmp_path, monkeypatch) -> None:
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


def test_changing_one_placement_only_recomputes_that_slot(tmp_path, monkeypatch) -> None:
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


def test_clear_render_cache_forces_full_recompute(tmp_path, monkeypatch) -> None:
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
    assert renderer._art_cache
    assert renderer._work_cache  # 1200x900 art downscales for a preview panel
    assert renderer._mask_cache
    assert renderer._border_cache

    clear_render_cache()
    assert not renderer._art_cache
    assert not renderer._work_cache
    assert not renderer._mask_cache
    assert not renderer._border_cache


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

    render_preview(project, assets)

    assert len(renderer._badge_cache) == 1

    clear_render_cache()
    assert not renderer._badge_cache


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
    # A pinned element fixes the card colour across slots, so the only thing
    # varying below is the badge text itself.
    assets = create_assets(tmp_path, [name], elements={name: "Pyro"})
    asset = assets[name.casefold()]

    def render_with(constellation: int, refinement: int) -> Image.Image:
        # Same tmp_path, hence the same weapon path, and no clear_render_cache()
        # in between: all three renders share one warm _badge_cache.
        assets[name.casefold()] = Asset(
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
    swap_slots GUI feature does) would reuse the other slot's stale,
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


TWO_TONE_LEFT = (220, 40, 40, 255)
TWO_TONE_RIGHT = (40, 40, 220, 255)


def two_tone_art() -> Image.Image:
    """Art the same size create_assets() writes, but horizontally asymmetric:
    red left half, blue right half.

    create_assets()' own ellipse is symmetric about the art's centre, so a
    mirrored crop of it is indistinguishable from an unmirrored one.
    """
    art = Image.new("RGBA", (1200, 900), TWO_TONE_LEFT)
    ImageDraw.Draw(art).rectangle((600, 0, 1199, 899), fill=TWO_TONE_RIGHT)
    return art


def _two_tone_project(tmp_path: Path) -> tuple[Project, dict[str, Asset]]:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    for asset in assets.values():
        two_tone_art().save(asset.art_path)
    return project, assets


def _reddish(pixel: tuple[int, ...]) -> bool:
    """Whether a probe leans towards the art's red half. Compares the channels
    rather than exact values, since the renderer applies colour/contrast
    enhancement, a card tint and a shade gradient on top of the art."""
    return pixel[0] > pixel[2]


def test_flip_mirrors_the_panel_art(tmp_path: Path) -> None:
    project, assets = _two_tone_project(tmp_path)
    member = project.teams[0][1]
    member.offset_x = 0.0

    # Two probes symmetric about the mirror axis, which is the centre of the
    # panel-sized art crop, not of the (narrower) visible card. Row 0 slot 1 is
    # used because its panel origin is non-negative, so it is not clipped.
    row_height, step, slant, _, _, _ = compact_layout()
    origin_x, _ = panel_origin(1, row=0, row_height=row_height, step=step, slant=slant)
    target = panel_target_size(compact=True)
    center_x = origin_x + target[0] // 2
    # 60px clears the slanted edges (the card spans step-wide at mid-height),
    # and mid-height is below the top shade gradient and above the badge.
    left_probe = (center_x - 60, row_height // 2)
    right_probe = (center_x + 60, row_height // 2)

    clear_render_cache()
    unflipped = render_preview(project, assets)
    assert _reddish(unflipped.getpixel(left_probe))
    assert not _reddish(unflipped.getpixel(right_probe))

    member.flip = True
    clear_render_cache()
    flipped = render_preview(project, assets)
    assert not _reddish(flipped.getpixel(left_probe))
    assert _reddish(flipped.getpixel(right_probe))


def _tone_boundary_x(crop: Image.Image) -> float:
    """The x of the single red/blue transition in the crop's middle row.

    A rigid feature of the two-tone art, unlike a per-colour pixel count, which
    also changes as a region is clipped at a panel edge.
    """
    row = crop.height // 2
    pixels = [crop.getpixel((x, row)) for x in range(crop.width)]
    reds = [x for x, pixel in enumerate(pixels) if pixel[3] and pixel[0] > pixel[2]]
    blues = [x for x, pixel in enumerate(pixels) if pixel[3] and pixel[2] > pixel[0]]
    assert reds and blues, "both tones must be visible in the crop"
    if reds[0] < blues[0]:
        return (reds[-1] + blues[0]) / 2
    return (blues[-1] + reds[0]) / 2


def test_flip_keeps_the_horizontal_drag_direction() -> None:
    """Increasing offset_x must move the visible content right whether or not
    the placement is flipped, so dragging keeps following the mouse."""
    art = two_tone_art()
    target = panel_target_size(compact=True)

    shifts = {}
    for flip in (False, True):
        member = Placement(offset_y=0.0, flip=flip)
        centered = panel_art(art, target, member, member.zoom)
        member.offset_x = 0.2
        shifted = panel_art(art, target, member, member.zoom)
        shifts[flip] = _tone_boundary_x(shifted) - _tone_boundary_x(centered)
        assert shifts[flip] > 0, flip
        assert abs(shifts[flip] - 0.2 * target[0]) <= 2, flip

    assert abs(shifts[True] - shifts[False]) <= 2


def test_flip_preserves_the_framing() -> None:
    """"Mirror the artwork, change nothing else" as an assertion: the flipped
    crop shows the mirror image of the unflipped one, so what was red in the
    latter is blue in the former and vice versa."""
    art = two_tone_art()
    target = panel_target_size(compact=True)

    def tone_counts(crop: Image.Image) -> tuple[int, int]:
        """How many pixels of the crop lean red and how many lean blue.

        The clipping subtract leaves 0 wherever a channel does not dominate,
        which also covers the transparent overscan strip, whose pixels are
        fully zeroed.
        """
        red_band, _, blue_band, _ = crop.split()
        red = sum(ImageChops.subtract(red_band, blue_band).histogram()[1:])
        blue = sum(ImageChops.subtract(blue_band, red_band).histogram()[1:])
        return red, blue

    unflipped_red, unflipped_blue = tone_counts(
        panel_art(art, target, Placement(offset_x=0.2, offset_y=0.0), 1.06)
    )
    flipped_red, flipped_blue = tone_counts(
        panel_art(art, target, Placement(offset_x=0.2, offset_y=0.0, flip=True), 1.06)
    )

    # A tolerance of a couple of pixel columns absorbs the integer rounding of
    # the crop window.
    tolerance = 2 * target[1]
    assert abs(flipped_red - unflipped_blue) <= tolerance
    assert abs(flipped_blue - unflipped_red) <= tolerance
    # Not a vacuous comparison: the two tones do not cover equal areas here.
    assert abs(unflipped_red - unflipped_blue) > tolerance


def test_flip_is_part_of_the_panel_cache_key(tmp_path: Path) -> None:
    """Regression test: flipping a placement must not be masked by the cached
    panel of its unflipped self."""
    clear_render_cache()
    project, assets = _two_tone_project(tmp_path)

    unflipped = render_preview(project, assets)
    project.teams[0][1].flip = True
    flipped = render_preview(project, assets)  # deliberately no cache clear

    assert ImageChops.difference(unflipped, flipped).getbbox() is not None
