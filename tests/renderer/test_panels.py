from pathlib import Path

from PIL import Image, ImageDraw

from genshin_thumbnail_studio.models import Asset, Project
from genshin_thumbnail_studio.renderer.art import cover_resize_offset, glow_zoom
from genshin_thumbnail_studio.renderer.cache import clear_render_cache
from genshin_thumbnail_studio.renderer.colors import ELEMENT_COLORS, hex_to_rgba
from genshin_thumbnail_studio.renderer.compose import render_preview
from genshin_thumbnail_studio.renderer.geometry import (
    BACKGROUND_COLOR,
    BASE_W,
    panel_metrics,
    panel_origin,
    panel_polygon,
    panel_target_size,
)
from genshin_thumbnail_studio.renderer.panels import apply_panel_mask, panel_background

from .helpers import compact_layout, create_assets, fill_project, gray, rgb, rgba, two_tone_project


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

    assert rgb(preview, canvas_point) == rgba(expected, local_point)[:3]

    # A slot with a real asset still composites character art on top of its
    # background gradient, so its pixel must differ from a plain
    # panel_background-only render at the same local point.
    real_color = project.teams[0][1].color
    plain_background = panel_background(target, real_color, compact=True)
    real_canvas_point = (1 * 320 - slant + local_point[0], local_point[1])
    assert rgb(preview, real_canvas_point) != rgba(plain_background, local_point)[:3]


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
            window = [gray(alpha, (x, y)) for x in range(round(edge_x) - 2, round(edge_x) + 3)]
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
        run = [(x, rgb(preview, (x, y))) for x in range(round(edge_x) - 8, round(edge_x) + 9)]
        outside = [x for x, pixel in run if pixel == background]
        inside = [x for x, pixel in run if pixel == border]
        assert outside and inside, (y, run)
        last_outside, first_inside = max(outside), min(inside)
        assert last_outside < first_inside, (y, run)
        blended = [rgb(preview, (x, y)) for x in range(last_outside + 1, first_inside)]
        assert blended, (y, run)
        for pixel in blended:
            assert all(
                min(background[channel], border[channel])
                <= pixel[channel]
                <= max(background[channel], border[channel])
                for channel in range(3)
            ), (y, pixel)


def _punch_a_transparent_hole(assets: dict[str, Asset]) -> None:
    """Give every asset opaque red art with a transparent hole in it.

    The glow is only ever visible where the character art is transparent, and
    the art's red is then the only red in the panel, so a red pixel outside the
    art can only have arrived through the blurred glow layer.
    """
    for asset in assets.values():
        art = Image.new("RGBA", (1200, 900), (255, 40, 40, 255))
        ImageDraw.Draw(art).ellipse((500, 350, 700, 550), fill=(0, 0, 0, 0))
        art.save(asset.art_path)


def test_glow_shows_through_a_transparent_gap_in_the_character_art(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    # Below 1 / GLOW_ZOOM_FACTOR the glow's floor keeps it near the crop's own
    # framing, so zoom in far enough that the two framings clearly differ.
    for member in (member for team in project.teams for member in team):
        member.zoom = 1.6
    assets = create_assets(tmp_path, names)
    _punch_a_transparent_hole(assets)

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
        if rgba(crop, (x, row))[3] == 0 and rgba(glow, (x, row))[3] == 255
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


def test_glow_reaches_into_a_transparent_gap_at_the_default_zoom(tmp_path: Path) -> None:
    """The floored glow zoom deserves its own probe, since it is what a fresh
    project renders with. There the glow is framed exactly like the crop, so a
    gap in the art is a gap in the glow as well, and only the glow layer's own
    softness reaches into it: it is built at a quarter of the panel resolution,
    blurred and resampled back up, which carries colour a little way past the
    gap's rim without filling its middle. Filling it is what the wider framing
    above 1 / GLOW_ZOOM_FACTOR is for.
    """
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    _punch_a_transparent_hole(assets)

    member = project.teams[0][1]
    assert glow_zoom(member.zoom) == 1.0, "the default zoom has to exercise the floor"

    preview = render_preview(project, assets)

    target = panel_target_size(compact=True)
    art = Image.open(assets[member.name.casefold()].art_path).convert("RGBA")
    crop = cover_resize_offset(art, target, member.offset_x, member.offset_y, member.zoom)
    row = target[1] // 2
    gap = [x for x in range(target[0]) if rgba(crop, (x, row))[3] == 0]
    assert gap, "no pixel where the character art is transparent"

    slant = panel_metrics(compact=True)[2]
    plain_background = panel_background(target, member.color, compact=True)

    def red_over_the_bare_panel(x: int) -> float:
        """How much redder the render is at `x` than the panel would be without
        any glow, mapped to canvas coordinates the way the panel is pasted."""
        pixel = preview.getpixel((1 * 320 - slant + x, row))
        background_pixel = plain_background.getpixel((x, row))
        assert isinstance(pixel, tuple)
        assert isinstance(background_pixel, tuple)
        return pixel[0] - background_pixel[0]

    assert red_over_the_bare_panel(gap[0]) > 20
    assert red_over_the_bare_panel(gap[-1]) > 20
    assert red_over_the_bare_panel(gap[len(gap) // 2]) < 10


def _reddish(pixel: tuple[int, ...]) -> bool:
    """Whether a probe leans towards the art's red half. Compares the channels
    rather than exact values, since the renderer applies colour/contrast
    enhancement, a card tint and a shade gradient on top of the art."""
    return pixel[0] > pixel[2]


def test_flip_mirrors_the_panel_art(tmp_path: Path) -> None:
    project, assets = two_tone_project(tmp_path)
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
    assert _reddish(rgb(unflipped, left_probe))
    assert not _reddish(rgb(unflipped, right_probe))

    member.flip = True
    clear_render_cache()
    flipped = render_preview(project, assets)
    assert not _reddish(rgb(flipped, left_probe))
    assert _reddish(rgb(flipped, right_probe))
