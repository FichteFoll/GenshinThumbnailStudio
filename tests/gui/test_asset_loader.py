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
from genshin_thumbnail_studio.models import Asset, Build, Project


@dataclass
class StubState:
    """The minimal `EditorState` the loader needs."""

    project: Project
    builds: dict[str, Build] = field(default_factory=dict)
    assets: dict[str, Asset] = field(default_factory=dict)


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


def make_asset(root: Path, build: Build) -> Asset:
    return Asset(build, root / f"{build.name}.png", root / f"{build.name}-weapon.png")


DownloadAssets = Callable[..., dict[str, Asset]]


def fake_downloader(requested: list[list[str]]) -> DownloadAssets:
    """A `download_assets` stand-in that fabricates assets without any network."""

    def fake_download_assets(
        builds: list[Build],
        root: Path,
        progress: object = None,
        on_asset: Callable[[str, Asset], None] | None = None,
    ) -> dict[str, Asset]:
        requested.append([build.name for build in builds])
        downloaded: dict[str, Asset] = {}
        for build in builds:
            key = build.name.casefold()
            downloaded[key] = make_asset(root, build)
            if on_asset:
                on_asset(key, downloaded[key])
        return downloaded

    return fake_download_assets


def make_loader(names: list[str], root: Path) -> tuple[AssetLoader, StubState, InlinePool]:
    project = Project.blank("abyss")
    members = [member for team in project.teams for member in team]
    for member, name in zip(members, names, strict=False):
        member.name = name
    state = StubState(project=project, builds={name.casefold(): make_build(name) for name in names})
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
    state.assets["nahida"] = make_asset(tmp_path, state.builds["nahida"])
    requested: list[list[str]] = []
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader(requested))

    loader.ensure()

    assert requested == [["Furina"]]


def test_ensure_emits_asset_ready_per_downloaded_character(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loader, _, _ = make_loader(["Furina", "Nahida"], tmp_path)
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader([]))
    arrived: list[str] = []

    def record(key: str, asset: Asset) -> None:
        arrived.append(key)

    loader.asset_ready.connect(record)

    loader.ensure()

    assert arrived == ["furina", "nahida"]


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
    loader, state, pool = make_loader(["Furina"], tmp_path)
    requested: list[list[str]] = []
    monkeypatch.setattr(asset_loader, "download_assets", fake_downloader(requested))
    loader.asset_ready.connect(state.assets.__setitem__)

    loader.ensure()
    loader.ensure()

    assert requested == [["Furina"]]
    assert len(pool.started) == 1


def test_a_failed_download_is_reported_and_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loader, _, _ = make_loader(["Furina"], tmp_path)

    def failing_download_assets(*args: object, **kwargs: object) -> dict[str, Asset]:
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
