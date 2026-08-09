"""The placement math behind the drag, wheel, slider and reset interactions.

Qt-free: it reads the editor state through `EditorState` on every call, see
`state.py` for why.

`MAX_ZOOM` is the renderer's `MAX_PLACEMENT_ZOOM` rather than a copy of its
value: the renderer sizes its cached working copy of the source art for exactly
that ceiling, so a placement zoomed past it would be upsampled. The two must
therefore be the same number, which is what the renderer's own comment on that
constant records.
"""

from __future__ import annotations

from ..models import DEFAULT_ZOOM, Placement
from ..renderer import (
    MAX_PLACEMENT_ZOOM,
    STANDARD_ART_SIZE,
    art_pixel_size,
    max_offset,
    panel_target_size,
)
from .state import EditorState

MIN_ZOOM = 0.70
MAX_ZOOM = MAX_PLACEMENT_ZOOM


class PlacementController:
    def __init__(self, state: EditorState) -> None:
        self._state = state

    def offset_bounds(self, member: Placement) -> tuple[float, float]:
        """Reachable +/- offset per axis for the member's art and zoom."""
        state = self._state
        asset = state.assets.get(member.asset_key) if member.asset_key else None
        art_size = art_pixel_size(str(asset.art_path)) if asset else STANDARD_ART_SIZE
        return max_offset(art_size, state.project.mode == "abyss", member.zoom)

    def pan(self, member: Placement, dx: float, dy: float) -> None:
        """Pan the member by a drag delta given in canvas pixels."""
        # Offsets are fractions of the panel, and panels are pasted 1:1 onto the
        # canvas, so dividing by the panel size pans one canvas pixel per mouse
        # pixel on both axes.
        target_w, target_h = panel_target_size(self._state.project.mode == "abyss")
        max_x, max_y = self.offset_bounds(member)
        member.offset_x = min(max_x, max(-max_x, member.offset_x + dx / target_w))
        member.offset_y = min(max_y, max(-max_y, member.offset_y + dy / target_h))

    def zoom_by(self, member: Placement, delta: float) -> None:
        member.zoom = min(MAX_ZOOM, max(MIN_ZOOM, member.zoom + delta))

    def reset(self, member: Placement) -> None:
        defaults = Placement()
        member.offset_x = defaults.offset_x
        member.offset_y = defaults.offset_y
        member.zoom = DEFAULT_ZOOM[self._state.project.mode]
        member.flip = defaults.flip
