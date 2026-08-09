"""`RenderJob`, which renders a `Project` snapshot on a `QThreadPool` worker."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Signal

from ..models import Project
from ..renderer import render_preview


class RenderJobSignals(QObject):
    finished = Signal(int, object, object)


class RenderJob(QRunnable):
    """Renders a `Project` snapshot on a worker thread via `QThreadPool`."""

    def __init__(self, token: int, project_snapshot: Project, art_root: Path) -> None:
        super().__init__()
        self.token = token
        self._project_snapshot = project_snapshot
        self._art_root = art_root
        self.signals = RenderJobSignals()

    def run(self) -> None:  # type: ignore[no-untyped-def]
        try:
            image: Image.Image | None = render_preview(self._project_snapshot, self._art_root)
        except Exception as error:  # reported back to the GUI thread
            self.signals.finished.emit(self.token, None, error)
            return
        self.signals.finished.emit(self.token, image, None)
