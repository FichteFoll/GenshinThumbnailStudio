"""Background downloads of the character art the always-on preview is missing.

The editor never blocks on the network: `AssetLoader.ensure()` starts a worker
for the art no slot has yet and reports each arrival through `asset_ready`, so
the preview fills its placeholder panels one character at a time.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from ..akasha import download_assets
from ..models import Asset, Build
from .state import EditorState


class AssetJobSignals(QObject):
    asset_ready = Signal(str, object)
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
            download_assets(self._builds, self._root, on_asset=self._emit_asset)
        except Exception as error:  # reported back to the GUI thread
            self.signals.finished.emit(self.token, error)
            return
        self.signals.finished.emit(self.token, None)

    def _emit_asset(self, key: str, asset: Asset) -> None:
        self.signals.asset_ready.emit(key, asset)


class AssetLoader(QObject):
    """Keeps the editor's `assets` filled in for the characters its slots name."""

    asset_ready = Signal(str, object)
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
        # Keyed by token rather than one flat set, so a job's names are released
        # by the job that carried them and not by whichever finishes first.
        self._in_flight: dict[int, set[str]] = {}

    def ensure(self) -> None:
        """Start downloading the art the named team members are still missing."""
        missing = self._missing_builds()
        if not missing:
            return
        self._token += 1
        self._in_flight[self._token] = {build.name.casefold() for build in missing}
        job = AssetJob(self._token, missing, self._root)
        job.signals.asset_ready.connect(self.asset_ready)
        job.signals.finished.connect(self._job_finished)
        self.progress.emit(f"Downloading art for {len(missing)} character(s) ...")
        self._pool.start(job)

    def _missing_builds(self) -> list[Build]:
        # Read the editor through the Protocol on every call, see state.py.
        state = self._state
        pending = {name for names in self._in_flight.values() for name in names}
        missing: dict[str, Build] = {}
        for team in state.project.teams:
            for member in team:
                key = member.name.casefold()
                if not key or key in state.assets or key in pending or key in missing:
                    continue
                build = state.builds.get(key)
                if build is not None:
                    missing[key] = build
        return list(missing.values())

    def _job_finished(self, token: int, error: Exception | None) -> None:
        self._in_flight.pop(token, None)
        if error is not None:
            self.failed.emit(error)
