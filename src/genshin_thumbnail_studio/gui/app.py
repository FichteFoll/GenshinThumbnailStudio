"""The GUI entry point behind `pyproject.toml`'s `gui-scripts`."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def run() -> int:
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
