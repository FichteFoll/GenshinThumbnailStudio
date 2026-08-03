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


def test_swap_slots_exchanges_placements(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()

    first = window.project.teams[0][0]
    second = window.project.teams[1][3]
    first.name = "Furina"
    first.fx = 0.42
    first.zoom = 1.20
    second.name = "Nahida"
    second.fx = 0.61
    second.zoom = 0.95

    window.swap_slots((0, 0), (1, 3))

    swapped_first = window.project.teams[0][0]
    swapped_second = window.project.teams[1][3]
    assert swapped_first.name == "Nahida"
    assert swapped_first.fx == 0.61
    assert swapped_first.zoom == 0.95
    assert swapped_second.name == "Furina"
    assert swapped_second.fx == 0.42
    assert swapped_second.zoom == 1.20

    window.close()
    app.processEvents()
