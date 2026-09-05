"""The application's logging policy: a console stream, a rotating log file, and
a bridge that folds the `enka` library's `loguru` output into both.

`configure_logging()` is called once, first thing in `run()`, before any Qt
object exists, so that everything an exception path reports is recorded with its
traceback rather than only shown in a popup.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from typing import TYPE_CHECKING

from loguru import logger as loguru_logger

from ..storage import app_data_dir

if TYPE_CHECKING:
    # `Message` lives in loguru's stubs only; it is not a runtime name.
    from loguru import Message

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
LOG_FILE_MAX_BYTES = 1_000_000
LOG_FILE_BACKUP_COUNT = 3

_configured = False


def configure_logging() -> None:
    """Attach the console and file handlers and bridge `loguru`, exactly once.

    Idempotent: a second call leaves the handlers the first one attached in
    place instead of duplicating every record.
    """
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(LOG_FORMAT)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)
    root.addHandler(console)

    _attach_file_handler(root, formatter)
    _bridge_loguru()


def _attach_file_handler(root: logging.Logger, formatter: logging.Formatter) -> None:
    """Add the rotating file handler, or warn and carry on without one.

    A read-only or unwritable app data directory must not stop the app; the
    console handler alone is still a usable record.
    """
    try:
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as error:
        root.warning("Logging to a file is disabled: %s", error)
        return
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def _bridge_loguru() -> None:
    """Route the `enka` library's `loguru` records into `logging` at WARNING.

    The library logs through `loguru`, whose default sink is stderr at DEBUG and
    prints a line for every asset file it opens. Its "consider calling
    update_assets()" errors, however, are the library's only report that its
    cached data files do not describe something, so the output cannot simply be
    silenced: replacing the sink with one at WARNING keeps those and drops the
    noise, in the same stream and the same file as everything else.
    """
    loguru_logger.remove()
    loguru_logger.add(_forward_to_logging, level="WARNING")


def _forward_to_logging(message: Message) -> None:
    record = message.record
    # loguru has level names of its own (TRACE, SUCCESS); anything `logging`
    # does not define as a level constant is reported at WARNING, which is the
    # floor this sink is added at anyway.
    level = getattr(logging, record["level"].name, logging.WARNING)
    if not isinstance(level, int):
        level = logging.WARNING
    logging.getLogger("enka").log(level, record["message"])
