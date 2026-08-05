"""Decoding, resizing and cropping the source character art."""

from __future__ import annotations

import functools

from PIL import Image

from ..models import Asset, Placement
from .cache import (
    ART_CACHE_MAX,
    WORK_CACHE_MAX,
    art_cache,
    cache_get,
    cache_put,
    work_cache,
)
from .geometry import cover_scale, offset_limits, scaled_size

# The GUI clamps a placement's zoom to 0.70..1.80, so a preview working copy
# scaled for 1.80 is never upsampled by an edit made through the GUI.
MAX_PLACEMENT_ZOOM = 1.80

# How much wider than the character crop the blurred glow layer is framed.
GLOW_ZOOM_FACTOR = 0.78


def glow_zoom(zoom: float) -> float:
    """The zoom the panel glow is cover-fit at, for a placement zoom.

    The glow is deliberately framed wider than the crop, so the wash around the
    portrait shows a different part of the art, but it must still cover the
    whole panel. Since both art axes scale by the same factor, zoom 1.0 is the
    smallest factor that still covers the panel, so the floor wins for every
    placement zoom up to `1 / GLOW_ZOOM_FACTOR` and the factor itself only
    applies above that. Below a placement zoom of 1.0 the floor even leaves the
    glow more zoomed in than the crop, which is what keeps the panel covered
    while the portrait shrinks inside it.
    """
    return max(1.0, zoom * GLOW_ZOOM_FACTOR)


def cover_resize_offset(
    image: Image.Image,
    size: tuple[int, int],
    offset_x: float,
    offset_y: float,
    zoom: float,
    resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> Image.Image:
    """Cover-fit `image` into `size`, panned by signed offsets.

    The offsets are fractions of the target size, positive meaning the visible
    content moves right/down. They are clamped to the reachable range first,
    which includes `PAN_OVERSCAN`, so the crop window may extend past the
    resized art by that margin. That overscanned strip is left transparent,
    letting the panel background and glow show through without any extra
    compositing.
    """
    source_w, source_h = image.size
    target_w, target_h = size
    image_scale = cover_scale(image.size, size, zoom)
    resized_w, resized_h = scaled_size(image.size, image_scale)
    limit_x, limit_y = offset_limits((resized_w, resized_h), size)
    offset_x = min(limit_x, max(-limit_x, offset_x))
    offset_y = min(limit_y, max(-limit_y, offset_y))
    left = round((resized_w - target_w) / 2 - offset_x * target_w)
    top = round((resized_h - target_h) / 2 - offset_y * target_h)

    # Resampling only the crop window's source region is far cheaper than
    # scaling the whole image and throwing most of it away. The window is
    # mapped back with source_w / resized_w rather than 1 / image_scale
    # because resized_w/resized_h are rounded integers, and dividing by them
    # keeps the mapping exact at the right and bottom edges.
    # It is clipped to the art first, since Image.resize() rejects a box that
    # leaves the source, which the overscan margin makes possible.
    visible_left = max(0, left)
    visible_top = max(0, top)
    visible_right = min(resized_w, left + target_w)
    visible_bottom = min(resized_h, top + target_h)
    if visible_right <= visible_left or visible_bottom <= visible_top:
        return Image.new("RGBA", size, (0, 0, 0, 0))
    box = (
        visible_left * source_w / resized_w,
        visible_top * source_h / resized_h,
        visible_right * source_w / resized_w,
        visible_bottom * source_h / resized_h,
    )
    visible_size = (visible_right - visible_left, visible_bottom - visible_top)
    # Pillow's Image.resize() stub leaves its overload partially unknown.
    visible = image.resize(visible_size, resample, box=box)  # pyright: ignore[reportUnknownMemberType]
    if visible_size == size:
        return visible

    panned = Image.new("RGBA", size, (0, 0, 0, 0))
    panned.paste(visible, (visible_left - left, visible_top - top))
    return panned


def panel_art(
    art: Image.Image,
    target: tuple[int, int],
    member: Placement,
    zoom: float,
    resample: Image.Resampling = Image.Resampling.LANCZOS,
) -> Image.Image:
    """One panel's crop of the character art, mirrored when the placement is
    flipped.

    Flipping is defined as mirroring the source artwork, which would leave the
    framing untouched. Mirroring the panel-sized crop and negating the
    horizontal offset is the same image for a fraction of the cost, because
    negating a panel-relative offset mirrors the crop window about the panel
    center:
    ``mirror(crop(art, -offset_x)) == crop(mirror(art), offset_x)``.
    Mirroring the crop also keeps the shared, read-only art cache untouched.
    """
    offset_x = -member.offset_x if member.flip else member.offset_x
    crop = cover_resize_offset(art, target, offset_x, member.offset_y, zoom, resample)
    if member.flip:
        crop = crop.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    return crop


@functools.lru_cache(maxsize=64)
def art_pixel_size(path: str) -> tuple[int, int]:
    """The art file's dimensions, read from its header without decoding it.

    Kept out of the render caches on purpose: those hold images and are emptied
    by `clear_render_cache()`, while a given file's dimensions never change.
    """
    with Image.open(path) as image:
        return image.size


def source_art(asset: Asset, target: tuple[int, int], zoom: float, scale: int) -> Image.Image:
    """The image make_panel() should resample its panel art from.

    For a preview render this is a working copy pre-downscaled to what the
    largest GUI-reachable zoom needs, so a drag resamples a few megapixels
    less per frame. Exports (and zooms beyond the GUI's clamp, which can only
    come from a hand-edited project file) resample the full-resolution source
    so they never lose detail.

    The cached images are shared between the preview render thread and the
    GUI thread, so they must be treated as read-only. Every consumer produces
    a new image via resize()/crop(), so no copy is made here.
    """
    art_key = (str(asset.art_path),)
    art = cache_get(art_cache, art_key)
    if art is None:
        art = Image.open(asset.art_path).convert("RGBA")
        cache_put(art_cache, art_key, art, ART_CACHE_MAX)
    if scale != 1 or zoom > MAX_PLACEMENT_ZOOM:
        return art

    source_w, source_h = art.size
    # Same cover scale cover_resize_offset() computes, but at the maximum zoom
    # rather than this placement's, so one working copy serves every zoom.
    work_scale = cover_scale(art.size, target, MAX_PLACEMENT_ZOOM)
    work = (round(source_w * work_scale), round(source_h * work_scale))
    if work[0] >= source_w or work[1] >= source_h:
        return art

    work_key = (str(asset.art_path), *work)
    working = cache_get(work_cache, work_key)
    if working is None:
        # Pillow's Image.resize() stub leaves its overload partially unknown.
        working = art.resize(work, Image.Resampling.LANCZOS)  # pyright: ignore[reportUnknownMemberType]
        cache_put(work_cache, work_key, working, WORK_CACHE_MAX)
    return working
