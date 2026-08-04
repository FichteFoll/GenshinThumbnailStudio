from PIL import Image, ImageChops, ImageDraw

from genshin_thumbnail_studio.models import Placement
from genshin_thumbnail_studio.renderer.art import cover_resize_offset, glow_zoom, panel_art
from genshin_thumbnail_studio.renderer.geometry import (
    PAN_OVERSCAN,
    STANDARD_ART_SIZE,
    max_offset,
    panel_target_size,
    resized_art_size,
)

from .helpers import marked_source, rgba, two_tone_art


def _marker_center_x(image: Image.Image) -> float:
    """Horizontal center of the red marker stripe in a crop's middle row."""
    row = image.height // 2
    columns = [x for x in range(image.width) if rgba(image, (x, row))[0] > 200]
    assert columns, "marker stripe not visible in the crop"
    return (columns[0] + columns[-1]) / 2


def test_cover_resize_offset_centers_and_pans() -> None:
    source = marked_source()
    target = panel_target_size(compact=True)

    centered = cover_resize_offset(source, target, 0.0, 0.0, 1.0)
    assert abs(_marker_center_x(centered) - target[0] / 2) <= 1

    # A positive offset moves the visible content right by offset * panel width.
    shifted = cover_resize_offset(source, target, 0.1, 0.0, 1.0)
    assert abs(_marker_center_x(shifted) - _marker_center_x(centered) - 0.1 * target[0]) <= 1

    mirrored = cover_resize_offset(source, target, -0.1, 0.0, 1.0)
    assert abs(_marker_center_x(mirrored) - _marker_center_x(centered) + 0.1 * target[0]) <= 1


def _marker_center_y(image: Image.Image) -> float:
    """Vertical center of the red marker stripe in a crop's middle column."""
    column = image.width // 2
    rows = [y for y in range(image.height) if rgba(image, (column, y))[0] > 200]
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
    return {rgba(image, (x, y))[3] for x in range(image.width)}


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
    source = marked_source()
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
    limit_x = abs(resized_w - target_w) / (2 * target_w) + PAN_OVERSCAN
    limit_y = abs(resized_h - target_h) / (2 * target_h) + PAN_OVERSCAN
    offset_x = min(limit_x, max(-limit_x, offset_x))
    offset_y = min(limit_y, max(-limit_y, offset_y))
    # Pillow's `resize` stub loses precision on its `resample` overload here.
    resized = image.resize((resized_w, resized_h), Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
    left = round((resized_w - target_w) / 2 - offset_x * target_w)
    top = round((resized_h - target_h) / 2 - offset_y * target_h)
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
                    # Pillow's `getextrema` stub returns a per-band-tuple union
                    # for multi-band images, which it cannot rule out here even
                    # though `.split()` always yields single-band images.
                    assert (
                        max(band.getextrema()[1] for band in difference.split())  # pyright: ignore[reportOperatorIssue]
                        <= 4
                    ), case


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


def test_a_zoom_below_the_cover_fit_can_be_panned_to_the_panel_edges() -> None:
    """Art that no longer covers the panel must still be movable across it, all
    the way to either edge, instead of being stuck in the middle."""
    zoom = 0.70
    source = Image.new("RGBA", STANDARD_ART_SIZE, (0, 0, 40, 255))
    for compact in (True, False):
        target = panel_target_size(compact)
        resized = resized_art_size(STANDARD_ART_SIZE, compact, zoom)
        assert resized[1] < target[1], (compact, resized, target)
        # The offset that moves the shrunken art's edge onto the panel's edge.
        margin = (target[1] - resized[1]) / (2 * target[1])
        assert max_offset(STANDARD_ART_SIZE, compact=compact, zoom=zoom)[1] >= margin

        flush_bottom = cover_resize_offset(source, target, 0.0, margin, zoom)
        assert _row_alpha(flush_bottom, target[1] - 1) == {255}, compact
        assert _row_alpha(flush_bottom, 0) == {0}, compact

        flush_top = cover_resize_offset(source, target, 0.0, -margin, zoom)
        assert _row_alpha(flush_top, 0) == {255}, compact
        assert _row_alpha(flush_top, target[1] - 1) == {0}, compact


def test_glow_never_leaves_the_panel_uncovered() -> None:
    for zoom in (0.70, 1.00, 1.28, 1.80):
        assert glow_zoom(zoom) >= 1.0
        for compact in (True, False):
            target = panel_target_size(compact)
            resized = resized_art_size(STANDARD_ART_SIZE, compact, glow_zoom(zoom))
            assert resized[0] >= target[0], (zoom, compact, resized, target)
            assert resized[1] >= target[1], (zoom, compact, resized, target)


def _tone_boundary_x(crop: Image.Image) -> float:
    """The x of the single red/blue transition in the crop's middle row.

    A rigid feature of the two-tone art, unlike a per-colour pixel count, which
    also changes as a region is clipped at a panel edge.
    """
    row = crop.height // 2
    pixels = [rgba(crop, (x, row)) for x in range(crop.width)]
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

    # The drag has to stay inside the reachable offset range, or the renderer
    # clamps it and the shift no longer matches the requested offset.
    drag = 0.1
    shifts: dict[bool, float] = {}
    for flip in (False, True):
        member = Placement(offset_y=0.0, flip=flip)
        assert drag < max_offset(art.size, compact=True, zoom=member.zoom)[0]
        centered = panel_art(art, target, member, member.zoom)
        member.offset_x = drag
        shifted = panel_art(art, target, member, member.zoom)
        shifts[flip] = _tone_boundary_x(shifted) - _tone_boundary_x(centered)
        assert shifts[flip] > 0, flip
        assert abs(shifts[flip] - drag * target[0]) <= 2, flip

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
