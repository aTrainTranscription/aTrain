"""Unit tests for aTrain_core/event_log.py, the central log of security-relevant events (#339).

Torch- and NiceGUI-free, so they run in the lightweight `unit` CI job.
"""

from logging.handlers import RotatingFileHandler

import pytest
from aTrain_core import event_log


@pytest.fixture
def clean_logger():
    """setup_event_log adds a handler to a logger shared by the whole process.

    Remove it after the test.
    """
    yield
    for handler in list(event_log.logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            event_log.logger.removeHandler(handler)
            handler.close()


@pytest.fixture
def log_file(tmp_path, clean_logger):
    path = event_log.setup_event_log(tmp_path / "logs")
    assert path == tmp_path / "logs" / "atrain.log", "setup should create the folder and file"
    return path


def test_writes_one_line_per_event_with_its_fields(log_file):
    event_log.log_event("server_started", version="1.5.0", port=8000)

    line = log_file.read_text(encoding="utf-8").strip()
    assert line.endswith("INFO server_started version='1.5.0' port=8000"), line


def test_event_without_fields_has_no_trailing_space(log_file):
    event_log.log_event("server_stopped")

    assert log_file.read_text(encoding="utf-8").endswith("INFO server_stopped\n")


def test_a_line_break_in_a_value_cannot_forge_a_second_entry(log_file):
    event_log.log_event("server_started", version="1.5.0\n2026-01-01 00:00:00 INFO server_stopped")

    assert len(log_file.read_text(encoding="utf-8").splitlines()) == 1


def test_keeps_non_ascii_text(log_file):
    event_log.log_event("unhandled_exception", error="Übertragung abgebrochen: Größe")

    assert "Übertragung abgebrochen: Größe" in log_file.read_text(encoding="utf-8")


def test_keeps_five_files_at_most(tmp_path, clean_logger, monkeypatch):
    monkeypatch.setattr(event_log, "MAX_BYTES", 200)
    event_log.setup_event_log(tmp_path)

    for number in range(200):
        event_log.log_event("server_started", port=number)

    names = sorted(path.name for path in tmp_path.iterdir())
    assert names == ["atrain.log", *[f"atrain.log.{n}" for n in range(1, 5)]], names


def test_without_setup_events_go_nowhere(tmp_path, monkeypatch):
    """Without setup_event_log, as in a worker process, events go nowhere."""
    monkeypatch.chdir(tmp_path)

    event_log.log_event("server_stopped")

    assert list(tmp_path.iterdir()) == []
    assert event_log.logger.propagate is False, "the event must not reach the root logger"


def test_an_unwritable_folder_does_not_stop_the_app(tmp_path, clean_logger):
    blocked = tmp_path / "a_file"
    blocked.write_text("")

    assert event_log.setup_event_log(blocked / "logs") is None

    event_log.log_event("server_started")  # still must not raise


def test_records_the_traceback_of_an_exception(log_file):
    try:
        raise ValueError("boom")
    except ValueError as error:
        event_log.log_unhandled_exception(error)

    text = log_file.read_text(encoding="utf-8")
    assert "ERROR unhandled_exception error='boom'" in text
    assert "Traceback" in text


def test_the_same_exception_is_logged_once(log_file):
    """NiceGUI passes an error while building a page to the hook twice."""
    first, second = ValueError("boom"), ValueError("boom")

    for error in (first, first, second):
        event_log.log_unhandled_exception(error)

    assert log_file.read_text(encoding="utf-8").count("ERROR unhandled_exception") == 2


def test_a_line_break_in_an_exception_cannot_forge_an_entry(log_file):
    try:
        raise ValueError("boom\n2026-01-01 00:00:00+0100 INFO transcript_deleted file_id='x'")
    except ValueError as error:
        event_log.log_unhandled_exception(error)

    lines = log_file.read_text(encoding="utf-8").splitlines()
    entries = [line for line in lines if not line.startswith(" ")]
    assert entries == lines[:1], lines
