"""Background downloads of the character art the always-on preview is missing.

The editor never blocks on the network: `AssetLoader.ensure()` starts a worker
for the art no slot has yet and reports each arrival through `asset_ready`, so
the preview fills its placeholder panels one character at a time.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..enka import download_assets
from ..models import Build
from .build_choices import selected_build
from .state import EditorState

# What a download is actually determined by, and therefore what two builds have
# to share before one of them can be skipped: the pair of URLs it fetches.
DownloadKey = tuple[str, str]


def _download_key(build: Build) -> DownloadKey:
    return (build.art_url, build.weapon_url)


class AssetJobSignals(QObject):
    asset_ready = Signal(object)
    finished = Signal(int, object)


class AssetJob(QRunnable):
    """Downloads one batch of builds' art on a worker thread via `QThreadPool`."""

    def __init__(self, token: int, builds: list[Build], root: Path) -> None:
        super().__init__()
        self.token = token
        self._builds = builds
        self._root = root
        self.signals = AssetJobSignals()

    def run(self) -> None:
        try:
            download_assets(self._builds, self._root, on_build=self._emit_build)
        except Exception as error:  # reported back to the GUI thread
            self.signals.finished.emit(self.token, error)
            return
        self.signals.finished.emit(self.token, None)

    def _emit_build(self, build: Build) -> None:
        self.signals.asset_ready.emit(build)


class AssetLoader(QObject):
    """Keeps the cache under `root` stocked with the art the named slots need."""

    asset_ready = Signal(object)
    progress = Signal(str)
    failed = Signal(object)

    def __init__(
        self, state: EditorState, root: Path, pool: QThreadPool, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._root = root
        self._pool = pool
        self._token = 0
        # Keyed by token rather than one flat set, so a job's URL pairs are
        # released by the job that carried them and not by whichever finishes first.
        self._in_flight: dict[int, set[DownloadKey]] = {}

    def ensure(self) -> None:
        """Start downloading the art the named team members are still missing."""
        missing = self._missing_builds()
        if not missing:
            return
        self._token += 1
        self._in_flight[self._token] = {_download_key(build) for build in missing}
        job = AssetJob(self._token, missing, self._root)
        job.signals.asset_ready.connect(self.asset_ready)
        job.signals.finished.connect(self._job_finished)
        self.progress.emit(f"Downloading art for {len(missing)} character(s) ...")
        self._pool.start(job)

    def _missing_builds(self) -> list[Build]:
        """The builds whose two files are not already cached, being fetched, or
        collected for this very batch.

        Deduplicating by the URL pair rather than by character and build name is
        what keeps two overlapping batches from writing the same temp file, and
        what lets two builds sharing a build name still fetch their own art.
        """
        # Read the editor through the Protocol on every call, see state.py.
        state = self._state
        pending = {key for keys in self._in_flight.values() for key in keys}
        missing: dict[DownloadKey, Build] = {}
        for team in state.project.teams:
            for member in team:
                if not member.name:
                    continue
                build = selected_build(state, member)
                if build is None:
                    continue
                key = _download_key(build)
                if key in pending or key in missing:
                    continue
                if build.art_path(self._root).exists() and build.weapon_path(self._root).exists():
                    continue
                missing[key] = build
        return list(missing.values())

    def _job_finished(self, token: int, error: Exception | None) -> None:
        self._in_flight.pop(token, None)
        if error is not None:
            self.failed.emit(error)
            return
        if not self._in_flight:
            # The "Downloading ..." line would otherwise claim a download is
            # still running for as long as nothing else writes to the status bar.
            self.progress.emit("Character art ready")
