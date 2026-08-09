"""`RenderPipeline`, the throttled preview render loop.

Owns the throttle timer, the token that identifies the newest request and the
in-flight/stale flags, and turns a finished `RenderJob` into either a `QPixmap`
or an error message. It reads `project` and `art_root` off the `EditorState` on
every dispatch rather than capturing them, because the window replaces the
project wholesale.
"""

from __future__ import annotations

import copy

from PIL import Image
from PIL.ImageQt import ImageQt
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from PySide6.QtGui import QPixmap

from ..models import Project
from .render_job import RenderJob
from .state import EditorState

# Delay between a placement change and the preview render it triggers.
RENDER_THROTTLE_MS = 80


class RenderPipeline(QObject):
    """The preview's render loop: throttle, dispatch, and result routing."""

    rendered = Signal(QPixmap)
    failed = Signal(str)

    def __init__(self, state: EditorState, pool: QThreadPool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._pool = pool
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.dispatch)
        # Public, because the tests drive the loop through them directly.
        self.token = 0
        self.running = False
        self.stale = False
        self.closing = False

    def schedule(self) -> None:
        # A throttle, not a debounce: restarting the timer on every
        # mouse-move event would mean it never fires during a drag.
        if not self.closing and not self.timer.isActive():
            self.timer.start(RENDER_THROTTLE_MS)

    def dispatch(self) -> None:
        if self.closing:
            return
        self.token += 1
        if self.running:
            self.stale = True
            return
        project = self._state.project
        snapshot = Project(
            mode=project.mode,
            uid=project.uid,
            output_name=project.output_name,
            output_height=project.output_height,
            teams=copy.deepcopy(project.teams),
            active_team=project.active_team,
        )
        self.running = True
        job = RenderJob(self.token, snapshot, self._state.art_root)
        job.signals.finished.connect(self._on_job_finished)
        self._pool.start(job)

    def stop(self) -> None:
        """Wind the loop down for teardown.

        A job signalling the GUI thread over a queued connection can still be
        delivered after the pool has been drained; the flag stops such a late
        arrival from restarting the timer or re-dispatching onto that pool.
        """
        self.closing = True
        self.timer.stop()

    def _on_job_finished(self, token: int, image: Image.Image | None, error: Exception | None) -> None:
        self.running = False
        if token == self.token:
            if error is None:
                self.rendered.emit(QPixmap.fromImage(ImageQt(image)))
            else:
                self.failed.emit(str(error))
        if self.stale:
            self.stale = False
            self.dispatch()
