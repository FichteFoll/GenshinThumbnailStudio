"""The PySide6 desktop application."""

from __future__ import annotations

from .app import run
from .lineup import parse_lineup
from .main_window import RENDER_THROTTLE_MS, RESOLUTION_OPTIONS, MainWindow
from .placement import MAX_ZOOM, MIN_ZOOM, PlacementController
from .presets import PresetStore, preset_key
from .preview import PreviewWidget
from .render_job import RenderJob, RenderJobSignals
from .state import EditorState
from .team_slots import SLOT_MIME_TYPE, TeamSlotWidget

__all__ = [
    "MAX_ZOOM",
    "MIN_ZOOM",
    "RENDER_THROTTLE_MS",
    "RESOLUTION_OPTIONS",
    "SLOT_MIME_TYPE",
    "EditorState",
    "MainWindow",
    "PlacementController",
    "PresetStore",
    "PreviewWidget",
    "RenderJob",
    "RenderJobSignals",
    "TeamSlotWidget",
    "parse_lineup",
    "preset_key",
    "run",
]
