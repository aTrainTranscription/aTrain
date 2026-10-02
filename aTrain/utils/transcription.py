import shutil
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast
from uuid import uuid4

from aTrain.components.dialogs.error import dialog_error
from aTrain_core.settings import Device, check_inputs_transcribe
from nicegui import app, events, ui


class State(TypedDict):
    model: str
    language: str
    speaker_detection: bool
    speaker_count: float | None
    GPU: bool
    compute_type: str
    temperature_override: float | None
    initial_prompt: str | None
    cpu_threads: int


@dataclass(slots=True)
class UploadPayload:
    """Platform-neutral description of the file to transcribe.

    Two callers feed the same pipeline: the browser upload on Windows/macOS
    (a NiceGUI `UploadEventArguments`) and the native file picker on
    Linux/Flatpak (a path on disk). Normalising both into this type keeps
    NiceGUI's event class out of the transcription code, so an upload-API
    change like 2.x `.name`/`.content` -> 3.x `.file` can only ever break the
    one adapter below instead of silently breaking one of the two platforms.
    """

    name: str
    upload: ui.upload.FileUpload | None = None
    path: Path | None = None

    async def materialise(self, directory: Path, filename: str) -> Path:
        """Return a path the engine can read, staging the upload if needed."""
        if self.path is not None:
            return self.path  # already on disk - no copy, the picker gave us a real file
        if self.upload is None:
            raise ValueError(f"No file to transcribe: {self.name!r} has neither upload nor path")
        target = directory / filename
        await self.upload.save(target)
        return target


async def start_uploads(event: events.MultiUploadEventArguments):
    """NiceGUI `on_multi_upload` handler (browser upload)."""
    payloads = [UploadPayload(name=file.name, upload=file) for file in event.files]
    await start_payloads(payloads)


async def start_paths(paths: list[Path], export_dir: Path | None = None):
    """Entry point for picked files or a folder on disk."""
    await start_payloads([UploadPayload(name=path.name, path=path) for path in paths], export_dir)


async def start_payloads(payloads: list[UploadPayload], export_dir: Path | None = None):
    """Add the files to the queue; the queue below the settings shows their progress."""
    from dataclasses import replace

    from aTrain.utils.queue_ui import LOCKED_TEXT, build_spec_from_state, get_queue_service
    from aTrain_core.jobs import QueueLockedError
    from werkzeug.utils import secure_filename

    if not payloads:
        return
    # Snapshot rather than read live: the page re-renders while an upload is staged,
    # and `get_model_options` resets `model` to None whenever no model is on disk yet.
    state = cast(State, dict(app.storage.general))
    staged: list[Path] = []
    enqueued = False
    try:
        device = Device.GPU if state.get("GPU") else Device.CPU
        # Validate first: it needs nothing but the name and the settings, and rejecting a
        # wrong model or language should not cost a full copy of the upload beforehand.
        check_inputs_transcribe(payloads[0].name, state.get("model"), state.get("language"), device)
        service = await get_queue_service()
        specs = []
        for payload in payloads:
            job_id = uuid4().hex
            staging = service.store.uploads_root / job_id
            if payload.path is None:
                staging.mkdir(parents=True)
                staged.append(staging)
            source = await payload.materialise(staging, secure_filename(payload.name) or "upload")
            spec = build_spec_from_state(
                state, job_id=job_id, source=source, display_name=payload.name
            )
            specs.append(replace(spec, export_dir=export_dir))
        service.enqueue(specs)
        enqueued = True
    except QueueLockedError:
        ui.notify(LOCKED_TEXT, color="negative", multi_line=True)
        return
    except Exception as e:
        dialog_error(error=str(e), traceback=traceback.format_exc())
        return
    finally:
        if not enqueued:
            for staging in staged:
                shutil.rmtree(staging, ignore_errors=True)
    added = payloads[0].name if len(specs) == 1 else f"{len(specs)} files"
    ui.notify(f"{added} added to the queue")
