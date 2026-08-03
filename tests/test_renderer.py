from pathlib import Path

from PIL import Image, ImageDraw

from genshin_thumbnail_studio import renderer
from genshin_thumbnail_studio.models import Asset, Build, Project
from genshin_thumbnail_studio.renderer import (
    BACKGROUND_COLOR,
    ELEMENT_COLORS,
    PAN_OVERSCAN,
    RARITY_COLORS,
    STANDARD_ART_SIZE,
    badge_geometry,
    clear_render_cache,
    cover_resize_offset,
    export_project,
    find_font,
    hex_to_rgba,
    max_offset,
    panel_background,
    panel_target_size,
    render_image,
    render_preview,
    resized_art_size,
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
    row_height = 360
    step = 320.0
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
    row_height = 360
    step = 320.0
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
    panel_width, slant, row_height = 340, 38, 360
    target = (panel_width + slant * 2, row_height)
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
    row_height = 360
    step = 320.0
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


def test_repeated_render_reuses_panel_cache(tmp_path, monkeypatch) -> None:
    clear_render_cache()
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)

    opened = _patch_counting_open(monkeypatch)
    first = render_preview(project, assets)
    assert opened  # sanity: the first render actually opened art/weapon files

    opened.clear()
    second = render_preview(project, assets)

    assert opened == []  # nothing reopened: every panel/icon was cache hit
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
    render_preview(project, assets)

    changed_art_path = str(assets[names[0].casefold()].art_path)
    untouched_art_paths = {str(assets[name.casefold()].art_path) for name in names[1:]}
    assert changed_art_path in opened
    assert not (untouched_art_paths & set(opened))


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

    all_art_paths = {str(asset.art_path) for asset in assets.values()}
    assert all_art_paths <= set(opened)


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
