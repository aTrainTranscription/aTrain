"""Unit tests for aTrain_core.jobs.QueueLock (one queue per machine)."""

import subprocess
import sys

import pytest
from aTrain_core.jobs import QueueLock, QueueLockedError

HOLD_LOCK = """
import sys, time
from pathlib import Path
from aTrain_core.jobs import QueueLock
lock = QueueLock(Path(sys.argv[1]))  # keep a reference: a collected FileLock releases
lock.acquire()
print("locked", flush=True)
time.sleep(60)
"""


def acquire_and_release(root):
    lock = QueueLock(root)
    lock.acquire()
    lock.release()


def test_lock_held_by_other_process_until_it_dies(tmp_path):
    holder = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(tmp_path)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(QueueLockedError):
            QueueLock(tmp_path).acquire()
    finally:
        holder.kill()
        holder.wait(10)
    acquire_and_release(tmp_path)
