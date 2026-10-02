"""The app's queue service: one per server process, started on first use."""

import asyncio
from pathlib import Path

from aTrain_core.globals import ATRAIN_DIR
from aTrain_core.jobs import JobSpec, JobStore, QueueLockedError
from aTrain_core.queue_service import QueueService
from aTrain_core.settings import ComputeType, Device
from nicegui import app

LOCKED_TEXT = (
    "aTrain is already transcribing in another window or on the command line. "
    "Close it to transcribe here."
)

QUEUE_ROOT = ATRAIN_DIR / "queue"

_service: QueueService | None = None
_loop: asyncio.AbstractEventLoop | None = None


async def get_queue_service() -> QueueService:
    """The running queue service. Raises QueueLockedError if another aTrain process
    holds the queue lock."""
    global _service, _loop
    # No await before _service is set (start() doesn't wait for anything), so two
    # callers can't both create a service.
    loop = asyncio.get_running_loop()
    if _service is not None and _loop is not loop:
        # a new event loop (only in tests): the old service can't run any more
        _service._lock.release()
        _service = None
    if _service is None:
        service = QueueService(JobStore(QUEUE_ROOT))
        await service.start()
        _service, _loop = service, loop
        app.on_shutdown(_stop)
    return _service


async def start_queue_service() -> None:
    """App startup: start the queue, so jobs of an earlier session continue. If another
    aTrain process holds the lock, the pages show a banner instead."""
    try:
        await get_queue_service()
    except QueueLockedError:
        pass


async def _stop() -> None:
    global _service
    if _service is not None:
        service, _service = _service, None
        await service.stop()


def build_spec_from_state(state: dict, *, job_id: str, source: Path, display_name: str) -> JobSpec:
    """A job with the settings of the transcribe page (a snapshot of app.storage.general)."""
    device = Device.GPU if state.get("GPU") else Device.CPU
    return JobSpec(
        id=job_id,
        source=source.absolute(),
        display_name=display_name,
        model=state["model"],
        language=state["language"],
        device=device,
        compute_type=ComputeType(state["compute_type"]),
        cpu_threads=int(state.get("cpu_threads", 0)) or 0,
        temperature=state.get("temperature_override"),
        initial_prompt=state.get("initial_prompt") or None,
        speaker_detection=bool(state.get("speaker_detection")),
        speaker_count=int(state.get("speaker_count") or 0) or None,
    )
