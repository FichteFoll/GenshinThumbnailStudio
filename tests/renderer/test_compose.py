"""Tests for `renderer.compose`."""

from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw

from genshin_thumbnail_studio.models import Asset, Build, Project
from genshin_thumbnail_studio.renderer.compose import export_project, render_image, render_preview

from .helpers import compact_layout, create_assets, fill_project


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


def test_stygian_exports_three_files(tmp_path: Path) -> None:
    names = [f"Character {index}" for index in range(12)]
    project = Project.blank("stygian")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    written = export_project(project, assets, tmp_path / "out")
    assert len(written) == 3
    assert all(path.exists() for path in written)


def _weapon_icon(path: Path, square: bool) -> None:
    icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    if square:
        draw.rectangle((40, 40, 215, 215), fill="white")
    else:
        draw.polygon([(128, 10), (190, 220), (128, 190), (66, 220)], fill="white")
    icon.save(path)


def test_two_builds_of_one_character_render_their_own_weapon_badge(tmp_path: Path) -> None:
    """The art dict is keyed by character *and* build, and so is the panel cache.

    Two slots holding different builds of one character differ only in their
    weapon icon here. Looking assets up by the bare character name would give
    both slots the same asset, and a render cache keyed by the name alone would
    serve the first slot's panel to the second.
    """
    art_path = tmp_path / "furina.png"
    art = Image.new("RGBA", (1200, 900), (25, 70, 100, 255))
    ImageDraw.Draw(art).ellipse((250, 80, 950, 850), fill=(130, 180, 220, 255))
    art.save(art_path)
    live_weapon = tmp_path / "weapon-live.png"
    saved_weapon = tmp_path / "weapon-saved.png"
    _weapon_icon(live_weapon, square=False)
    _weapon_icon(saved_weapon, square=True)

    live = Build(
        name="Furina",
        constellation=2,
        refinement=3,
        weapon_name="Splendor of Tranquil Waters",
        costume_id=None,
        art_url="https://example.invalid/art.png",
        weapon_url="https://example.invalid/live-weapon.png",
        element="Hydro",
        rarity=5,
        weapon_rarity=5,
    )
    saved = replace(live, build_name="Bow DPS", build_id="7", weapon_name="Favonius Sword")
    assets = {
        live.key: Asset(live, art_path, live_weapon),
        saved.key: Asset(saved, art_path, saved_weapon),
    }
    project = Project.blank("abyss")
    first, second = project.teams[0][0], project.teams[0][1]
    for member, build in ((first, live), (second, saved)):
        member.name = "Furina"
        member.build = build
        # The same colour in both slots, so the build is the only thing the two
        # panels can differ by.
        member.color = "#78d7ff"

    image = render_image(project.teams, assets, compact=True, scale=1, require_complete=False)

    # A window around each slot's badge, narrow enough that no neighbouring
    # panel reaches into it, so the two crops are congruent by construction.
    layout = compact_layout()
    badges = [
        image.crop(
            (
                round(index * layout.step + layout.step / 2) - 100,
                layout.row_height - 75,
                round(index * layout.step + layout.step / 2) + 100,
                layout.row_height - 5,
            )
        )
        for index in (0, 1)
    ]
    assert badges[0].tobytes() != badges[1].tobytes()


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
