"""Tests for `MainWindow`'s profile loading and project save/open flows."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from genshin_thumbnail_studio.enka import EnkaClient
from genshin_thumbnail_studio.gui import MainWindow, asset_loader, dialogs, project_io
from genshin_thumbnail_studio.models import LIVE_BUILD_NAME, Asset, Build, Profile, Project
from genshin_thumbnail_studio.storage import (
    load_last_profile,
    load_profile_cache,
    load_project,
    save_last_profile,
    save_profile_cache,
    save_project,
)

from .helpers import (
    TEAM_NAMES,
    close_ignoring_unsaved_changes,
    create_test_assets,
    fill_window_teams,
    qapp,
    wait_for_render,
)


def make_build(name: str, build_name: str = LIVE_BUILD_NAME) -> Build:
    return Build(
        name=name,
        constellation=1,
        refinement=2,
        weapon_name="Splendor of Tranquil Waters",
        costume_id=None,
        build_name=build_name,
        build_id=f"{name}-{build_name}",
        art_url=f"https://enka.network/ui/{name}.png",
        weapon_url="https://enka.network/ui/weapon.png",
        element="Hydro",
        rarity=5,
        weapon_rarity=5,
    )


def make_profile(
    identifier: str, names: list[str], username: str = "", fetched_at: datetime | None = None
) -> Profile:
    return Profile(
        identifier=identifier,
        uid="" if username else identifier,
        username=username,
        builds={name.casefold(): [make_build(name)] for name in names},
        fetched_at=fetched_at or datetime.now(),
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fetched_at: datetime
) -> tuple[MainWindow, str]:
    uid = "700000042"
    save_profile_cache(make_profile(uid, TEAM_NAMES, fetched_at=fetched_at))
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
        project_io.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
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
    window._render.dispatch()
    wait_for_render(window, app)


def test_open_project_loads_cached_profile_and_previews(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window, uid = prepare_cached_open(tmp_path, monkeypatch, datetime.now() - timedelta(minutes=5))

    window.open_project()
    settle_downloads_and_render(window, app)

    assert window.project.uid == uid
    assert sorted(window.builds) == sorted(name.casefold() for name in TEAM_NAMES)
    assert window.editor_panel.preview._pixmap is not None

    window.close()
    app.processEvents()


def test_open_project_with_stale_cache_offers_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    StubMessageBox.instances = []
    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    window, _ = prepare_cached_open(tmp_path, monkeypatch, datetime.now() - timedelta(hours=2))

    def forbidden_load_profile(*args: Any, **kwargs: Any) -> None:
        pytest.fail("live profile load must not happen")

    monkeypatch.setattr(window.client, "load_profile", forbidden_load_profile)

    window.open_project()
    settle_downloads_and_render(window, app)

    assert len(StubMessageBox.instances) == 1
    assert "2.0 hours" in StubMessageBox.instances[0].text
    assert sorted(window.builds) == sorted(name.casefold() for name in TEAM_NAMES)
    assert window.editor_panel.preview._pixmap is not None

    window.close()
    app.processEvents()


def test_open_project_without_cache_shows_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    project_path = tmp_path / "project.json"
    write_project(project_path, "900000099")
    monkeypatch.setattr(
        project_io.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )
    window = MainWindow()

    window.open_project()

    assert not window.builds
    assert "no cached profile" in window.statusBar().currentMessage()

    window.close()
    app.processEvents()


def test_load_profile_fills_the_builds_and_downloads_under_build_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1: the profile comes from Enka, and its art is fetched per character *and* build."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    live = make_build("Furina")
    saved = make_build("Furina", "Bow DPS")
    profile = Profile(
        identifier="700000042",
        uid="700000042",
        username="",
        builds={"furina": [live, saved]},
        fetched_at=datetime(2026, 8, 3, 10, 30, 15),
    )
    def fake_load_profile(identifier: str) -> Profile:
        return profile

    # `ProfileLoader.load()` funnels every exception into a real modal dialog,
    # which would hang the headless run instead of failing it.
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    monkeypatch.setattr(window.client, "load_profile", fake_load_profile)
    requested: list[list[str]] = []

    def fake_download_assets(
        builds: list[Build], root: Path, progress: object = None, on_asset: object = None
    ) -> dict[str, Asset]:
        requested.append([build.key for build in builds])
        return {}

    monkeypatch.setattr(asset_loader, "download_assets", fake_download_assets)
    window.project.teams[0][0].name = "Furina"
    window.controls_panel.profile_edit.setText("700000042")

    window.load_profile()
    window._thread_pool.waitForDone(5000)
    app.processEvents()

    assert window.builds == {"furina": [live, saved]}
    # The live build is the default, and its art is keyed by character and build.
    assert window.project.teams[0][0].build == live
    assert requested == [["furina|live"]]

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_open_project_resolves_the_cached_profile_by_name_not_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4: a project's profile name takes priority over its UID."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    def no_downloads(*args: object, **kwargs: object) -> dict[str, Asset]:
        return {}

    monkeypatch.setattr(asset_loader, "download_assets", no_downloads)
    save_profile_cache(make_profile("Algoinde", TEAM_NAMES, username="Algoinde"))
    save_profile_cache(make_profile("900000099", ["Nobody"]))

    project = Project.blank("abyss", "900000099")
    project.profile_name = "Algoinde"
    for index, member in enumerate(member for team in project.teams for member in team):
        member.name = TEAM_NAMES[index]
    project_path = tmp_path / "named-project.json"
    save_project(project, project_path)
    monkeypatch.setattr(
        project_io.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )
    window = MainWindow()

    window.open_project()

    assert sorted(window.builds) == sorted(name.casefold() for name in TEAM_NAMES)
    assert window.controls_panel.profile_edit.text() == "Algoinde"

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_load_profile_persists_profile_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()

    uid = "700000042"
    profile = make_profile(uid, ["Furina", "Nahida"], fetched_at=datetime(2026, 8, 3, 10, 30, 15))

    def fake_load_profile(identifier: str) -> Profile:
        return profile

    monkeypatch.setattr(window.client, "load_profile", fake_load_profile)
    window.controls_panel.profile_edit.setText(uid)

    window.load_profile()

    cached = load_profile_cache(uid)
    assert cached is not None
    assert cached.builds == profile.builds
    assert cached.fetched_at == profile.fetched_at
    assert cached.identifier == uid

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_load_profile_remembers_the_typed_identifier_not_the_resolved_uid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R13: the field comes back holding what the user typed, a username included."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window = MainWindow()

    username = "Algoinde"
    profile = make_profile("700000042", ["Furina"], username=username)

    def fake_load_profile(identifier: str) -> Profile:
        return profile

    monkeypatch.setattr(window.client, "load_profile", fake_load_profile)
    window.controls_panel.profile_edit.setText(username)

    window.load_profile()

    assert load_last_profile() == username

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_a_fresh_window_shows_the_last_remembered_profile_without_loading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R13: the field is ready to use on startup, but nothing is fetched for it."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)

    def forbidden_load_profile(*args: Any, **kwargs: Any) -> None:
        pytest.fail("a remembered profile must not be fetched on startup")

    save_last_profile("700000042")
    # On the class, so the guard covers the construction itself; patching the
    # instance afterwards would let a fetch from `__init__` through unseen.
    monkeypatch.setattr(EnkaClient, "load_profile", forbidden_load_profile)

    window = MainWindow()
    app.processEvents()

    assert window.controls_panel.profile_edit.text() == "700000042"

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_choosing_a_build_snapshots_it_into_the_saved_and_reopened_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R7/R9/R10: the chosen build frames the slot, is saved, and survives reopening."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)

    def no_downloads(*args: object, **kwargs: object) -> dict[str, Asset]:
        return {}

    monkeypatch.setattr(asset_loader, "download_assets", no_downloads)
    uid = "700000042"
    live = make_build("Furina")
    saved_build = make_build("Furina", "Bow DPS")
    saved_build.costume_id = "203201"
    saved_build.weapon_name = "Aqua Simulacra"
    saved_build.constellation = 6
    saved_build.refinement = 5
    save_profile_cache(
        Profile(identifier=uid, uid=uid, username="", builds={"furina": [live, saved_build]}, fetched_at=datetime.now())
    )

    window = MainWindow()
    window.builds = {"furina": [live, saved_build]}
    window.populate_combo_items()
    window.controls_panel.profile_edit.setText(uid)
    window.team_fields.combos[0][0].setCurrentText("Furina")

    window.build_selected(0, 0, saved_build)

    member = window.project.teams[0][0]
    assert member.build is not None
    assert member.build.details() == ("203201", "Aqua Simulacra", 6, 5)

    project_path = tmp_path / "chosen-build.json"
    monkeypatch.setattr(
        project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )
    window.save_project()

    written = json.loads(project_path.read_text(encoding="utf-8"))["teams"][0][0]["build"]
    assert (written["costume_id"], written["weapon_name"], written["constellation"], written["refinement"]) == (
        "203201",
        "Aqua Simulacra",
        6,
        5,
    )

    # The profile has moved on: the same build name now carries other details.
    drifted = make_build("Furina", "Bow DPS")
    save_profile_cache(
        Profile(identifier=uid, uid=uid, username="", builds={"furina": [live, drifted]}, fetched_at=datetime.now())
    )
    monkeypatch.setattr(
        project_io.QFileDialog, "getOpenFileName", staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )

    window.open_project()

    reopened = window.project.teams[0][0].build
    assert reopened is not None
    assert reopened.details() == ("203201", "Aqua Simulacra", 6, 5)

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def _prepare_export_window(window: MainWindow, tmp_path: Path, names: list[str]) -> None:
    assets = create_test_assets(tmp_path / "assets", names)
    window.builds = {asset.build.name.casefold(): [asset.build] for asset in assets.values()}
    fill_window_teams(window, names)
    window.rebuild_team_fields()
    window.assets = assets


class RecordingCritical:
    """Records `QMessageBox.critical` calls, which `dialogs.show_error` makes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def critical(self, parent: object, title: str, text: str) -> None:
        self.calls.append((title, text))


def test_export_refuses_a_team_whose_slot_names_no_loaded_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The always-on preview tolerates placeholders; the export still does not."""
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    # One slot names a character the loaded profile has no build for, which is
    # exactly the slot the preview would draw as a placeholder panel.
    window.team_fields.combos[1][3].setCurrentText("Somebody Else")

    recorder = RecordingCritical()
    monkeypatch.setattr(dialogs, "QMessageBox", recorder)
    for chooser in ("getSaveFileName", "getExistingDirectory"):
        monkeypatch.setattr(
            project_io.QFileDialog,
            chooser,
            staticmethod(lambda *args, **kwargs: pytest.fail("an incomplete team must not reach the export dialog")),
        )

    window.export()

    assert [title for title, _ in recorder.calls] == ["Export failed"]
    assert "Somebody Else" in recorder.calls[0][1]
    assert list(tmp_path.glob("*.png")) == []

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_export_abyss_writes_the_file_chosen_in_the_save_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.controls_panel.output_name.setText("prefilled")

    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        project_io.QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *args, **kwargs: pytest.fail("abyss export must not ask for a folder")),
    )
    chosen = tmp_path / "out" / "chosen.png"
    default_names: list[str] = []

    def fake_save_dialog(parent: object, title: str, default_name: str, name_filter: str) -> tuple[str, str]:
        default_names.append(default_name)
        return str(chosen), "PNG (*.png)"

    monkeypatch.setattr(project_io.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.export()

    assert [Path(name).name for name in default_names] == ["prefilled.png"]
    assert chosen.exists()
    assert list(chosen.parent.glob("*.png")) == [chosen]
    assert window.controls_panel.output_name.text() == "chosen"
    assert window.project.output_name == "chosen"

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_export_stygian_still_asks_for_a_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    window = MainWindow()
    # Switching the mode replaces window.project, so fill the teams afterwards.
    window.controls_panel.stygian_radio.setChecked(True)
    names = [*TEAM_NAMES, "Xingqiu", "Ganyu", "Raiden Shogun", "Yelan"]
    _prepare_export_window(window, tmp_path, names)
    window.controls_panel.output_name.setText("bosses")

    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        project_io.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: pytest.fail("stygian export must not ask for a file name")),
    )
    directory = tmp_path / "out"
    monkeypatch.setattr(
        project_io.QFileDialog, "getExistingDirectory", staticmethod(lambda *args, **kwargs: str(directory))
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
        project_io.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(project_file), ""))
    )
    window.open_project()

    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.controls_panel.output_name.setText("prefilled")
    default_paths: list[str] = []

    def fake_save_dialog(parent: object, title: str, default_path: str, name_filter: str) -> tuple[str, str]:
        default_paths.append(default_path)
        return str(tmp_path / "out" / "chosen.png"), "PNG (*.png)"

    monkeypatch.setattr(project_io.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

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
        project_io.QFileDialog,
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
    window, _ = prepare_cached_open(tmp_path, monkeypatch, datetime.now() - timedelta(minutes=5))

    # Inside the range `sync_controls()` clamps to, so the assertions below
    # read the preset back rather than the reachable maximum.
    reframed = 0.1

    def fake_apply_to(editor: MainWindow, member: Any) -> None:
        member.offset_x = reframed

    monkeypatch.setattr(window._presets, "apply_to", fake_apply_to)

    window.open_project()

    assert window.project.teams[0][0].offset_x != reframed
    assert not window.is_dirty()

    settle_downloads_and_render(window, app)

    assert window.project.teams[0][0].offset_x == reframed

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_saving_an_opened_project_overwrites_it_without_a_dialog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window, _ = prepare_cached_open(tmp_path, monkeypatch, datetime.now() - timedelta(minutes=5))

    window.open_project()
    settle_downloads_and_render(window, app)
    project_path = tmp_path / "project.json"
    assert window.project_path == project_path

    window.project.teams[0][0].offset_x = 0.125
    monkeypatch.setattr(
        project_io.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: pytest.fail("saving an opened project must not ask for a path")),
    )

    window.save_project()

    assert load_project(project_path).teams[0][0].offset_x == 0.125
    assert not window.is_dirty()

    window.close()
    app.processEvents()


def test_saving_without_a_path_asks_once_and_reuses_the_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window = MainWindow()
    assert window.project_path is None
    window.project.teams[0][0].offset_x = 0.3

    first = tmp_path / "first.json"
    asked: list[str] = []

    def fake_save_dialog(parent: object, title: str, default_path: str, name_filter: str) -> tuple[str, str]:
        asked.append(default_path)
        return str(first), "JSON (*.json)"

    monkeypatch.setattr(project_io.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.save_project()

    assert first.exists()
    assert window.project_path == first
    assert len(asked) == 1

    window.project.teams[0][0].offset_x = 0.4
    window.save_project()

    assert len(asked) == 1
    assert load_project(first).teams[0][0].offset_x == 0.4
    assert window.project_path == first

    window.close()
    app.processEvents()


def test_save_as_asks_again_even_when_the_project_has_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window = MainWindow()
    first = tmp_path / "first.json"
    monkeypatch.setattr(
        project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(first), ""))
    )
    window.save_project()
    assert window.project_path == first

    second = tmp_path / "second.json"
    monkeypatch.setattr(
        project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(second), ""))
    )

    window.save_project_as()

    assert second.exists()
    assert window.project_path == second

    window.close()
    app.processEvents()


def test_cancelling_save_as_keeps_the_previous_file_and_the_dirty_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    monkeypatch.setattr(dialogs, "QMessageBox", ForbiddenMessageBox)
    window = MainWindow()
    first = tmp_path / "first.json"
    monkeypatch.setattr(
        project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: (str(first), ""))
    )
    window.save_project()
    window.project.teams[0][0].offset_x = 0.42
    assert window.is_dirty()

    monkeypatch.setattr(project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *args, **kwargs: ("", "")))

    window.save_project_as()

    assert window.project_path == first
    assert window.is_dirty()

    close_ignoring_unsaved_changes(window, app, monkeypatch)


def test_export_defaults_to_the_saved_project_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path / "app-data"))
    app = qapp()
    project_dir = tmp_path / "saved"
    project_dir.mkdir()
    project_file = project_dir / "thumbnail-project.json"

    window = MainWindow()
    _prepare_export_window(window, tmp_path, TEAM_NAMES)
    window.controls_panel.output_name.setText("prefilled")

    monkeypatch.setattr(dialogs, "QMessageBox", StubMessageBox)
    monkeypatch.setattr(
        project_io.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(project_file), ""))
    )
    window.save_project()

    default_paths: list[str] = []

    def fake_save_dialog(parent: object, title: str, default_path: str, name_filter: str) -> tuple[str, str]:
        default_paths.append(default_path)
        return str(tmp_path / "out" / "chosen.png"), "PNG (*.png)"

    monkeypatch.setattr(project_io.QFileDialog, "getSaveFileName", staticmethod(fake_save_dialog))

    window.export()

    assert default_paths == [str(project_dir / "prefilled.png")]

    close_ignoring_unsaved_changes(window, app, monkeypatch)
