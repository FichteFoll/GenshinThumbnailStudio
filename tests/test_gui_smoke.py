import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox")

from PySide6.QtWidgets import QApplication

from genshin_thumbnail_studio.gui import MainWindow


def test_main_window_starts(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.windowTitle() == "Genshin Thumbnail Studio"
    assert len(window.team_combos) == 2
    window.close()
    app.processEvents()
