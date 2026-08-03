from pathlib import Path

from PIL import Image, ImageDraw

from genshin_thumbnail_studio.models import Asset, Build, Project
from genshin_thumbnail_studio.renderer import (
    BACKGROUND_COLOR,
    ELEMENT_COLORS,
    badge_geometry,
    export_project,
    find_font,
    hex_to_rgba,
    render_preview,
)


def create_assets(
    directory: Path, names: list[str], elements: dict[str, str] | None = None
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
        )
        result[name.casefold()] = Asset(build, art_path, weapon_path)
    return result


def fill_project(project: Project, names: list[str]) -> None:
    for index, member in enumerate(member for team in project.teams for member in team):
        member.name = names[index]


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
