"""Tests for `renderer.badges`."""

import threading
import time
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from genshin_thumbnail_studio.models import Project
from genshin_thumbnail_studio.renderer import badges as render_badges_module
from genshin_thumbnail_studio.renderer.badges import badge_geometry, badge_tile, badge_tile_origin, find_font
from genshin_thumbnail_studio.renderer.colors import ELEMENT_COLORS, RARITY_COLORS, hex_to_rgba
from genshin_thumbnail_studio.renderer.compose import render_preview

from .helpers import compact_layout, create_assets, fill_project, gray, rgb, rgba


def test_badge_render_and_geometry_for_long_constellation_string(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    builds = create_assets(tmp_path, names)
    fill_project(project, builds)
    # Not a value the app would normally produce, but the box must not
    # overflow the canvas even for an unusually long "CxRy" string.
    builds[0].constellation = 10
    builds[0].refinement = 5

    preview = render_preview(project, tmp_path)
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
    center = round(0 * step + step / 2)
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
    # 5-star character, 4-star weapon: two rarities that map to visibly
    # distinct colors (gold vs. purple), unlike the fallback gold-on-gold
    # look this test would silently pass under if both runs still shared
    # one color.
    builds = create_assets(tmp_path, names, rarities={names[0]: (5, 4)})
    fill_project(project, builds)
    preview = render_preview(project, tmp_path)

    # Leftmost slot of the first (compact) abyss row; mirrors the geometry
    # used in the long-string badge test above.
    scale = 1
    compact = True
    row_height, step, *_ = compact_layout(scale)
    font = find_font((38 if compact else 54) * scale)
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    center = round(0 * step + step / 2)
    top_y = 0 * row_height + row_height - (68 if compact else 107) * scale
    build = builds[0]
    text = f"C{build.constellation}R{build.refinement}"
    geometry = badge_geometry(draw, text, font, center_x=center, top_y=top_y, scale=scale, compact=compact)

    assert _color_present_in_box(preview, geometry.box, RARITY_COLORS[5])
    assert _color_present_in_box(preview, geometry.box, RARITY_COLORS[4])


def test_weapon_circle_outline_uses_element_color(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    builds = create_assets(tmp_path, names, elements={names[0]: "Pyro"})
    fill_project(project, builds)
    preview = render_preview(project, tmp_path)

    # Same leftmost-slot geometry as the badge tests above, but probing the
    # weapon icon's circle rather than the C/R box.
    scale = 1
    compact = True
    row_height, step, *_ = compact_layout(scale)
    font = find_font((38 if compact else 54) * scale)
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    center = round(0 * step + step / 2)
    top_y = 0 * row_height + row_height - (68 if compact else 107) * scale
    build = builds[0]
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


def test_weapon_icon_visible_content_is_centered_in_the_circle_despite_source_padding(
    tmp_path: Path,
) -> None:
    # Diagnosis: badge_tile() centers the weapon icon using the thumbnailed
    # icon's own width/height, i.e. its full source canvas including
    # transparent padding, rather than the visible art's bounding box. Enka
    # weapon PNGs aren't reliably centered on their own canvas, so uneven
    # padding shifts the visible art off-center inside the circle. A
    # manufactured 71x71 opaque square at (20, 20) on a 256x256 canvas
    # (padded 20px left/top, ~165px right/bottom) was measured to render
    # with the circle centered at (234, 321) but the visible content
    # centered at (220, 307) - a 14px miss on both axes.
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    builds = create_assets(tmp_path, names)
    fill_project(project, builds)

    weapon_path = builds[0].weapon_path(tmp_path)
    weapon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    ImageDraw.Draw(weapon).rectangle((20, 20, 90, 90), fill=(255, 0, 255, 255))
    weapon.save(weapon_path)

    preview = render_preview(project, tmp_path)

    # Same leftmost-slot geometry as the badge tests above.
    scale = 1
    compact = True
    row_height, step, *_ = compact_layout(scale)
    font = find_font((38 if compact else 54) * scale)
    canvas = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    center = round(0 * step + step / 2)
    top_y = 0 * row_height + row_height - (68 if compact else 107) * scale
    build = builds[0]
    text = f"C{build.constellation}R{build.refinement}"
    geometry = badge_geometry(draw, text, font, center_x=center, top_y=top_y, scale=scale, compact=compact)

    circle_x0, circle_y0, circle_x1, circle_y1 = geometry.circle
    target = (255, 0, 255)
    tolerance = 10
    xs: list[int] = []
    ys: list[int] = []
    for y in range(circle_y0, circle_y1 + 1):
        for x in range(circle_x0, circle_x1 + 1):
            pixel = rgb(preview, (x, y))
            if all(abs(pixel[channel] - target[channel]) <= tolerance for channel in range(3)):
                xs.append(x)
                ys.append(y)

    # Sanity check: the icon rendered at all.
    assert xs

    content_center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    circle_center = ((circle_x0 + circle_x1) / 2, (circle_y0 + circle_y1) / 2)

    assert abs(content_center[0] - circle_center[0]) <= 1.5
    assert abs(content_center[1] - circle_center[1]) <= 1.5


def _has_partial_coverage(coverage: Image.Image, box: tuple[int, int, int, int]) -> bool:
    """Whether any pixel in the inclusive `box` is only partially covered,
    i.e. antialiased. The box is inclusive to match Pillow's shape coordinates,
    which is where the callers take their probe regions from."""
    x0, y0, x1, y1 = box
    return any(
        0 < gray(coverage, (x, y)) < 255
        for y in range(max(0, y0), min(coverage.height, y1 + 1))
        for x in range(max(0, x0), min(coverage.width, x1 + 1))
    )


def test_badge_shape_edges_are_antialiased(tmp_path: Path) -> None:
    names = ["Character 0"]
    build = create_assets(tmp_path, names, elements={names[0]: "Pyro"})[0]

    # Same leftmost-slot geometry as the badge tests above.
    scale = 1
    compact = True
    row_height, step, *_ = compact_layout(scale)
    font = find_font((38 if compact else 54) * scale)
    draw = ImageDraw.Draw(Image.new("RGBA", (1280, 720), (0, 0, 0, 0)))
    center = round(0 * step + step / 2)
    top_y = 0 * row_height + row_height - (68 if compact else 107) * scale
    text = f"C{build.constellation}R{build.refinement}"
    geometry = badge_geometry(draw, text, font, center_x=center, top_y=top_y, scale=scale, compact=compact)

    tile, coverage = badge_tile(
        geometry, build, build.weapon_path(tmp_path), ELEMENT_COLORS["pyro"], font, scale, compact
    )

    origin_x, origin_y = badge_tile_origin(geometry)
    box_x0, box_y0, box_x1, box_y1 = (
        geometry.box[0] - origin_x,
        geometry.box[1] - origin_y,
        geometry.box[2] - origin_x,
        geometry.box[3] - origin_y,
    )
    circle_x0, circle_y0, circle_x1, circle_y1 = (
        geometry.circle[0] - origin_x,
        geometry.circle[1] - origin_y,
        geometry.circle[2] - origin_x,
        geometry.circle[3] - origin_y,
    )
    corner_radius = 14 * scale

    assert _has_partial_coverage(
        coverage, (box_x0, box_y0, box_x0 + corner_radius, box_y0 + corner_radius)
    )
    # The circle's left edge is vertical at its middle, so the partially
    # covered pixels sit above and below that point.
    assert _has_partial_coverage(coverage, (circle_x0, circle_y0, circle_x0 + 2, circle_y1))

    assert gray(coverage, ((box_x0 + box_x1) // 2, (box_y0 + box_y1) // 2)) == 255
    # Above the box's top edge and left of the circle: no shape reaches here.
    assert gray(coverage, (box_x0, 0)) == 0

    # add_badges() blends the tile onto the card through this very coverage, so
    # a partially covered pixel must still hold the shape's own colour. A tile
    # scaled by the coverage as well would fade every antialiased edge toward
    # black instead of into the card art.
    partial_ring_pixels = [
        (x, y)
        for y in range(circle_y0, circle_y0 + 4)
        for x in range(circle_x0, circle_x1 + 1)
        if 0 < gray(coverage, (x, y)) < 255
    ]
    assert partial_ring_pixels
    ring_color = hex_to_rgba(ELEMENT_COLORS["pyro"], 240)
    assert all(rgba(tile, pixel) == ring_color for pixel in partial_ring_pixels)


def test_add_badges_serializes_font_use_across_threads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The FreeTypeFont find_font() memoizes is shared by the preview worker
    thread and the exporting GUI thread, and Pillow does not document measuring
    or drawing with one font from two threads at once as safe. add_badges() must
    therefore hold _font_lock across its whole font-using span, so at most one
    thread is ever inside it."""
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, create_assets(tmp_path, names))

    probe_lock = threading.Lock()
    inside = 0
    max_inside = 0

    def probing_find_font(size: int):
        nonlocal inside, max_inside
        with probe_lock:
            inside += 1
            max_inside = max(max_inside, inside)
        try:
            font = find_font(size)
            # Sleep while still counted as "inside" to widen the window in which
            # an unserialized second thread would be observed.
            time.sleep(0.02)
            return font
        finally:
            with probe_lock:
                inside -= 1

    monkeypatch.setattr(render_badges_module, "find_font", probing_find_font)

    failures: list[BaseException] = []

    def render() -> None:
        try:
            render_preview(project, tmp_path)
        except BaseException as error:  # re-raised in the main thread
            failures.append(error)

    threads = [threading.Thread(target=render) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failures
    assert max_inside == 1
