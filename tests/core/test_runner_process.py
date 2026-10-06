"""Runner tests with real spawned children and fake models (tests/fakes/runner.py)."""

import asyncio
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil
import pytest
from aTrain_core import runner
from aTrain_core.globals import TIMESTAMP_FORMAT
from tests.unit.test_jobs import make_spec

FIXTURE = Path(__file__).parent.parent / "fixtures" / "sample_short.mp3"
FACTORY = "tests.fakes.runner:load_transcriber"
REPO_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """Two jobs on copies of the fixture; children write into an archive under tmp_path."""
    monkeypatch.setenv("ATRAIN_USER_DIR", str(tmp_path / "atrain"))
    monkeypatch.delenv("FAKE_RUNNER", raising=False)
    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    result = []
    for job_id in ("job1", "job2"):
        source = tmp_path / f"{job_id}.mp3"
        shutil.copy(FIXTURE, source)
        spec = make_spec(
            id=job_id,
            source=source,
            display_name=source.name,
            speaker_detection=False,
            export_dir=None,
        )
        result.append(runner.PhaseJob(spec, timestamp, tmp_path / "work" / job_id))
    return result


def fake(monkeypatch, **config):
    monkeypatch.setenv("FAKE_RUNNER", json.dumps(config))


async def drive(handle: runner.PhaseHandle, on_event=None) -> list:
    """Return all events of the child."""
    events = []
    async for event in handle.events():
        events.append(event)
        if on_event:
            on_event(event)
    return events


def kinds(events) -> list[str]:
    return [type(e).__name__ for e in events if not isinstance(e, runner.JobProgress)]


def test_events_arrive_in_order(jobs):
    events = asyncio.run(drive(runner.launch_phase1(jobs[0], FACTORY)))

    assert kinds(events) == ["JobDone", "PhaseFinished"]
    assert [e.job_id for e in events if isinstance(e, runner.JobDone)] == ["job1"]


def test_crash_during_job_gives_phase_died(jobs, monkeypatch):
    fake(monkeypatch, crash_on_job=1)
    events = asyncio.run(drive(runner.launch_phase1(jobs[0], FACTORY)))

    assert kinds(events) == ["PhaseDied"]
    assert events[-1].exitcode == 1


def test_kill_during_a_slow_job(jobs, monkeypatch):
    fake(monkeypatch, sleep=60)
    handle = runner.launch_phase1(jobs[0], FACTORY)

    def kill_when_transcribing(event):
        if isinstance(event, runner.JobProgress):
            handle.kill()

    started = time.monotonic()
    events = asyncio.run(drive(handle, kill_when_transcribing))

    assert time.monotonic() - started < 30
    assert not handle.process.is_alive()
    assert isinstance(events[-1], runner.PhaseDied)


HELPER = """
import sys, time
from pathlib import Path
from aTrain_core import runner
from tests.unit.test_jobs import make_spec

source, work_dir = Path(sys.argv[2]), Path(sys.argv[3])
spec = make_spec(id="slow", source=source, display_name=source.name, speaker_detection=False)
job = runner.PhaseJob(spec, "2026-09-30 14-05-12", work_dir)
handle = runner.launch_phase1(job, sys.argv[1])
while not isinstance(handle.conn.recv(), runner.JobProgress):
    pass
print(handle.process.pid, flush=True)  # the child is now busy with a 60 s job
time.sleep(60)
"""


def test_watchdog_ends_busy_child_when_parent_dies(jobs, monkeypatch):
    fake(monkeypatch, sleep=60)
    job = jobs[0]
    helper = subprocess.Popen(
        [sys.executable, "-c", HELPER, FACTORY, str(job.spec.source), str(job.work_dir)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        child = psutil.Process(int(helper.stdout.readline()))
    finally:
        helper.kill()
        helper.wait(10)

    # The child doesn't read the pipe while it works; only its watchdog can end it.
    try:
        child.wait(timeout=10)
    except psutil.TimeoutExpired:
        child.kill()
        raise
