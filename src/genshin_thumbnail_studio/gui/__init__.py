"""The PySide6 desktop application."""

from __future__ import annotations

from .app import run
from .lineup import parse_lineup
from .main_window import RENDER_THROTTLE_MS, RESOLUTION_OPTIONS, MainWindow
from .preview import PreviewWidget
from .render_job import RenderJob, RenderJobSignals
from .team_slots import SLOT_MIME_TYPE, TeamSlotWidget

__all__ = [
    "RENDER_THROTTLE_MS",
    "RESOLUTION_OPTIONS",
    "SLOT_MIME_TYPE",
    "MainWindow",
    "PreviewWidget",
    "RenderJob",
    "RenderJobSignals",
    "TeamSlotWidget",
    "parse_lineup",
    "run",
]
