"""The queue service: decides which job runs, starts and kills the phase children, and is
the only writer of the job store. Runs on one asyncio loop; no NiceGUI.

Jobs run one at a time in queue order: a phase-1 child for the transcription, then a
phase-2 child for speaker detection. Commands change state without awaiting in between,
so they can't interleave with starting a job. The only await in a command is the kill in
cancel().
"""

import asyncio
import logging
import shutil
from collections.abc import Callable
from datetime import datetime
from traceback import format_exc

from aTrain_core.globals import TIMESTAMP_FORMAT
from aTrain_core.jobs import (
    FINAL_STATUSES,
    JobSpec,
    JobState,
    JobStatus,
    JobStore,
    QueueLock,
    Step,
)
from aTrain_core.runner import (
    JobDone,
    JobFailed,
    JobProgress,
    PhaseDied,
    PhaseError,
    PhaseHandle,
    PhaseJob,
    launch_phase1,
    launch_phase2,
)

log = logging.getLogger(__name__)


class QueueService:
    def __init__(
        self,
        store: JobStore,
        *,
        launch_phase1: Callable[..., PhaseHandle] = launch_phase1,
        launch_phase2: Callable[..., PhaseHandle] = launch_phase2,
    ):
        self.store = store
        self.paused = False
        self._lock = QueueLock(store.root)
        self._launch = {Step.TRANSCRIPTION: launch_phase1, Step.DIARIZATION: launch_phase2}
        self._wake = asyncio.Event()
        self._scheduler_task: asyncio.Task | None = None
        self._stopping = False
        # the running phase
        self.step = Step.TRANSCRIPTION  # what the running child does
        self.progress = 0.0  # of the running child, 0 to 1
        self.cancelling = False  # the running job is being cancelled
        self._handle: PhaseHandle | None = None
        self._in_flight: str | None = None
        self._phase_error: PhaseError | None = None

    # --- lifecycle --------------------------------------------------------------------

    async def start(self) -> None:
        """Take the queue lock (QueueLockedError if another process holds it), put jobs
        that were running when the app stopped back into the queue, start scheduling."""
        self._lock.acquire()
        self.store.reload()  # another aTrain may have changed the queue until now
        for spec, state in self.store.jobs():
            if state.status == JobStatus.RUNNING:
                self._guarded(spec.id, self._resume, spec.id)
        # files uploaded on a page that was closed before they were added to the queue
        job_ids = {spec.id for spec, _ in self.store.jobs()}
        for folder in self.store.uploads_root.glob("*"):
            if folder.name not in job_ids:
                shutil.rmtree(folder, ignore_errors=True)
        self._scheduler_task = asyncio.create_task(self._scheduler())
        self._wake.set()

    async def stop(self) -> None:
        """Kill the running child; its job goes back into the queue. Release the lock."""
        self._stopping = True
        self._wake.set()
        try:
            if self._handle is not None:
                await asyncio.to_thread(self._handle.kill)
            if self._scheduler_task is not None:
                await self._scheduler_task
        finally:
            self._lock.release()

    # --- commands ---------------------------------------------------------------------

    def enqueue(self, specs: list[JobSpec]) -> None:
        self.store.add(specs)
        self._wake.set()

    async def cancel(self, job_ids: list[str]) -> None:
        handle = None
        for job_id in job_ids:
            try:
                _, state = self.store.get(job_id)
            except KeyError:  # removed while a confirmation dialog was open
                continue
            if state.status in FINAL_STATUSES:
                continue
            if job_id != self._in_flight:
                self._guarded(job_id, self.store.update, job_id, status=JobStatus.CANCELLED)
                continue
            # The child is killed; events it sent before are still applied, so a job
            # that has just finished stays DONE (a just transcribed one is CANCELLED).
            self.cancelling = True
            handle = self._handle
        # Cancel every waiting entry before yielding to the scheduler, and kill only
        # the child captured above even if the scheduler advances while we await it.
        if handle is not None:
            await asyncio.to_thread(handle.kill)

    def retry(self, job_id: str) -> None:
        """Back into the queue, at its end."""
        _, state = self.store.get(job_id)
        if state.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError("Only failed or cancelled jobs can be retried")
        self.store.move(job_id, len(self.store.jobs()))
        self.store.update(
            job_id, error=None, traceback=None, failed_step=None, warnings=[], started_at=None
        )
        self._resume(job_id)
        self._wake.set()

    def remove(self, job_id: str) -> None:
        if job_id == self._in_flight:
            raise ValueError("The job is running; cancel it first")
        self.store.remove(job_id)

    def clear_finished(self) -> None:
        self.store.clear_finished()

    def move(self, job_id: str, delta: int) -> None:
        """Swap a queued job with its queued neighbour (delta -1 up, +1 down). Running and
        finished jobs keep their places; a no-op for other jobs and at the ends."""
        jobs = self.store.jobs()
        queued = [i for i, (_, state) in enumerate(jobs) if state.status == JobStatus.QUEUED]
        index = next((i for i, (spec, _) in enumerate(jobs) if spec.id == job_id), None)
        if index not in queued:
            return
        target = queued.index(index) + delta
        if 0 <= target < len(queued):
            self.store.move(job_id, queued[target] - index)

    def pause(self) -> None:
        """Start no new phase; the running one finishes. A job between its two phases goes
        back into the queue and keeps its transcription."""
        self.paused = True

    def resume(self) -> None:
        self.paused = False
        self._wake.set()

    # --- read side --------------------------------------------------------------------

    def jobs(self) -> list[tuple[JobSpec, JobState]]:
        return self.store.jobs()

    # --- scheduling -------------------------------------------------------------------

    async def _scheduler(self) -> None:
        while not self._stopping:
            await self._wake.wait()
            self._wake.clear()
            while not (self._stopping or self.paused) and (spec := self._head()) is not None:
                await self._run_job(spec)

    def _head(self) -> JobSpec | None:
        for spec, state in self.store.jobs():
            if state.status == JobStatus.QUEUED:
                return spec
        return None

    async def _run_job(self, spec: JobSpec) -> None:
        """The transcription, then the speaker detection. The children reuse what the job's
        checkpoints hold, so a job that comes back into the queue redoes only what is missing."""
        try:
            if not (await self._run_phase(Step.TRANSCRIPTION, spec) and spec.speaker_detection):
                return
            if self.cancelling:  # transcribed just before the kill
                self._guarded(spec.id, self.store.update, spec.id, status=JobStatus.CANCELLED)
            elif self.paused or self._stopping:
                self._guarded(spec.id, self.store.update, spec.id, status=JobStatus.QUEUED)
            else:
                await self._run_phase(Step.DIARIZATION, spec)
        finally:
            self.cancelling = False

    async def _run_phase(self, step: Step, spec: JobSpec) -> bool:
        """Run one child for the job. True if it ended without a result or a crash: it did
        its step, and the job continues with the next one."""
        self._phase_error = None
        try:
            if not spec.source.exists():
                self._fail(spec.id, step, "Source file not found")
                return False
            started_at = self.store.get(spec.id)[1].started_at or _now()
            self.store.update(spec.id, status=JobStatus.RUNNING, started_at=started_at)
            self.progress = 0.0  # each phase reports from 0
            self.step = step
            self._in_flight = spec.id
            job = PhaseJob(spec, started_at, self.store.work_dir(spec.id))
            self._handle = self._launch[step](job)
        except Exception as e:
            # e.g. queue.json can't be saved or the process can't start: fail this job
            log.exception("Could not start job %s", spec.id)
            self._in_flight = None
            self._guarded(spec.id, self._fail, spec.id, step, f"Internal error: {e}", format_exc())
            return False
        try:
            async for event in self._handle.events():
                self._guarded(getattr(event, "job_id", self._in_flight), self._on_event, event)
            # a result, a failure or a crash would have taken the job out of flight
            return self._in_flight == spec.id
        finally:
            self._handle = None
            self._in_flight = None

    def _on_event(self, event) -> None:
        if isinstance(event, PhaseError):
            self._phase_error = event
        elif isinstance(event, PhaseDied):
            self._phase_died(event.exitcode)
        elif getattr(event, "job_id", None) != self._in_flight:
            log.debug("Dropped event for a job that isn't in flight: %r", event)
        elif isinstance(event, JobProgress):
            self.progress = event.current / (event.total or 1)
        elif isinstance(event, JobDone):
            self._in_flight = None
            self.store.update(
                event.job_id,
                status=JobStatus.DONE,
                file_id=event.file_id,
                audio_duration=event.audio_duration,
                warnings=list(event.warnings),
                finished_at=_now(),
            )
            shutil.rmtree(self.store.work_dir(event.job_id), ignore_errors=True)
            shutil.rmtree(self.store.uploads_root / event.job_id, ignore_errors=True)
        elif isinstance(event, JobFailed):
            self._in_flight = None
            self._fail(event.job_id, event.step, event.error, event.traceback)

    def _phase_died(self, exitcode: int | None) -> None:
        reason = (
            self._phase_error.error if self._phase_error else f"process ended with code {exitcode}"
        )
        traceback = self._phase_error.traceback if self._phase_error else None
        job_id, self._in_flight = self._in_flight, None
        if job_id is not None:
            if self.cancelling:
                self.store.update(job_id, status=JobStatus.CANCELLED)
            elif self._stopping:
                self._resume(job_id)
            else:
                message = f"Processing stopped unexpectedly (possibly out of memory): {reason}"
                self._fail(job_id, self.step, message, traceback)

    # --- helpers ----------------------------------------------------------------------

    def _resume(self, job_id: str) -> None:
        """Back into the queue after a stop, a restart or a retry. The checkpoints stay, so
        finished work is reused."""
        self.store.update(job_id, status=JobStatus.QUEUED)

    def _fail(self, job_id: str, step: Step, error: str, traceback: str | None = None) -> None:
        try:
            self.store.update(
                job_id, status=JobStatus.FAILED, failed_step=step, error=error, traceback=traceback
            )
        except OSError as e:
            # Even the failure cannot be saved. Show it for this session and stop
            # scheduling; the last durable state and checkpoints allow restart recovery.
            self.paused = True
            _, state = self.store.get(job_id)
            state.status = JobStatus.FAILED
            state.failed_step = step
            state.error = (
                f"{error}\nQueue paused because its state could not be saved: {e}. "
                "Free disk space or restore write access, then retry and resume the queue."
            )
            state.traceback = traceback
            log.exception("Could not save failure for job %s; queue paused", job_id)

    def _guarded(self, job_id: str | None, action: Callable, *args, **kwargs) -> None:
        """Run a state change; an unexpected error fails only that job, never the scheduler."""
        try:
            action(*args, **kwargs)
        except Exception as e:
            log.exception("Queue error for job %s", job_id)
            if job_id is None:
                return
            if job_id == self._in_flight:
                self._in_flight = None
            try:
                _, state = self.store.get(job_id)
                if state.status not in FINAL_STATUSES:
                    step = state.failed_step or self.step
                    self._fail(job_id, step, f"Internal error: {e}")
            except Exception:
                log.exception("Could not mark job %s as failed", job_id)


def _now() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)
