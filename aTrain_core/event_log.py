"""Central log of security-relevant events (#339).

`aTrain start` calls setup_event_log(). Worker processes started with spawn do not
get its handler, so only one process writes the file: RotatingFileHandler is not
safe across processes. With fork, as in the Flatpak on ARM, a worker inherits the
handler, so code that runs in a worker must not call log_event().

Transcript text and the initial prompt do not belong in this log.
"""

import logging
import textwrap
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aTrain_core.globals import EVENT_LOG_DIR

EVENT_LOG_FILENAME = "atrain.log"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 4  # with the current file, 5 files at most

logger = logging.getLogger("aTrain.events")
logger.setLevel(logging.INFO)
logger.propagate = False
logger.addHandler(logging.NullHandler())


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Indents the traceback, so a line break in an exception message cannot start
        # a line that looks like a new entry. This happens here and not in
        # formatException(): another handler on the logger may format the record
        # first and store an unindented traceback.
        first, _, rest = super().format(record).partition("\n")
        return f"{first}\n{textwrap.indent(rest, '    ')}" if rest else first


def setup_event_log(log_dir: Path = EVENT_LOG_DIR) -> Path | None:
    """Start writing events to a rotating file and return its path.

    Returns None if the folder is not writable: a missing log must not keep the
    app from starting.
    """
    path = log_dir / EVENT_LOG_FILENAME
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
    except OSError as error:
        print(f"Cannot write the event log to {path}: {error}")
        return None
    handler.setFormatter(_Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S%z"))
    logger.addHandler(handler)
    return path


def log_event(event: str, level: int = logging.INFO, exc_info=None, **fields) -> None:
    """Write one event.

    repr() escapes line breaks in the values, so a value cannot add a fake entry.
    """
    details = " ".join(f"{key}={value!r}" for key, value in fields.items())
    logger.log(level, "%s", f"{event} {details}".rstrip(), exc_info=exc_info)


def log_unhandled_exception(error: Exception) -> None:
    # NiceGUI hands an error while building a page to this hook twice. The marker
    # on the exception keeps the second call out of the log.
    if getattr(error, "_in_event_log", False):
        return
    error._in_event_log = True  # type: ignore[attr-defined]
    log_event("unhandled_exception", logging.ERROR, exc_info=error, error=str(error))
