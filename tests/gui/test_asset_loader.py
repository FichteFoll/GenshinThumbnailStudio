"""Tests for `gui.asset_loader.AssetLoader`, the background character-art downloads.

The pool stand-in runs each job on the calling thread, so the loader's signals
arrive as direct connections and every assertion here is synchronous.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QRunnable, QThreadPool

from genshin_thumbnail_studio.gui import asset_loader
from genshin_thumbnail_studio.gui.asset_loader import AssetLoader
from genshin_thumbnail_studio.models import Build, Project


@dataclass
class StubState:
    """The minimal `EditorState` the loader needs."""

    project: Project
    builds: dict[str, list[Build]] = field(default_factory=dict)
    art_root: Path = Path("assets")


class InlinePool:
    """Stands in for `QThreadPool`, running each job where it was started."""

    def __init__(self) -> None:
        self.started: list[QRunnable] = []

    def start(self, job: QRunnable) -> None:
        self.started.append(job)
        job.run()


def make_build(name: str) -> Build:
    return Build(
        name=name,
        constellation=0,
        refinement=1,
        weapon_name="Weapon",
        costume_id=None,
        build_id=f"{name}-build",
        art_url=f"https://example.invalid/{name}.png",
        weapon_url="https://example.invalid/weapon.png",
    )


def publish(root: Path, build: Build) -> None:
    """Put empty files where the build says its two files belong.

    The loader asks nothing of them but that they exist, which is exactly what
    "this build has been downloaded" means now.
    """
    for path in (build.art_path(root), build.weapon_path(root)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


DownloadAssets = Callable[..., None]


def fake_downloader(requested: list[list[str]]) -> DownloadAssets:
    """A `download_assets` stand-in that publishes the files without any network."""

    def fake_download_assets(
        builds: list[Build],
        root: Path,
        progress: object = None,
        on_build: Callable[[Build], None] | None = None,
    ) -> None:
        requested.append([build.name for build in builds])
        for build in builds:
            publish(root, build)
            if on_build:
                on_build(build)

    return fake_download_assets


def make_loader(names: list[str], root: Path) -> tuple[AssetLoader, StubState, InlinePool]:
    project = Project.blank("abyss")
    members = [member for team in project.teams for member in team]
    for member, name in zip(members, names, strict=False):
        member.name = name
    state = StubState(project=project, builds={name.casefold(): [make_build(name)] for name in names})
    pool = InlinePool()
    loader = AssetLoader(state, root, cast(QThreadPool, pool))
    return loader, state, pool


def test_ensure_requests_only_the_builds_that_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, state, _ = make_loader(["Furina", "Nahida"], tmp_path)
    # A third slot names a character the profile does not know, and a fourth is
    # already downloaded; neither may reach the downloader.
    state.project.teams[0][2].name = "Unknown Traveler"
    publish(tmp_path, state.builds["nahida"][0])
    requested: list[list[str]] = []
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader(requested))

    loader.ensure()

    assert requested == [["Furina"]]


def test_ensure_emits_asset_ready_per_downloaded_character(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, _, _ = make_loader(["Furina", "Nahida"], tmp_path)
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader([]))
    arrived: list[Build] = []
    loader.asset_ready.connect(arrived.append)

    loader.ensure()

    assert [build.name for build in arrived] == ["Furina", "Nahida"]


def test_progress_reports_the_batch_finishing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A finished batch has to say so, or the status bar keeps claiming a download."""
    loader, _, _ = make_loader(["Furina", "Nahida"], tmp_path)
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader([]))
    reported: list[str] = []
    loader.progress.connect(reported.append)

    loader.ensure()

    assert reported == ["Downloading art for 2 character(s) ...", "Character art ready"]


def test_ensure_starts_no_job_for_art_that_is_already_downloaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, _, pool = make_loader(["Furina"], tmp_path)
    requested: list[list[str]] = []
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader(requested))

    loader.ensure()
    loader.ensure()

    assert requested == [["Furina"]]
    assert len(pool.started) == 1


def test_a_failed_download_is_reported_and_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loader, _, _ = make_loader(["Furina"], tmp_path)

    def failing_download_assets(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Enka is unreachable")

    monkeypatch.setattr(asset_loader, "download_assets", failing_download_assets)
    failures: list[object] = []
    loader.failed.connect(failures.append)

    loader.ensure()

    assert [str(error) for error in failures] == ["Enka is unreachable"]

    # The failed name did not stay in flight, so the next attempt retries it.
    requested: list[list[str]] = []
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader(requested))

    loader.ensure()

    assert requested == [["Furina"]]


def test_two_builds_fetching_the_same_two_urls_share_one_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deduplication is by the URL pair, which is what a download is determined by.

    Keying it by character and build name instead let two builds with identical
    URLs but different names into one batch, or into two overlapping ones, where
    they raced each other for the same temp file.
    """
    loader, state, _ = make_loader(["Furina", "Furina"], tmp_path)
    twin = make_build("Furina")
    twin.build_name = "Vape"
    state.project.teams[0][1].build = twin
    requested: list[list[str]] = []
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader(requested))

    loader.ensure()

    assert requested == [["Furina"]]


def test_two_builds_sharing_a_build_name_each_get_their_own_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R6: a shared build name is not a shared download.

    `build_choices()` deliberately offers two entries of one name, and their art
    differs; the old name-based key collapsed them onto one fetch.
    """
    loader, state, _ = make_loader(["Furina", "Furina"], tmp_path)
    other = make_build("Furina")
    other.art_url = "https://example.invalid/Furina-vape.png"
    state.project.teams[0][0].build = make_build("Furina")
    state.project.teams[0][1].build = other
    requested: list[list[str]] = []
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader(requested))

    loader.ensure()

    assert requested == [["Furina", "Furina"]]
