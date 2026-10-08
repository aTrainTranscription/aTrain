"""QueueService tests with a fake launcher: fake phase handles that answer like a child."""

import asyncio

import pytest
from aTrain_core import outputs
from aTrain_core.jobs import JobStatus, JobStore, Step
from aTrain_core.queue_service import QueueService
from aTrain_core.runner import (
    RAW_CHECKPOINT,
    JobDone,
    JobFailed,
    JobProgress,
    PhaseDied,
    PhaseFinished,
)
from aTrain_core.settings import ComputeType, Device
from tests.unit.test_jobs import make_spec


class FakeHandle:
    """Behaves like a phase child running one job. Per job id, `outcomes` says what
    happens: "done" (default), "fail", "crash" or "hang" (works until killed). A job with a
    gate waits for it first."""

    def __init__(self, launcher, phase, job):
        self.launcher, self.phase, self.job = launcher, phase, job
        self.killed = asyncio.Event()

    async def events(self):
        launcher, job = self.launcher, self.job
        job_id = job.spec.id
        if job_id in launcher.gates:
            await launcher.gates[job_id].wait()
        outcome = launcher.outcomes.get(job_id, "done")
        yield JobProgress(job_id, "Transcribe", 1, 2)
        if outcome == "fail":
            yield JobFailed(job_id, Step.TRANSCRIPTION, "model error", "Traceback")
        elif outcome == "crash":
            yield PhaseDied(1)
            return
        elif outcome == "hang":
            await self.killed.wait()
        elif self.phase == 1 and job.spec.speaker_detection:
            job.work_dir.mkdir(parents=True, exist_ok=True)
            outputs.write_checkpoint(
                job.work_dir / RAW_CHECKPOINT,
                transcript={"segments": []},
                audio_duration=5,
                source=job.spec.source,
            )
        else:
            file_id = f"{job_id}-archive"
            (outputs.TRANSCRIPT_DIR / file_id).mkdir(parents=True)
            yield JobDone(job_id, file_id, 5, [])
        # events sent before a kill still arrive
        yield PhaseDied(-9) if self.killed.is_set() else PhaseFinished()

    def kill(self):
        self.killed.set()


class FakeLauncher:
    def __init__(self):
        self.launches: list[tuple[int, object]] = []
        self.handles: list[FakeHandle] = []
        self.outcomes: dict[str, str] = {}
        self.gates: dict[str, asyncio.Event] = {}
        self.launch_error_models: set[str] = set()

    def launch(self, phase):
        def launch(job):
            if phase == 1 and job.spec.model in self.launch_error_models:
                raise OSError("cannot start the process")
            self.launches.append((phase, job))
            handle = FakeHandle(self, phase, job)
            self.handles.append(handle)
            return handle

        return launch

    def dispatched(self) -> list[str]:
        return [handle.job.spec.id for handle in self.handles]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(outputs, "TRANSCRIPT_DIR", tmp_path / "transcriptions")
    launcher = FakeLauncher()
    store = JobStore(tmp_path / "queue")
    service = QueueService(
        store, launch_phase1=launcher.launch(1), launch_phase2=launcher.launch(2)
    )
    return tmp_path, store, service, launcher


def spec(tmp_path, job_id, **overrides):
    source = tmp_path / f"{job_id}.mp3"
    source.write_bytes(b"audio " + job_id.encode())
    values = {"device": Device.CPU, "compute_type": ComputeType.INT8, "speaker_detection": False}
    values.update(overrides)
    return make_spec(id=job_id, source=source, display_name=source.name, export_dir=None, **values)


def status(store, job_id):
    return store.get(job_id)[1].status


async def until(condition, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


async def settle(service):
    await until(
        lambda: all(
            state.status in {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}
            for _, state in service.jobs()
        )
    )


@pytest.fixture
async def started(env):
    _tmp_path, _store, service, _launcher = env
    await service.start()
    yield env
    await service.stop()


async def test_job_without_speaker_detection_is_done_in_phase_1(started):
    tmp_path, store, service, launcher = started
    staged = store.uploads_root / "a" / "a.mp3"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"audio")
    store.work_dir("a").mkdir(parents=True)
    job = spec(tmp_path, "a")
    service.enqueue([job.__class__.from_json({**job.to_json(), "source": str(staged)})])
    await settle(service)

    state = store.get("a")[1]
    assert state.status == JobStatus.DONE and state.file_id == "a-archive"
    assert [phase for phase, _ in launcher.launches] == [1]
    assert not store.work_dir("a").exists() and not staged.parent.exists()


async def test_speaker_detection_runs_right_after_the_transcription(started):
    tmp_path, store, service, launcher = started
    service.enqueue(
        [spec(tmp_path, "a", speaker_detection=True), spec(tmp_path, "b", speaker_detection=True)]
    )
    await settle(service)

    assert [phase for phase, _ in launcher.launches] == [1, 2, 1, 2]
    assert launcher.dispatched() == ["a", "a", "b", "b"]
    assert status(store, "a") == status(store, "b") == JobStatus.DONE


async def test_jobs_run_in_queue_order(started):
    tmp_path, _store, service, launcher = started
    service.pause()
    service.enqueue([spec(tmp_path, "a"), spec(tmp_path, "b", model="small"), spec(tmp_path, "c")])
    service.resume()
    await settle(service)

    assert launcher.dispatched() == ["a", "b", "c"]
    assert [job.spec.model for _, job in launcher.launches] == [
        "large-v3-turbo",
        "small",
        "large-v3-turbo",
    ]


async def test_cancelled_job_is_never_started(started):
    tmp_path, store, service, launcher = started
    launcher.gates["a"] = asyncio.Event()
    service.enqueue([spec(tmp_path, "a"), spec(tmp_path, "b"), spec(tmp_path, "c")])
    await until(lambda: launcher.dispatched() == ["a"])

    await service.cancel(["b"])
    service.move("c", -1)
    launcher.gates["a"].set()
    await settle(service)

    assert launcher.dispatched() == ["a", "c"]
    assert status(store, "b") == JobStatus.CANCELLED


def ids(service):
    return [spec.id for spec, _ in service.jobs()]


def test_move_swaps_queued_neighbours_only(env):
    tmp_path, store, service, _launcher = env
    store.add([spec(tmp_path, job_id) for job_id in "abcde"])
    store.update("a", status=JobStatus.RUNNING)  # running
    store.update("c", status=JobStatus.CANCELLED)

    service.move("d", -1)  # over the cancelled job to b, not below the running job
    assert ids(service) == ["a", "d", "b", "c", "e"]
    service.move("d", -1)  # first queued
    service.move("a", 1)  # not queued
    service.move("c", -1)  # not queued
    service.move("e", 1)  # last queued
    assert ids(service) == ["a", "d", "b", "c", "e"]
    service.move("d", 1)
    assert ids(service) == ["a", "b", "d", "c", "e"]
    service.move("d", 1)  # over the cancelled job to e
    assert ids(service) == ["a", "b", "c", "e", "d"]


async def test_cancel_the_running_job(started):
    tmp_path, store, service, launcher = started
    launcher.outcomes["a"] = "hang"
    service.enqueue([spec(tmp_path, "a"), spec(tmp_path, "b")])
    await until(lambda: status(store, "a") == JobStatus.RUNNING)

    await service.cancel(["a"])
    await settle(service)

    assert status(store, "a") == JobStatus.CANCELLED and not service.cancelling
    assert status(store, "b") == JobStatus.DONE
    assert len(launcher.launches) == 2  # b ran in a new child


async def test_cancel_while_the_transcription_ends(started):
    tmp_path, store, service, launcher = started
    launcher.gates["a"] = asyncio.Event()
    service.enqueue([spec(tmp_path, "a", speaker_detection=True)])
    await until(lambda: launcher.dispatched() == ["a"])

    await service.cancel(["a"])  # the kill is requested while the job is in flight...
    launcher.gates["a"].set()  # ...but the transcription was already done
    await settle(service)

    assert status(store, "a") == JobStatus.CANCELLED and not service.cancelling
    assert [phase for phase, _ in launcher.launches] == [1]
    service.retry("a")  # phase 1 reuses the transcription
    await settle(service)
    assert status(store, "a") == JobStatus.DONE
    assert [phase for phase, _ in launcher.launches] == [1, 1, 2]


async def test_pause_during_transcription_does_not_start_phase_2(started):
    tmp_path, store, service, launcher = started
    launcher.gates["a"] = asyncio.Event()
    service.enqueue([spec(tmp_path, "a", speaker_detection=True)])
    await until(lambda: launcher.dispatched() == ["a"])

    service.pause()
    launcher.gates["a"].set()
    await until(lambda: status(store, "a") == JobStatus.QUEUED)  # back, with its transcription
    await asyncio.sleep(0.1)
    assert [phase for phase, _ in launcher.launches] == [1]

    service.resume()
    await settle(service)
    assert status(store, "a") == JobStatus.DONE
    assert [phase for phase, _ in launcher.launches] == [1, 1, 2]


async def test_pause_and_resume(started):
    tmp_path, store, service, launcher = started
    service.pause()
    service.enqueue([spec(tmp_path, "a")])
    await asyncio.sleep(0.1)
    assert launcher.launches == []
    service.resume()
    await settle(service)
    assert status(store, "a") == JobStatus.DONE


async def test_missing_source_fails_and_the_next_job_runs(started):
    tmp_path, store, service, _launcher = started
    service.pause()
    service.enqueue([spec(tmp_path, "a"), spec(tmp_path, "b")])
    (tmp_path / "a.mp3").unlink()
    service.resume()
    await settle(service)

    assert store.get("a")[1].error == "Source file not found"
    assert status(store, "b") == JobStatus.DONE


async def test_failed_job_does_not_stop_the_queue(started):
    tmp_path, store, service, launcher = started
    launcher.outcomes["a"] = "fail"
    service.enqueue([spec(tmp_path, "a"), spec(tmp_path, "b")])
    await settle(service)

    state = store.get("a")[1]
    assert (state.status, state.failed_step, state.error) == (
        JobStatus.FAILED,
        Step.TRANSCRIPTION,
        "model error",
    )
    assert status(store, "b") == JobStatus.DONE


async def test_crash_while_working_fails_only_that_job(started):
    tmp_path, store, service, launcher = started
    launcher.outcomes["a"] = "crash"
    service.enqueue([spec(tmp_path, "a"), spec(tmp_path, "b")])
    await settle(service)

    assert "stopped unexpectedly" in store.get("a")[1].error
    assert status(store, "b") == JobStatus.DONE


async def test_retry_runs_the_job_again_at_the_end(started):
    tmp_path, store, service, launcher = started
    launcher.outcomes["a"] = "fail"
    service.enqueue([spec(tmp_path, "a"), spec(tmp_path, "b")])
    await settle(service)
    launcher.outcomes["a"] = "done"

    service.retry("a")
    assert ids(service) == ["b", "a"]
    await settle(service)

    state = store.get("a")[1]
    assert state.status == JobStatus.DONE and state.error is None


async def test_launch_error_fails_only_that_job(started):
    tmp_path, store, service, launcher = started
    launcher.launch_error_models.add("large-v3-turbo")
    service.pause()
    service.enqueue([spec(tmp_path, "a"), spec(tmp_path, "b", model="small")])
    service.resume()
    await settle(service)

    assert "cannot start the process" in store.get("a")[1].error
    assert status(store, "b") == JobStatus.DONE


async def test_recovery_after_a_restart(env):
    tmp_path, store, service, _launcher = env
    store.add(
        [
            spec(tmp_path, "a"),
            spec(tmp_path, "b", speaker_detection=True),
            spec(tmp_path, "c", speaker_detection=True),
        ]
    )
    for job_id in "abc":
        store.update(job_id, status=JobStatus.RUNNING)
    b_spec = store.get("b")[0]
    outputs.write_checkpoint(
        store.work_dir("b") / RAW_CHECKPOINT,
        transcript={"segments": []},
        audio_duration=5,
        source=b_spec.source,
    )
    for job_id in ("a", "abandoned"):
        (store.uploads_root / job_id).mkdir(parents=True)
    service.pause()

    await service.start()
    try:
        assert [status(store, job_id) for job_id in "abc"] == [JobStatus.QUEUED] * 3
        assert (store.work_dir("b") / RAW_CHECKPOINT).is_file()  # phase 1 reuses it
        # uploads of a page that was closed before they became jobs are deleted
        assert [folder.name for folder in store.uploads_root.iterdir()] == ["a"]
    finally:
        await service.stop()


async def test_stop_puts_the_running_job_back(env):
    tmp_path, store, service, launcher = env
    launcher.outcomes["a"] = "hang"
    await service.start()
    service.enqueue([spec(tmp_path, "a")])
    await until(lambda: status(store, "a") == JobStatus.RUNNING)

    await service.stop()

    assert status(store, "a") == JobStatus.QUEUED
    second = QueueService(store)
    second._lock.acquire()  # the lock was released
    second._lock.release()
