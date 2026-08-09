"""Reusable per-character placement presets, without any Qt dependency.

A preset remembers how the user framed one character so that re-adding that same
character (in the same mode) restores the framing. The store reads the editor
state through `EditorState` on every call, see `state.py` for why.
"""

from __future__ import annotations

from ..models import Placement
from ..storage import load_presets, save_presets
from .build_choices import selected_build
from .state import EditorState


def preset_key(state: EditorState, member: Placement) -> str:
    """Identify the member's character across profile reloads, per mode.

    The identity falls back from the costume id (a skin frames differently from
    the default outfit) to the casefolded name.
    """
    build = selected_build(state, member)
    identity = build.costume_id if build and build.costume_id else member.name.casefold()
    return f"{state.project.mode}|{identity}"


class PresetStore:
    """The saved placement presets, keyed by `preset_key()`.

    The entry type stays `dict[str, float]` even though `flip` is a bool, because
    that is the type `storage.load_presets()`/`save_presets()` use.
    """

    def __init__(self, presets: dict[str, dict[str, float]]) -> None:
        self._presets = presets

    @classmethod
    def load(cls) -> PresetStore:
        return cls(load_presets())

    @property
    def entries(self) -> dict[str, dict[str, float]]:
        return self._presets

    def apply_to(self, state: EditorState, member: Placement) -> None:
        """Overwrite the member's framing with its stored preset, if there is one."""
        preset = self._presets.get(preset_key(state, member))
        if preset:
            member.offset_x = float(preset.get("offset_x", member.offset_x))
            member.offset_y = float(preset.get("offset_y", member.offset_y))
            member.zoom = float(preset.get("zoom", member.zoom))
            member.flip = bool(preset.get("flip", member.flip))

    def remember(self, state: EditorState, member: Placement) -> None:
        """Store the member's framing as the preset for its character and persist it."""
        if not member.name:
            return
        self._presets[preset_key(state, member)] = {
            "offset_x": member.offset_x,
            "offset_y": member.offset_y,
            "zoom": member.zoom,
            "flip": member.flip,
        }
        save_presets(self._presets)
