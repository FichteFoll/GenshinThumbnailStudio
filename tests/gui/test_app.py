"""Tests for `run()`'s `--smoke-test` mode: the event loop ends on its own,
with the exit code telling whether the first preview render arrived."""

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QTimer

from genshin_thumbnail_studio.gui import app, logging_setup, render_job
from genshin_thumbnail_studio.models import Project

from .helpers import qapp

# Longer than `run()`'s own timeout, so it only fires when `run()` would
# otherwise wait for the user; the sentinel then fails the test instead of
# hanging it.
HANG_GUARD_MS = 40_000
HANG_GUARD_EXIT_CODE = 99


@pytest.fixture
def isolated_root_logger() -> Iterator[None]:
    """Keep `configure_logging()`'s handlers out of the rest of the suite."""
    root = logging.getLogger()
    handlers = root.handlers[:]
    level = root.level
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def smoke_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_root_logger: None) -> None:
    monkeypatch.setenv("GENSHIN_THUMBNAIL_STUDIO_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["app", "--smoke-test"])
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(logging_setup, "_configured", False)


def run_guarded() -> int:
    """`run()`, with its event loop ended by a sentinel exit code should it hang."""
    application = qapp()
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(lambda: application.exit(HANG_GUARD_EXIT_CODE))
    guard.start(HANG_GUARD_MS)
    try:
        return app.run()
    finally:
        guard.stop()


@pytest.mark.usefixtures("smoke_run")
def test_smoke_test_exits_zero_after_the_first_preview_render() -> None:
    assert run_guarded() == 0


@pytest.mark.usefixtures("smoke_run")
def test_smoke_test_exits_one_when_the_preview_render_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def failing_render(project: Project, art_root: Path) -> Image.Image:
        raise RuntimeError("render exploded")

    monkeypatch.setattr(render_job, "render_preview", failing_render)

    assert run_guarded() == 1
    assert "render exploded" in caplog.text
