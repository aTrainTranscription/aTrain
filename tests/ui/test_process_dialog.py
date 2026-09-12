"""Tests for the process dialog's progress polling.

`update_progress` reads a multiprocessing Manager dict every 100 ms. When a
transcription is cancelled (stop button -> nicegui.run.tear_down), the
manager process dies while the dialog tears down, and a late timer tick
must not blow up on the dead pipe.
"""

from datetime import datetime

from aTrain.components.dialogs import process
from nicegui import app


class DeadManagerDict:
    """Mimics a DictProxy whose manager process has exited."""

    def __getitem__(self, key):
        raise BrokenPipeError(32, "Broken pipe")


def test_update_progress_survives_torn_down_manager():
    app.storage.general["progress"] = 0.25
    process.update_progress(DeadManagerDict(), datetime.now())  # must not raise
    assert app.storage.general["progress"] == 0.25  # last known value untouched


def test_update_progress_reads_live_dict():
    app.storage.general["speaker_detection"] = False
    process.update_progress({"current": 1, "total": 4, "task": "Transcribe"}, datetime.now())
    assert app.storage.general["progress"] == 0.25
    assert app.storage.general["task_number"] == "2/2"
