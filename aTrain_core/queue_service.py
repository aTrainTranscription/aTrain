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

from aTrain_core import outputs
from aTrain_core.globals import TIMESTAMP_FORMAT
from aTrain_core.jobs import (
    FINAL_STATUSES,
    JobSpec,
    JobState,
    JobStatus,
    JobStore,
    QueueLock,
    Step,
    resume_status,
)
from aTrain_core.runner import (
    RAW_CHECKPOINT,
    JobDone,
    JobFailed,
    JobFileId,
    JobProgress,
    JobTranscribed,
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
        self._launch = {1: launch_phase1, 2: launch_phase2}
        self._wake = asyncio.Event()
        self._scheduler_task: asyncio.Task | None = None
        self._stopping = False
        # the running phase
        self._handle: PhaseHandle | None = None
        self._in_flight: str | None = None
        self._phase_error: PhaseError | None = None
        self._cancel_requested: set[str] = set()

    # --- lifecycle --------------------------------------------------------------------

    async def start(self) -> None:
        """Take the queue lock (QueueLockedError if another process holds it), put jobs
        that were running when the app stopped back into the queue, start scheduling."""
        self._lock.acquire()
        self.store.reload()  # another aTrain may have changed the queue until now
        for spec, state in self.store.jobs():
            if state.status in (JobStatus.TRANSCRIBING, JobStatus.DIARIZING):
                self._guarded(spec.id, self._resume, spec.id)
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
            self._cancel_requested.add(job_id)
            state.cancelling = True
            handle = self._handle
        # Cancel every waiting entry before yielding to the scheduler, and kill only
        # the child captured above even if the scheduler advances while we await it.
        if handle is not None:
            await asyncio.to_thread(handle.kill)

    def retry(self, job_id: str) -> None:
        _, state = self.store.get(job_id)
        if state.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError("Only failed or cancelled jobs can be retried")
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
        self.store.move(job_id, delta)

    def pause(self) -> None:
        """Start no new phase; the running one finishes."""
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
            while not (self._stopping or self.paused) and (head := self._head()) is not None:
                spec, state = head
                # a transcribed job stays at the head, so its phase 2 runs next
                await self._run_phase(1 if state.status == JobStatus.QUEUED else 2, spec)

    def _head(self) -> tuple[JobSpec, JobState] | None:
        for spec, state in self.store.jobs():
            if state.status in (JobStatus.QUEUED, JobStatus.TRANSCRIBED):
                return spec, state
        return None

    async def _run_phase(self, phase: int, spec: JobSpec) -> None:
        step = Step.TRANSCRIPTION if phase == 1 else Step.DIARIZATION
        self._phase_error = None
        try:
            if not spec.source.exists():
                self._fail(spec.id, step, "Source file not found")
                return
            started_at = self.store.get(spec.id)[1].started_at or _now()
            running = JobStatus.TRANSCRIBING if phase == 1 else JobStatus.DIARIZING
            self.store.update(spec.id, status=running, started_at=started_at)
            self.store.get(spec.id)[1].progress = 0.0  # each phase reports from 0
            self._in_flight = spec.id
            job = PhaseJob(spec, started_at, self.store.work_dir(spec.id))
            self._handle = self._launch[phase](job)
        except Exception as e:
            # e.g. queue.json can't be saved or the process can't start: fail this job
            log.exception("Could not start job %s", spec.id)
            self._in_flight = None
            self._guarded(spec.id, self._fail, spec.id, step, f"Internal error: {e}", format_exc())
            return
        try:
            async for event in self._handle.events():
                self._guarded(getattr(event, "job_id", self._in_flight), self._on_event, event)
        finally:
            self._handle = None
            self._cancel_requested.clear()

    def _on_event(self, event) -> None:
        if isinstance(event, PhaseError):
            self._phase_error = event
        elif isinstance(event, PhaseDied):
            self._phase_died(event.exitcode)
        elif getattr(event, "job_id", None) != self._in_flight:
            log.debug("Dropped event for a job that isn't in flight: %r", event)
        elif isinstance(event, JobProgress):
            self.store.get(event.job_id)[1].progress = event.current / (event.total or 1)
        elif isinstance(event, JobFileId):
            self.store.update(event.job_id, file_id=event.file_id)
        elif isinstance(event, JobTranscribed):
            self._in_flight = None
            # cancelled meanwhile: keep the transcription for a retry, but don't go on
            cancelled = event.job_id in self._cancel_requested
            status = JobStatus.CANCELLED if cancelled else JobStatus.TRANSCRIBED
            self.store.update(event.job_id, status=status, audio_duration=event.audio_duration)
            self._finish(event.job_id)
        elif isinstance(event, JobDone):
            self._in_flight = None
            self.store.update(
                event.job_id,
                status=JobStatus.DONE,
                audio_duration=event.audio_duration,
                warnings=list(event.warnings),
                finished_at=_now(),
            )
            shutil.rmtree(self.store.work_dir(event.job_id), ignore_errors=True)
            shutil.rmtree(self.store.uploads_root / event.job_id, ignore_errors=True)
            self._finish(event.job_id)
        elif isinstance(event, JobFailed):
            self._in_flight = None
            self._drop_incomplete_output(event.job_id)
            self._fail(event.job_id, event.step, event.error, event.traceback)

    def _phase_died(self, exitcode: int | None) -> None:
        reason = (
            self._phase_error.error if self._phase_error else f"process ended with code {exitcode}"
        )
        traceback = self._phase_error.traceback if self._phase_error else None
        job_id, self._in_flight = self._in_flight, None
        if job_id is not None:
            _, state = self.store.get(job_id)
            state.cancelling = False
            step = self._current_step(state)
            self._drop_incomplete_output(job_id)
            if job_id in self._cancel_requested:
                self.store.update(job_id, status=JobStatus.CANCELLED)
                self._finish(job_id)
            elif self._stopping:
                self._resume(job_id)
            else:
                message = f"Processing stopped unexpectedly (possibly out of memory): {reason}"
                self._fail(job_id, step, message, traceback)

    def _current_step(self, state: JobState) -> Step:
        if state.file_id is not None:
            return Step.OUTPUT
        if state.status in (JobStatus.TRANSCRIBED, JobStatus.DIARIZING):
            return Step.DIARIZATION
        return Step.TRANSCRIPTION

    # --- helpers ----------------------------------------------------------------------

    def _resume(self, job_id: str) -> None:
        """Back into the queue after a stop, a restart or a retry, keeping finished work."""
        spec, _ = self.store.get(job_id)
        self._drop_incomplete_output(job_id)
        raw = outputs.read_checkpoint(self.store.work_dir(job_id) / RAW_CHECKPOINT, spec.source)
        self.store.update(job_id, status=resume_status(spec, raw_checkpoint_valid=raw is not None))

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
        self._finish(job_id)

    def _finish(self, job_id: str) -> None:
        self.store.get(job_id)[1].cancelling = False

    def _drop_incomplete_output(self, job_id: str) -> None:
        """A job that has an archive folder but isn't DONE was interrupted while writing its
        outputs: delete the folder, so the archive only holds finished transcriptions."""
        _, state = self.store.get(job_id)
        if state.file_id is not None and state.status != JobStatus.DONE:
            shutil.rmtree(outputs.TRANSCRIPT_DIR / state.file_id, ignore_errors=True)
            self.store.update(job_id, file_id=None)

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
                    step = state.failed_step or self._current_step(state)
                    self._fail(job_id, step, f"Internal error: {e}")
            except Exception:
                log.exception("Could not mark job %s as failed", job_id)


def _now() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)
