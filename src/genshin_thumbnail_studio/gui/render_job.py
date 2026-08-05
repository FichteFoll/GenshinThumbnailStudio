"""`RenderJob`, which renders a `Project` snapshot on a `QThreadPool` worker."""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QObject, QRunnable, Signal

from ..models import Asset, Project
from ..renderer import render_preview


class RenderJobSignals(QObject):
    finished = Signal(int, object, object)


class RenderJob(QRunnable):
    """Renders a `Project` snapshot on a worker thread via `QThreadPool`."""

    def __init__(self, token: int, project_snapshot: Project, assets_snapshot: dict[str, Asset]) -> None:
        super().__init__()
        self.token = token
        self._project_snapshot = project_snapshot
        self._assets_snapshot = assets_snapshot
        self.signals = RenderJobSignals()

    def run(self) -> None:  # type: ignore[no-untyped-def]
        try:
            image: Image.Image | None = render_preview(self._project_snapshot, self._assets_snapshot)
        except Exception as error:  # reported back to the GUI thread
            self.signals.finished.emit(self.token, None, error)
            return
        self.signals.finished.emit(self.token, image, None)
