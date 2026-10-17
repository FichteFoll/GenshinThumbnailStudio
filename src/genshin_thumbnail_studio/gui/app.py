"""The GUI entry point behind `pyproject.toml`'s `gui-scripts`."""

from __future__ import annotations

import logging
import sys
from types import TracebackType

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .logging_setup import configure_logging
from .main_window import MainWindow

logger = logging.getLogger(__name__)

SMOKE_TEST_FLAG = "--smoke-test"
SMOKE_TEST_TIMEOUT_MS = 30_000


def run() -> int:
    configure_logging()
    _install_excepthook()
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        # QApplication.instance() is typed as QCoreApplication | None, which
        # lacks setStyle; a fresh QApplication is always the concrete subtype.
        app = QApplication([])
    app.setStyle("Fusion")
    app.setApplicationName("Genshin Thumbnail Studio")
    app.setOrganizationName("GenshinThumbnailStudio")
    window = MainWindow()
    if SMOKE_TEST_FLAG in sys.argv[1:]:
        _exit_after_first_render(app, window)
    window.show()
    return app.exec()


def _exit_after_first_render(app: QApplication, window: MainWindow) -> None:
    """End the event loop with 0 once the first preview arrives, or 1 when it
    fails or does not arrive in time, instead of waiting for the user."""
    timeout = QTimer(window)
    timeout.setSingleShot(True)
    finished = False

    def finish(code: int) -> None:
        # A late render can still arrive over its queued connection after the
        # first outcome; it must not end some later event loop.
        nonlocal finished
        if finished:
            return
        finished = True
        timeout.stop()
        window.close()
        # Not `quit()`: Qt 6's `quit()` first tries to close every window.
        app.exit(code)

    def fail(message: str) -> None:
        logger.error("Smoke test failed: %s", message)
        finish(1)

    window.preview_rendered.connect(lambda: finish(0))
    window.preview_failed.connect(fail)
    timeout.timeout.connect(lambda: fail(f"no preview within {SMOKE_TEST_TIMEOUT_MS} ms"))
    timeout.start(SMOKE_TEST_TIMEOUT_MS)


def _install_excepthook() -> None:
    """Record an exception that reaches no popup, then let the previous hook run."""
    previous = sys.excepthook

    def hook(
        exc_type: type[BaseException], value: BaseException, traceback: TracebackType | None
    ) -> None:
        logger.error("Unhandled exception", exc_info=(exc_type, value, traceback))
        previous(exc_type, value, traceback)

    sys.excepthook = hook
