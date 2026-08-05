"""The bounded LRU caches render output is kept in, and their access helpers."""

from __future__ import annotations

import collections
import threading
from typing import TypeAlias, TypeVar

from PIL import Image

# Bounded LRU caches for render output that would otherwise be recomputed
# on every preview render regardless of what actually changed: one for
# fully-composited panel layers (make_panel()/placeholder_panel() output),
# one for decoded/resized weapon icons, one for decoded character art, and
# one for preview-sized working copies of that art. Cleared via
# clear_render_cache(), e.g. between tests that assert on cache hit/miss
# counts, and automatically at the end of every export_project() call (even
# if it raises) to release its larger export-scale entries.
#
# Cached panels are panel-sized (~0.6 MB each at preview scale, so the bound is
# ~19 MB) and are composited *into* the canvas rather than being the composite
# operand, so they must never be mutated once cached; canvas.alpha_composite()
# only reads them.
#
# The keys are heterogeneous tuples of primitives (paths, floats, ints, bools)
# assembled ad hoc by each cache's caller, so `tuple[object, ...]` is the
# honest type rather than a made-up, more specific structure.
CacheKey: TypeAlias = tuple[object, ...]

PANEL_CACHE_MAX = 32
panel_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

WEAPON_ICON_CACHE_MAX = 32
weapon_icon_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

ART_CACHE_MAX = 12
art_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

WORK_CACHE_MAX = 12
work_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

# The supersampled card mask and card-border overlay depend on the layout
# geometry alone (and, for the border, its colour), never on the placement, so
# after the first frame they are permanent hits even while a portrait is dragged.
MASK_CACHE_MAX = 16
mask_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

BORDER_CACHE_MAX = 16
border_cache: collections.OrderedDict[CacheKey, Image.Image] = collections.OrderedDict()

# A slot's C/R + weapon badge depends on the build and the card colour, never
# on the placement's position or zoom, so it survives a drag untouched. Each
# entry is the drawn tile plus the coverage mask that says which of its pixels
# the drawing actually touched (see badge_tile()).
BADGE_CACHE_MAX = 16
badge_cache: collections.OrderedDict[CacheKey, tuple[Image.Image, Image.Image]] = collections.OrderedDict()

# Previews render on a background thread while export_project() renders on
# the GUI thread, so all caches can be touched concurrently.
_cache_lock = threading.Lock()


def clear_render_cache() -> None:
    """Empty the panel, weapon-icon, character-art, working-copy, card-mask,
    card-border and badge caches."""
    with _cache_lock:
        panel_cache.clear()
        weapon_icon_cache.clear()
        art_cache.clear()
        work_cache.clear()
        mask_cache.clear()
        border_cache.clear()
        badge_cache.clear()


_CacheValue = TypeVar("_CacheValue")


def cache_get(cache: collections.OrderedDict[CacheKey, _CacheValue], key: CacheKey) -> _CacheValue | None:
    with _cache_lock:
        if key not in cache:
            return None
        cache.move_to_end(key)
        return cache[key]


def cache_put(
    cache: collections.OrderedDict[CacheKey, _CacheValue], key: CacheKey, value: _CacheValue, max_size: int
) -> None:
    with _cache_lock:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > max_size:
            cache.popitem(last=False)
