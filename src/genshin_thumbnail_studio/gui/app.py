"""The GUI entry point behind `pyproject.toml`'s `gui-scripts`."""

from __future__ import annotations

import logging
import sys
from types import TracebackType

from PySide6.QtWidgets import QApplication

from .logging_setup import configure_logging
from .main_window import MainWindow

logger = logging.getLogger(__name__)


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
    window.show()
    return app.exec()


def _install_excepthook() -> None:
    """Record an exception that reaches no popup, then let the previous hook run."""
    previous = sys.excepthook

    def hook(
        exc_type: type[BaseException], value: BaseException, traceback: TracebackType | None
    ) -> None:
        logger.error("Unhandled exception", exc_info=(exc_type, value, traceback))
        previous(exc_type, value, traceback)

    sys.excepthook = hook
