"""Child processes that run the two phases of one job.

Phase 1 loads Whisper and transcribes; phase 2 loads pyannote and detects speakers. Each
child gets one job, sends events to the parent and exits, which frees its model. Children
are spawned, and exit when the parent dies.
"""

import asyncio
import importlib
import multiprocessing
import os
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, MutableMapping
from contextlib import suppress
from dataclasses import dataclass, field
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from traceback import format_exc
from typing import Any, NoReturn, Protocol

from werkzeug.utils import secure_filename

from aTrain_core.engine import backend_of, decode, diarize
from aTrain_core.jobs import JobSpec, Step
from aTrain_core.outputs import (
    free_file_id,
    fresh_output_dir,
    make_logger,
    publish,
    read_checkpoint,
    write_checkpoint,
    write_final_outputs,
)

RAW_CHECKPOINT = "raw_transcript.json"
DIARIZED_CHECKPOINT = "diarized_transcript.json"
WORK_LOG = "log.txt"
POLL_INTERVAL = 0.05


@dataclass(frozen=True, slots=True)
class PhaseJob:
    """What a child needs for one job."""

    spec: JobSpec
    timestamp: str  # JobState.started_at, used as the metadata timestamp
    work_dir: Path


# child -> parent
@dataclass(frozen=True, slots=True)
class JobProgress:
    job_id: str
    task: str
    current: float
    total: float


@dataclass(frozen=True, slots=True)
class JobDone:
    job_id: str
    file_id: str  # the archive folder
    audio_duration: int
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class JobFailed:
    job_id: str
    step: Step
    error: str
    traceback: str


@dataclass(frozen=True, slots=True)
class PhaseFinished:
    pass


@dataclass(frozen=True, slots=True)
class PhaseError:
    error: str
    traceback: str


# made up by the parent when a child ended without PhaseFinished
@dataclass(frozen=True, slots=True)
class PhaseDied:
    exitcode: int | None


class Channel(Protocol):
    """The child's side of the connection to the parent."""

    def send(self, event: Any) -> None: ...


class EventProgress(MutableMapping):
    """A progress dict that the existing progress code writes to, sent to the parent as
    JobProgress events, at most every `interval` seconds. flush() sends the last value."""

    def __init__(self, channel: Channel, job_id: str, interval: float = 0.2, clock=time.monotonic):
        self._data: dict[str, Any] = {"task": "", "current": 0, "total": 1}
        self._channel, self._job_id = channel, job_id
        self._interval, self._clock = interval, clock
        self._last_sent = float("-inf")
        self._pending = False

    def __setitem__(self, key: str, value: Any) -> None:
        task_changed = key == "task" and value != self._data.get("task")
        self._data[key] = value
        self._pending = True
        if task_changed or self._clock() - self._last_sent >= self._interval:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        data = self._data
        self._channel.send(JobProgress(self._job_id, data["task"], data["current"], data["total"]))
        self._last_sent, self._pending = self._clock(), False

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __delitem__(self, key: str) -> None:
        del self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


class CheckpointMissingError(Exception):
    pass


class SourceChangedError(Exception):
    pass


def _decode_unchanged(source: Path, source_stat: os.stat_result, log):
    """Decode the source; fail if it changed since `source_stat` was taken, because the
    checkpoints made from this audio are tied to `source_stat`."""
    audio, duration = decode(source, log)
    now = os.stat(source)
    if (now.st_size, now.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
        raise SourceChangedError(
            "The recording changed while it was read. Retry to transcribe it again."
        )
    return audio, duration


def run_phase1(job: PhaseJob, channel: Channel, load_transcriber: Callable) -> None:
    """Load Whisper and transcribe the job. A job without speaker detection also gets its
    outputs written here. A saved transcription is reused without loading Whisper."""
    # no cleanup afterwards: the child ends with os._exit, which frees everything
    _run_phase1_job(lambda: load_transcriber(job.spec.model_key), job, channel)


def _run_phase1_job(load: Callable, job: PhaseJob, channel: Channel) -> None:
    step = Step.TRANSCRIPTION
    log = make_logger(job.work_dir / WORK_LOG)
    try:
        job.work_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = read_checkpoint(job.work_dir / RAW_CHECKPOINT, job.spec.source)
        if checkpoint is None:
            transcriber = load()
            source_stat = os.stat(job.spec.source)
            audio, duration = _decode_unchanged(job.spec.source, source_stat, log)
            progress = EventProgress(channel, job.spec.id)
            transcript = transcriber.transcribe(
                audio,
                language=job.spec.language,
                initial_prompt=job.spec.initial_prompt,
                temperature=job.spec.temperature,
                progress=progress,
                log=log,
            )
            progress.flush()
            del audio
            write_checkpoint(
                job.work_dir / RAW_CHECKPOINT,
                transcript=transcript,
                audio_duration=duration,
                source=job.spec.source,
                source_stat=source_stat,
            )
            log("Transcription successful")
        else:
            transcript, duration = checkpoint.transcript, checkpoint.audio_duration
            log("Reusing the saved transcription")
        if job.spec.speaker_detection:
            return  # phase 2 detects the speakers and writes the outputs
        step = Step.OUTPUT
        _write_outputs(channel, job, transcript, duration, backend_of(job.spec.model))
    except Exception as e:
        _fail(channel, job, step, e, log)


def run_phase2(job: PhaseJob, channel: Channel, load_diarizer: Callable) -> None:
    """Load pyannote, detect the job's speakers and write its outputs. A saved speaker
    detection is reused without loading pyannote."""
    # no cleanup afterwards: the child ends with os._exit, which frees everything
    _run_phase2_job(lambda: load_diarizer(job.spec.device), job, channel)


def _run_phase2_job(load: Callable, job: PhaseJob, channel: Channel) -> None:
    step = Step.DIARIZATION
    log = make_logger(job.work_dir / WORK_LOG)
    try:
        job.work_dir.mkdir(parents=True, exist_ok=True)
        source_stat = os.stat(job.spec.source)
        raw = read_checkpoint(job.work_dir / RAW_CHECKPOINT, job.spec.source, source_stat)
        if raw is None:
            raise CheckpointMissingError(
                "The saved transcription is missing, or the recording changed after it "
                "was transcribed. Retry to transcribe it again."
            )
        checkpoint = read_checkpoint(
            job.work_dir / DIARIZED_CHECKPOINT, job.spec.source, source_stat
        )
        if checkpoint is None:
            pipeline = load()
            audio, _ = _decode_unchanged(job.spec.source, source_stat, log)
            progress = EventProgress(channel, job.spec.id)
            transcript = diarize(
                pipeline,
                audio,
                raw.transcript,
                speaker_count=job.spec.speaker_count,
                progress=progress,
                log=log,
            )
            progress.flush()
            del audio
            write_checkpoint(
                job.work_dir / DIARIZED_CHECKPOINT,
                transcript=transcript,
                audio_duration=raw.audio_duration,
                source=job.spec.source,
                source_stat=source_stat,
            )
        else:
            transcript = checkpoint.transcript
            log("Reusing the saved speaker detection")
        step = Step.OUTPUT
        _write_outputs(channel, job, transcript, raw.audio_duration, backend_of(job.spec.model))
    except Exception as e:
        _fail(channel, job, step, e, log)


def _write_outputs(channel: Channel, job: PhaseJob, transcript: dict, duration: int, backend: str):
    file_id = free_file_id(Path(secure_filename(job.spec.display_name)), job.timestamp)
    directory = fresh_output_dir(file_id)
    warnings = write_final_outputs(
        job.spec.to_settings(file_id=file_id, timestamp=job.timestamp, progress={}),
        transcript,
        audio_duration=duration,
        backend=backend,
        work_log=job.work_dir / WORK_LOG,
        export_dir=job.spec.export_dir,
        directory=directory,
    )
    publish(directory)
    channel.send(JobDone(job.spec.id, file_id, duration, warnings))


def _fail(channel: Channel, job: PhaseJob, step: Step, error: Exception, log) -> None:
    with suppress(OSError):
        log(f"{step} failed: {error}")
    channel.send(JobFailed(job.spec.id, step, str(error), format_exc()))


# --- child entry points -------------------------------------------------------------


def phase1_main(
    job: PhaseJob, conn: Connection, factory: str = "aTrain_core.engine:load_transcriber"
) -> NoReturn:
    _child_main(conn, lambda channel: run_phase1(job, channel, _load_factory(factory)))


def phase2_main(
    job: PhaseJob, conn: Connection, factory: str = "aTrain_core.engine:load_diarizer"
) -> NoReturn:
    _child_main(conn, lambda channel: run_phase2(job, channel, _load_factory(factory)))


def _load_factory(path: str) -> Callable:
    """Resolve "module:name". Tests pass fakes this way, because a spawned child can't
    see monkeypatches."""
    module, name = path.split(":")
    return getattr(importlib.import_module(module), name)


def _child_main(conn: Connection, work: Callable[[Channel], None]) -> NoReturn:
    _start_parent_watchdog()
    code = 0
    try:
        work(conn)
        conn.send(PhaseFinished())
    except BaseException as e:
        code = 1
        with suppress(Exception):
            conn.send(PhaseError(str(e), format_exc()))
    with suppress(Exception):
        conn.close()
    # Skip interpreter shutdown: faster-whisper can hang there
    # (https://github.com/guillaumekln/faster-whisper/issues/71).
    os._exit(code)


def _start_parent_watchdog() -> None:
    """Exit when the parent is gone (crash, force-quit), so no child keeps the GPU."""
    parent = multiprocessing.parent_process()
    if parent is None:
        return

    def watch() -> None:
        parent.join()
        os._exit(3)

    threading.Thread(target=watch, name="parent-watchdog", daemon=True).start()


# --- parent side ----------------------------------------------------------------------


class PhaseHandle:
    """The parent's side of one phase child."""

    def __init__(self, process: BaseProcess, conn: Connection):
        self.process = process
        self.conn = conn

    async def events(self) -> AsyncIterator[Any]:
        """Yield the child's events in order. After the child has ended, yields PhaseDied
        unless it sent PhaseFinished."""
        finished = False
        while True:
            alive = self.process.is_alive()
            for event in self._drain():
                finished = finished or isinstance(event, PhaseFinished)
                yield event
            if not alive:
                break
            await asyncio.sleep(POLL_INTERVAL)
        await asyncio.to_thread(self.process.join)
        if not finished:
            yield PhaseDied(self.process.exitcode)

    def _drain(self) -> Iterator[Any]:
        try:
            while self.conn.poll():
                yield self.conn.recv()
        except (EOFError, OSError):
            return

    def kill(self) -> None:
        self.process.kill()
        self.process.join(5)


def launch_phase1(job: PhaseJob, factory: str | None = None) -> PhaseHandle:
    return _launch(phase1_main, job, factory, "aTrain phase 1")


def launch_phase2(job: PhaseJob, factory: str | None = None) -> PhaseHandle:
    return _launch(phase2_main, job, factory, "aTrain phase 2")


def _launch(target, job: PhaseJob, factory: str | None, name: str) -> PhaseHandle:
    # spawn on every platform: no inherited CUDA state and nothing copied from the GUI
    context = multiprocessing.get_context("spawn")
    parent_conn, child_conn = context.Pipe(duplex=False)
    args = (job, child_conn) if factory is None else (job, child_conn, factory)
    process = context.Process(target=target, args=args, name=name, daemon=False)
    process.start()
    child_conn.close()  # so the parent sees EOF when the child ends
    return PhaseHandle(process, parent_conn)
