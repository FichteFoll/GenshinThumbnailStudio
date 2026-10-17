"""The PySide6 desktop application."""

from __future__ import annotations

from .actions import ProjectActions
from .app import run
from .asset_loader import AssetJob, AssetJobSignals, AssetLoader
from .build_choices import BuildChoice, build_choices, selected_build
from .build_editor import ELEMENT_CHOICES, BuildEditorDialog, ask_custom_build
from .controls_panel import RESOLUTION_OPTIONS, ControlsPanel
from .dialogs import (
    ask_export_target,
    ask_lineup_text,
    confirm_cache_refresh,
    confirm_discard_changes,
    show_error,
)
from .editor_panel import EditorPanel
from .history import HISTORY_DEBOUNCE_MS, HISTORY_LIMIT, HistoryController, PlacementHistory
from .lineup import parse_lineup
from .logging_setup import configure_logging
from .main_window import MainWindow
from .placement import MAX_ZOOM, MIN_ZOOM, PlacementController
from .presets import PresetStore, preset_key
from .preview import PreviewWidget
from .profile_io import ProfileLoader
from .project_io import ProjectFiles
from .render_job import RenderJob, RenderJobSignals
from .render_pipeline import RENDER_THROTTLE_MS, RenderPipeline
from .state import EditorState
from .team_fields import TeamFieldsController
from .team_slots import SLOT_MIME_TYPE, TeamSlotWidget

__all__ = [
    "ELEMENT_CHOICES",
    "HISTORY_DEBOUNCE_MS",
    "HISTORY_LIMIT",
    "MAX_ZOOM",
    "MIN_ZOOM",
    "RENDER_THROTTLE_MS",
    "RESOLUTION_OPTIONS",
    "SLOT_MIME_TYPE",
    "AssetJob",
    "AssetJobSignals",
    "AssetLoader",
    "BuildChoice",
    "BuildEditorDialog",
    "ControlsPanel",
    "EditorPanel",
    "EditorState",
    "HistoryController",
    "MainWindow",
    "PlacementController",
    "PlacementHistory",
    "PresetStore",
    "PreviewWidget",
    "ProfileLoader",
    "ProjectActions",
    "ProjectFiles",
    "RenderJob",
    "RenderJobSignals",
    "RenderPipeline",
    "TeamFieldsController",
    "TeamSlotWidget",
    "ask_custom_build",
    "ask_export_target",
    "ask_lineup_text",
    "build_choices",
    "configure_logging",
    "confirm_cache_refresh",
    "confirm_discard_changes",
    "parse_lineup",
    "preset_key",
    "run",
    "selected_build",
    "show_error",
]
