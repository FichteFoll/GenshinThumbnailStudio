from __future__ import annotations

from collections.abc import Callable

from PIL import Image, ImageChops, ImageDraw

# Pillow's ImageDraw has no antialiasing, so the near-vertical slanted card
# edges come out stair-stepped. Drawing that geometry at 4x into a
# single-channel coverage image and box-downsampling it yields proper edge
# coverage; "L" rather than "RGBA" makes it ~6x cheaper for the same result,
# and the outcome is cached anyway because it only depends on the layout.
GEOMETRY_SUPERSAMPLE = 4


def supersampled_coverage_for(
    size: tuple[int, int], draw_shape: Callable[[ImageDraw.ImageDraw, int], None]
) -> Image.Image:
    """An antialiased "L" coverage map of `size`, drawn by `draw_shape(draw, factor)`
    in coordinates multiplied by `factor`.

    Drawing outside the map is clipped by ImageDraw, which is what lets the
    slanted card outlines overhang their own layer.
    """
    big_size = (size[0] * GEOMETRY_SUPERSAMPLE, size[1] * GEOMETRY_SUPERSAMPLE)
    big = Image.new("L", big_size, 0)
    draw_shape(ImageDraw.Draw(big), GEOMETRY_SUPERSAMPLE)
    # Pillow's Image.resize() stub leaves its overload partially unknown.
    return big.resize(size, Image.Resampling.BOX)  # pyright: ignore[reportUnknownMemberType]


def supersampled_coverage(
    size: tuple[int, int], points: list[tuple[int, int]], width: int | None = None
) -> Image.Image:
    """An antialiased "L" coverage map of `size` for the polygon `points`:
    filled when `width` is None, otherwise a `width`-pixel outline stroke.
    """

    def draw_shape(draw: ImageDraw.ImageDraw, factor: int) -> None:
        big_points = [(x * factor, y * factor) for x, y in points]
        if width is None:
            draw.polygon(big_points, fill=255)
        else:
            draw.polygon(big_points, outline=255, width=width * factor)

    return supersampled_coverage_for(size, draw_shape)


def supersampled_box(box: tuple[int, int, int, int], factor: int) -> tuple[int, int, int, int]:
    """`box` blown up by `factor` for a supersampled draw. Pillow's shape
    coordinates are inclusive, so scaling the raw values would leave the far
    edges one supersampled pixel short and shrink the shape by a whole
    downsampled pixel."""
    x0, y0, x1, y1 = box
    return (x0 * factor, y0 * factor, (x1 + 1) * factor - 1, (y1 + 1) * factor - 1)


def _hard_mask(mask: Image.Image) -> Image.Image:
    """`mask` with every partially covered pixel promoted to full coverage."""

    def lut(value: int) -> int:
        return 255 if value else 0

    # Pillow's Image.point() stub leaves its overload partially unknown.
    return mask.point(lut)  # pyright: ignore[reportUnknownMemberType]


def _fully_covered(mask: Image.Image) -> Image.Image:
    """The part of `mask` that is covered completely rather than partially."""

    def lut(value: int) -> int:
        return 255 if value == 255 else 0

    # Pillow's Image.point() stub leaves its overload partially unknown.
    return mask.point(lut)  # pyright: ignore[reportUnknownMemberType]


def paint_through_coverage(
    tile: Image.Image, color: tuple[int, int, int, int], mask: Image.Image, painted: Image.Image
) -> Image.Image:
    """Paint `color` into `tile` through the antialiased `mask` and return the
    grown `painted` coverage.

    `Image.paste()` blends toward what the tile already holds, so on a shape's
    outer silhouette, where that is still transparent black, a half-covered
    pixel would end up at half the colour. The caller then pastes the tile onto
    the card through the very same coverage, which would multiply by that half
    a second time and fade every antialiased edge toward black. Seeding the
    footprint with the flat colour first keeps those pixels at the colour
    itself and leaves the softness to the coverage mask alone.

    The seed is skipped where an earlier shape already covers the pixel
    completely: there the tile holds real content the new shape should blend
    into, which is what antialiases the shapes against each other. A pixel an
    earlier shape only covers partially is part of the badge's silhouette and
    gets seeded, so the outermost shape's colour survives the coverage paste.
    """
    seed = ImageChops.subtract(_hard_mask(mask), _fully_covered(painted))
    tile.paste(color, mask=seed)
    tile.paste(color, mask=mask)
    return ImageChops.lighter(painted, mask)
