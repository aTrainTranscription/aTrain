"""Transcription jobs: what to do (JobSpec), where a job is (JobState), and the queue file.

Imports only the standard library, filelock and aTrain_core, so the runner's child
processes and the CLI can use it without NiceGUI or torch.
"""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from enum import StrEnum, auto
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

from aTrain_core.settings import ComputeType, Device, ModelKey, Settings

SCHEMA_VERSION = 1
QUEUE_FILENAME = "queue.json"
LOCK_FILENAME = ".lock"


@dataclass(frozen=True, slots=True)
class JobSpec:
    """What to do. Fixed once the job is created; all settings are captured when it is added."""

    id: str  # uuid4 hex
    source: Path  # absolute; for browser uploads the staged copy in queue/uploads/<id>/
    display_name: str  # original file name
    model: str
    language: str
    device: Device
    compute_type: ComputeType
    cpu_threads: int
    temperature: float | None
    initial_prompt: str | None
    speaker_detection: bool
    speaker_count: int | None
    export_dir: Path | None = None  # optional copy next to the source files

    @property
    def model_key(self) -> ModelKey:
        return ModelKey(self.model, self.device, self.compute_type, self.cpu_threads)

    def to_settings(self, *, file_id: str, timestamp: str, progress) -> Settings:
        return Settings(
            file=self.source,
            file_id=file_id,
            file_name=self.display_name,
            model=self.model,
            language=self.language,
            speaker_detection=self.speaker_detection,
            speaker_count=self.speaker_count,
            device=self.device,
            compute_type=self.compute_type,
            timestamp=timestamp,
            temperature=self.temperature,
            initial_prompt=self.initial_prompt,
            progress=progress,
            cpu_threads=self.cpu_threads,
        )

    def to_json(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["source"] = str(self.source)
        data["export_dir"] = str(self.export_dir) if self.export_dir else None
        data["device"] = self.device.value
        data["compute_type"] = self.compute_type.value
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "JobSpec":
        return cls(  # unknown keys raise TypeError
            **{
                **data,
                "source": Path(data["source"]),
                "export_dir": Path(data["export_dir"]) if data.get("export_dir") else None,
                "device": Device(data["device"]),
                "compute_type": ComputeType(data["compute_type"]),
            }
        )


class JobStatus(StrEnum):
    QUEUED = auto()  # waiting; its checkpoints are reused when it runs
    RUNNING = auto()  # its transcription or speaker detection child is running
    DONE = auto()  # archive folder complete
    FAILED = auto()
    CANCELLED = auto()


class Step(StrEnum):
    TRANSCRIPTION = auto()
    DIARIZATION = auto()
    OUTPUT = auto()


FINAL_STATUSES = {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass(slots=True)
class JobState:
    """Where the job is. Owned by the queue service."""

    status: JobStatus = JobStatus.QUEUED
    file_id: str | None = None  # archive folder, once DONE
    started_at: str | None = None  # metadata timestamp of the current run
    finished_at: str | None = None
    audio_duration: int | None = None
    failed_step: Step | None = None  # for display only
    error: str | None = None
    traceback: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)}
        data["warnings"] = list(self.warnings)
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "JobState":
        failed_step = data.get("failed_step")
        return cls(  # unknown keys raise TypeError
            **{
                **data,
                "status": JobStatus(data["status"]),
                "failed_step": Step(failed_step) if failed_step else None,
            }
        )


class JobStore:
    """The queue on disk: one queue.json under `root`, rewritten atomically on every change.
    List order is queue order."""

    def __init__(self, root: Path):
        self.root = root
        self.path = root / QUEUE_FILENAME
        self.work_root = root / "work"
        self.uploads_root = root / "uploads"
        self._jobs: list[tuple[JobSpec, JobState]] = self._load()

    def reload(self) -> None:
        """Read queue.json again, e.g. after taking the queue lock."""
        self._jobs = self._load()

    def add(self, specs: list[JobSpec]) -> None:
        known = {spec.id for spec, _ in self._jobs}
        for spec in specs:
            if spec.id in known:
                raise ValueError(f"Job {spec.id} is already in the queue")
            known.add(spec.id)
        jobs = self._jobs + [(spec, JobState()) for spec in specs]
        self._save(jobs)
        self._jobs = jobs

    def get(self, job_id: str) -> tuple[JobSpec, JobState]:
        return self._jobs[self._index(job_id)]

    def jobs(self) -> list[tuple[JobSpec, JobState]]:
        return list(self._jobs)

    def update(self, job_id: str, **changes) -> JobState:
        """Change saved state fields."""
        index = self._index(job_id)
        spec, state = self._jobs[index]
        jobs = self._jobs.copy()
        jobs[index] = (spec, replace(state, **changes))
        self._save(jobs)
        # Keep existing readers' state references live, but only after the write succeeds.
        for name, value in changes.items():
            setattr(state, name, value)
        return state

    def move(self, job_id: str, delta: int) -> None:
        index = self._index(job_id)
        target = max(0, min(len(self._jobs) - 1, index + delta))
        jobs = self._jobs.copy()
        jobs.insert(target, jobs.pop(index))
        self._save(jobs)
        self._jobs = jobs

    def remove(self, job_id: str) -> None:
        """Remove the entry and delete its work folder and staged upload.
        A source outside queue/uploads/ is never touched."""
        jobs = self._jobs.copy()
        del jobs[self._index(job_id)]
        self._save(jobs)
        self._jobs = jobs
        self._delete_files(job_id)

    def clear_finished(self) -> None:
        finished = [spec.id for spec, state in self._jobs if state.status in FINAL_STATUSES]
        jobs = [job for job in self._jobs if job[1].status not in FINAL_STATUSES]
        self._save(jobs)
        self._jobs = jobs
        for job_id in finished:
            self._delete_files(job_id)

    def _delete_files(self, job_id: str) -> None:
        shutil.rmtree(self.work_dir(job_id), ignore_errors=True)
        shutil.rmtree(self.uploads_root / job_id, ignore_errors=True)

    def work_dir(self, job_id: str) -> Path:
        return self.work_root / job_id

    def _index(self, job_id: str) -> int:
        for index, (spec, _) in enumerate(self._jobs):
            if spec.id == job_id:
                return index
        raise KeyError(job_id)

    def _load(self) -> list[tuple[JobSpec, JobState]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("schema_version") != SCHEMA_VERSION:
                raise ValueError(f"unsupported schema_version {data.get('schema_version')!r}")
            return [
                (JobSpec.from_json(job["spec"]), JobState.from_json(job["state"]))
                for job in data["jobs"]
            ]
        except Exception as e:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            unreadable = self.path.with_name(f"{QUEUE_FILENAME}.unreadable-{stamp}")
            os.replace(self.path, unreadable)
            logging.warning("Could not read %s (%s); moved it to %s", self.path, e, unreadable)
            return []

    def _save(self, jobs: list[tuple[JobSpec, JobState]]) -> None:
        """Persist a proposed change before exposing it to readers or deleting files."""
        self.root.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": SCHEMA_VERSION,
            "jobs": [{"spec": spec.to_json(), "state": state.to_json()} for spec, state in jobs],
        }
        tmp = self.path.with_name(QUEUE_FILENAME + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)


class QueueLockedError(Exception):
    pass


class QueueLock:
    """OS-level lock on queue/.lock, held by the process that runs the queue.
    The OS releases it when that process dies."""

    def __init__(self, root: Path):
        self.root = root
        self._lock = FileLock(root / LOCK_FILENAME)

    def acquire(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self._lock.acquire(blocking=False)
        except Timeout as e:
            raise QueueLockedError("aTrain is already running in another window.") from e
        except OSError as e:  # e.g. a file system without locking: never run unlocked
            raise QueueLockedError(f"Could not lock the queue: {e}") from e

    def release(self) -> None:
        self._lock.release()
