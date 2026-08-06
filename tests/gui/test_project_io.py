"""Tests for `MainWindow`'s profile loading and project save/open flows."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from genshin_thumbnail_studio.gui import MainWindow, asset_loader, dialogs, main_window
from genshin_thumbnail_studio.models import Asset, Build, Project
from genshin_thumbnail_studio.storage import load_profile_cache, save_profile_cache, save_project

from .helpers import (
    TEAM_NAMES,
    close_ignoring_unsaved_changes,
    create_test_assets,
    fill_window_teams,
    qapp,
    wait_for_render,
)


def make_build(name: str) -> Build:
    return Build(
        name=name,
        constellation=1,
        refinement=2,
        weapon_name="Splendor of Tranquil Waters",
        costume_id=None,
        build_id=f"{name}-build",
        build_md5="0123456789abcdef",
        last_build_update="2026-08-01T12:00:00+00:00",
        art_url=f"https://enka.network/ui/{name}.png",
        weapon_url="https://enka.network/ui/weapon.png",
        element="Hydro",
        rarity=5,
        weapon_rarity=5,
        raw={"name": name},
    )


def write_project(path: Path, uid: str) -> None:
    project = Project.blank("abyss", uid)
    for index, member in enumerate(member for team in project.teams for member in team):
        member.name = TEAM_NAMES[index]
    save_project(project, path)


class StubMessageBox:
    """Records dialogs instead of showing them; ``clickedButton`` always simulates Cancel."""

    ButtonRole = QMessageBox.ButtonRole
    StandardButton = QMessageBox.StandardButton
    instances: ClassVar[list["StubMessageBox"]] = []

    def __init__(self, parent: object = None) -> None:
        self.title = ""
        self.text = ""
        self.executed = False
        type(self).instances.append(self)

    def setWindowTitle(self, title: str) -> None:
        self.title = title

    def setText(self, text: str) -> None:
        self.text = text

    def addButton(self, *args: object) -> object:
        return object()

    def exec(self) -> None:
        self.executed = True

    def clickedButton(self) -> object | None:
        return None

    @staticmethod
    def critical(parent: object, title: str, text: str) -> None:
        raise AssertionError(f"unexpected error dialog: {title}: {text}")

    @staticmethod
    def information(parent: object, title: str, text: str) -> None:
        return None


class ForbiddenMessageBox(StubMessageBox):
    def __init__(self, parent: object = None) -> None:
        raise AssertionError("unexpected message box")

    @staticmethod
    def information(parent: object, title: str, text: str) -> None:
        raise AssertionError(f"unexpected info dialog: {title}: {text}")


def prepare_cached_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, last_update: datetime
) -> tuple[MainWindow, str]:
    uid = "700000042"
    builds = [make_build(name) for name in TEAM_NAMES]
    save_profile_cache(uid, builds, last_update)
    project_path = tmp_path / "project.json"
    write_project(project_path, uid)
    window = MainWindow()
    assets = create_test_assets(tmp_path / "assets", TEAM_NAMES)

    def fake_download_assets(*args: Any, **kwargs: Any) -> dict[str, Asset]:
        on_asset = kwargs.get("on_asset")
        if callable(on_asset):
            for key, asset in assets.items():
                on_asset(key, asset)
        return assets

    monkeypatch.setattr(asset_loader, "download_assets", fake_download_assets)
    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )
    return window, uid


def settle_downloads_and_render(window: MainWindow, app: QApplication) -> None:
    """Let the background art download land, then force the throttled render.

    Opening a project no longer downloads or renders synchronously: it starts
    the loader and schedules a render, so a test that wants the finished pixmap
    has to wait for both.
    """
    window._thread_pool.waitForDone(5000)
    app.processEvents()
    window._dispatch_render()
    wait_for_render(window, app)


def test_open_project_loads_cached_profile_and_previews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window, uid = prepare_cached_open(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(minutes=5))

    window.open_project()
    settle_downloads_and_render(window, app)

    assert window.project.uid == uid
    assert sorted(window.builds) == sorted(name.casefold() for name in TEAM_NAMES)
    assert window.preview._pixmap is not None

    window.close()
    app.processEvents()


def test_open_project_with_stale_cache_offers_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    StubMessageBox.instances = []
    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    window, _ = prepare_cached_open(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(hours=2))
    refreshed: list[bool] = []

    def fake_refresh_profile(*args: Any, **kwargs: Any) -> None:
        refreshed.append(True)

    def forbidden_load_profile(*args: Any, **kwargs: Any) -> None:
        pytest.fail("live profile load must not happen")

    monkeypatch.setattr(window.client, "refresh_profile", fake_refresh_profile)
    monkeypatch.setattr(window.client, "load_profile", forbidden_load_profile)

    window.open_project()
    settle_downloads_and_render(window, app)

    assert len(StubMessageBox.instances) == 1
    assert "2.0 hours" in StubMessageBox.instances[0].text
    assert not refreshed
    assert sorted(window.builds) == sorted(name.casefold() for name in TEAM_NAMES)
    assert window.preview._pixmap is not None

    window.close()
    app.processEvents()


def test_open_project_without_cache_shows_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    project_path = tmp_path / "project.json"
    write_project(project_path, "900000099")
    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )
    window = MainWindow()

    window.open_project()

    assert not window.builds
    assert "no cached profile" in window.statusBar().currentMessage()

    window.close()
    app.processEvents()


def test_load_profile_persists_profile_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    uid = "700000042"
    builds = [make_build("Furina"), make_build("Nahida")]
    last_update = datetime(2026, 8, 3, 10, 30, 15, tzinfo=timezone.utc)

    def fake_load_profile(*args: Any, **kwargs: Any) -> tuple[list[Build], float, datetime]:
        return builds, 5.0, last_update

    monkeypatch.setattr(window.client, "load_profile", fake_load_profile)
    window.uid_edit.setText(uid)

    window.load_profile()

    cached = load_profile_cache(uid)
    assert cached is not None
    cached_builds, cached_last_update = cached
    assert cached_builds == builds
    assert cached_last_update == last_update

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def _prepare_export_window(window: MainWindow, tmp_path: Path, names: list[str]) -> None:
    assets = create_test_assets(tmp_path / "assets", names)
    window.builds = {key: asset.build for key, asset in assets.items()}
    fill_window_teams(window, names)
    window._rebuild_team_fields()
    window.assets = assets


def test_export_abyss_writes_the_file_chosen_in_the_save_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.output_name.setText("prefilled")

    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: pytest.fail("abyss export must not ask for a folder")),
    )
    chosen = tmp_path / "out" / "chosen.png"
    default_names: list[str] = []

    def fake_save_dialog(parent: object, title: str, default_name: str, name_filter: str) -> tuple[str, str]:
        default_names.append(default_name)
        return str(chosen), "PNG (*.png)"

    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.export()

    assert [Path(name).name for name in default_names] == ["prefilled.png"]
    assert chosen.exists()
    assert list(chosen.parent.glob("*.png")) == [chosen]
    assert window.output_name.text() == "chosen"
    assert window.project.output_name == "chosen"

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_export_stygian_still_asks_for_a_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    # Switching the mode replaces window.project, so fill the teams afterwards.
    window.stygian_radio.setChecked(True)
    names = [*TEAM_NAMES, "Xingqiu", "Ganyu", "Raiden Shogun", "Yelan"]
    _prepare_export_window(window, tmp_path, names)
    window.output_name.setText("bosses")

    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        main_window.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: pytest.fail("stygian export must not ask for a file name")),
    )
    directory = tmp_path / "out"
    monkeypatch.setattr(
        main_window.QFileDialog, "getExistingDirectory", staticmethod(lambda *args, **kwargs: str(directory))
    )

    window.export()

    for index in (1, 2, 3):
        assert (directory / f"bosses_boss{index}.png").exists()

    window.close()
    app.processEvents()


def test_export_defaults_to_the_opened_project_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    project_dir = tmp_path / "projects"
    project_dir.mkdir()
    project_file = project_dir / "thumbnail-project.json"
    write_project(project_file, "700000042")

    window = MainWindow()
    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        main_window.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(project_file), ""))
    )
    window.open_project()

    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.output_name.setText("prefilled")
    default_paths: list[str] = []

    def fake_save_dialog(parent: object, title: str, default_path: str, name_filter: str) -> tuple[str, str]:
        default_paths.append(default_path)
        return str(tmp_path / "out" / "chosen.png"), "PNG (*.png)"

    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.export()

    assert default_paths == [str(project_dir / "prefilled.png")]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_saving_project_clears_the_dirty_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    window.project.teams[0][0].offset_x = 0.3
    assert window.is_dirty()

    monkeypatch.setattr(
        main_window.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(tmp_path / "thumbnail-project.json"), "")),
    )
    window.save_project()

    assert not window.is_dirty()

    window.close()
    app.processEvents()


def test_opening_a_project_takes_its_dirty_baseline_before_the_art_arrives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opening leaves the project as it was read; the presets reframe it later.

    The download no longer runs inside `open_project()`, so the preset that each
    arriving asset applies is an edit made after the baseline, exactly like one
    the user would make by hand.
    """
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window, _ = prepare_cached_open(tmp_path, monkeypatch, datetime.now(timezone.utc) - timedelta(minutes=5))

    def fake_apply_to(editor: MainWindow, member: Any) -> None:
        member.offset_x = 0.42

    monkeypatch.setattr(window._presets, "apply_to", fake_apply_to)

    window.open_project()

    assert window.project.teams[0][0].offset_x != 0.42
    assert not window.is_dirty()

    settle_downloads_and_render(window, app)

    assert window.project.teams[0][0].offset_x == 0.42

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_export_defaults_to_the_saved_project_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    project_dir = tmp_path / "saved"
    project_dir.mkdir()
    project_file = project_dir / "thumbnail-project.json"

    window = MainWindow()
    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.output_name.setText("prefilled")

    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        main_window.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(project_file), ""))
    )
    window.save_project()

    default_paths: list[str] = []

    def fake_save_dialog(parent: object, title: str, default_path: str, name_filter: str) -> tuple[str, str]:
        default_paths.append(default_path)
        return str(tmp_path / "out" / "chosen.png"), "PNG (*.png)"

    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.export()

    assert default_paths == [str(project_dir / "prefilled.png")]

    close_ignoring_unsaved_changes(window, app, monkeypatch)
