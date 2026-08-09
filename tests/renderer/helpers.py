"""Helpers shared by more than one of the renderer test modules."""

from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageDraw

from genshin_thumbnail_studio.models import Asset, Build, Project
from genshin_thumbnail_studio.renderer.geometry import (
    BASE_W,
    CARD_BORDER,
    CARD_GAP,
    STANDARD_ART_SIZE,
    panel_metrics,
)


def rgb(image: Image.Image, xy: tuple[int, int]) -> tuple[int, int, int]:
    """Pixel read for RGB images (e.g. the final composited preview), narrowed
    past `Image.getpixel`'s `float | tuple[int, ...] | None` return type."""
    pixel = image.getpixel(xy)
    assert isinstance(pixel, tuple) and len(pixel) == 3
    return (pixel[0], pixel[1], pixel[2])


def rgba(image: Image.Image, xy: tuple[int, int]) -> tuple[int, int, int, int]:
    """Pixel read for RGBA images (art crops, panel backgrounds, badge tiles),
    narrowed past `Image.getpixel`'s `float | tuple[int, ...] | None` return type."""
    pixel = image.getpixel(xy)
    assert isinstance(pixel, tuple) and len(pixel) == 4
    return (pixel[0], pixel[1], pixel[2], pixel[3])


def gray(image: Image.Image, xy: tuple[int, int]) -> int:
    """Pixel read for single-band images (an alpha channel or a coverage mask),
    narrowed past `Image.getpixel`'s `float | tuple[int, ...] | None` return type."""
    pixel = image.getpixel(xy)
    assert isinstance(pixel, int)
    return pixel


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
    """One asset per name, keyed by `Build.key` the way the editor keys them."""
    result: dict[str, Asset] = {}
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
            art_url="https://example.invalid/art.png",
            weapon_url="https://example.invalid/weapon.png",
            element=(elements or {}).get(name),
            rarity=rarity,
            weapon_rarity=weapon_rarity,
        )
        result[build.key] = Asset(build, art_path, weapon_path)
    return result


def asset_key(name: str) -> str:
    """The key `create_assets()` files a character's art under: `Build.key` for
    that character's live build."""
    return live_build(name).key


def live_build(name: str) -> Build:
    """The minimal live build a placement carries in these tests.

    The renderer resolves a slot's art through `Placement.asset_key` alone, so a
    placement needs a build whose `key` matches the one `create_assets()` filed
    that character's art under.
    """
    return Build(
        name=name,
        constellation=0,
        refinement=1,
        weapon_name="Weapon",
        costume_id=None,
        art_url="https://example.invalid/art.png",
        weapon_url="https://example.invalid/weapon.png",
    )


def fill_project(project: Project, names: list[str]) -> None:
    for index, member in enumerate(member for team in project.teams for member in team):
        member.name = names[index]
        member.build = live_build(names[index])


def marked_source() -> Image.Image:
    source = Image.new("RGBA", STANDARD_ART_SIZE, (0, 0, 40, 255))
    center_x = STANDARD_ART_SIZE[0] // 2
    ImageDraw.Draw(source).rectangle(
        (center_x - 20, 0, center_x + 19, STANDARD_ART_SIZE[1] - 1), fill=(255, 0, 0, 255)
    )
    return source


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


def two_tone_project(tmp_path: Path) -> tuple[Project, dict[str, Asset]]:
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    fill_project(project, names)
    assets = create_assets(tmp_path, names)
    for asset in assets.values():
        two_tone_art().save(asset.art_path)
    return project, assets
