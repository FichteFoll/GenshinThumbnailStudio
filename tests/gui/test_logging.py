"""Tests for the logging policy: a reported error is recorded with its
traceback, and `configure_logging()` attaches its handlers exactly once."""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from PySide6.QtWidgets import QMainWindow, QMessageBox

from genshin_thumbnail_studio.gui import dialogs, logging_setup

from .helpers import qapp


class RecordingMessageBox:
    """Records the critical popups shown, instead of putting one up."""

    StandardButton = QMessageBox.StandardButton
    critical_calls: ClassVar[list[tuple[str, str]]] = []

    @staticmethod
    def critical(parent: object, title: str, text: str) -> object:
        RecordingMessageBox.critical_calls.append((title, text))
        return QMessageBox.StandardButton.Ok


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


def test_show_error_logs_the_exception_with_its_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    app = qapp()
    RecordingMessageBox.critical_calls = []
    monkeypatch.setattr(dialogs, "QMessageBox", RecordingMessageBox)
    caplog.set_level(logging.ERROR)
    window = QMainWindow()
    try:
        raise RuntimeError("'NoneType' object is not subscriptable")
    except RuntimeError as raised:
        error = raised

    dialogs.show_error(window, "Could not load profile", error)

    records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert "'NoneType' object is not subscriptable" in caplog.text
    assert "Traceback (most recent call last)" in caplog.text
    assert RecordingMessageBox.critical_calls == [
        ("Could not load profile", "'NoneType' object is not subscriptable")
    ]

    window.close()
    app.processEvents()


@pytest.mark.usefixtures("isolated_root_logger")
def test_configure_logging_twice_attaches_one_set_of_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logging_setup, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(logging_setup, "_configured", False)

    logging_setup.configure_logging()
    after_first = len(logging.getLogger().handlers)
    logging_setup.configure_logging()

    assert len(logging.getLogger().handlers) == after_first
    assert (tmp_path / "logs" / "app.log").exists()
