"""Helpers shared by more than one of the renderer test modules."""

from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageDraw

from genshin_thumbnail_studio.models import Build, Project
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


def make_builds(
    names: list[str],
    elements: dict[str, str] | None = None,
    rarities: dict[str, tuple[int | None, int | None]] | None = None,
) -> list[Build]:
    """One live build per name, no files written.

    Each build gets art and weapon URLs of its own, so that no two builds
    resolve to the same cached path - which is the only thing that tells two
    slots' art apart now.
    """
    builds: list[Build] = []
    for index, name in enumerate(names):
        rarity, weapon_rarity = (rarities or {}).get(name, (None, None))
        builds.append(
            Build(
                name=name,
                constellation=index % 7,
                refinement=index % 5 + 1,
                weapon_name="Weapon",
                costume_id=None,
                build_id=str(index),
                art_url=f"https://example.invalid/{index}-art.png",
                weapon_url=f"https://example.invalid/{index}-weapon.png",
                element=(elements or {}).get(name),
                rarity=rarity,
                weapon_rarity=weapon_rarity,
            )
        )
    return builds


def publish(root: Path, builds: list[Build]) -> None:
    """Write each build's art and weapon image where the build says they belong.

    That, and nothing else, is what makes a slot framed with one of these builds
    render as a portrait rather than as a placeholder.
    """
    for index, build in enumerate(builds):
        art_path = build.art_path(root)
        art_path.parent.mkdir(parents=True, exist_ok=True)
        art = Image.new("RGBA", (1200, 900), (25 + index * 10, 70, 100, 255))
        ImageDraw.Draw(art).ellipse((250, 80, 950, 850), fill=(130 + index * 8, 180, 220, 255))
        art.save(art_path)
        weapon_path = build.weapon_path(root)
        weapon_path.parent.mkdir(parents=True, exist_ok=True)
        weapon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        ImageDraw.Draw(weapon).polygon([(128, 10), (190, 220), (128, 190), (66, 220)], fill="white")
        weapon.save(weapon_path)


def create_assets(
    root: Path,
    names: list[str],
    elements: dict[str, str] | None = None,
    rarities: dict[str, tuple[int | None, int | None]] | None = None,
) -> list[Build]:
    """One build per name, with its files published under the cache root `root`."""
    builds = make_builds(names, elements, rarities)
    publish(root, builds)
    return builds


def fill_project(project: Project, builds: list[Build]) -> None:
    """Frame each slot with one of `builds`, in order."""
    for index, member in enumerate(member for team in project.teams for member in team):
        member.name = builds[index].name
        member.build = builds[index]


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


def two_tone_project(tmp_path: Path) -> tuple[Project, Path]:
    """A filled abyss project and the cache root its builds' art was published
    under, every portrait replaced by the two-tone art."""
    names = [f"Character {index}" for index in range(8)]
    project = Project.blank("abyss")
    builds = create_assets(tmp_path, names)
    fill_project(project, builds)
    for build in builds:
        two_tone_art().save(build.art_path(tmp_path))
    return project, tmp_path
