import shutil
import traceback
from pathlib import Path
from uuid import uuid4

from aTrain.components.dialogs.error import dialog_error
from aTrain_core.settings import Device, validate_job_settings
from nicegui import app, ui


async def stage_upload(file: ui.upload.FileUpload) -> Path:
    """Save a browser file in the queue's upload folder, in a folder named by the id of its
    future job, so it is a path like any picked file."""
    from aTrain.utils.queue_ui import get_queue_service

    service = await get_queue_service()
    name = Path(file.name).name
    path = service.store.uploads_root / uuid4().hex / (name if name not in ("", "..") else "upload")
    path.parent.mkdir(parents=True)
    try:
        await file.save(path)
    except BaseException:
        shutil.rmtree(path.parent, ignore_errors=True)
        raise
    return path


async def start_paths(paths: list[Path], export_dir: Path | None = None) -> bool:
    """Add one job per file; the queue below the settings shows their progress. Returns
    whether they were added."""
    from aTrain.utils.queue_ui import LOCKED_TEXT, build_spec_from_state, get_queue_service
    from aTrain_core.jobs import QueueLockedError

    # Snapshot rather than read live: `get_model_options` resets `model` to None whenever
    # no model is on disk yet.
    state = dict(app.storage.general)
    try:
        device = Device.GPU if state.get("GPU") else Device.CPU
        validate_job_settings(state.get("model"), state.get("language"), device)
        service = await get_queue_service()
        uploads_root = service.store.uploads_root
        specs = [
            build_spec_from_state(
                state,
                # a staged upload's folder is named by its job id
                job_id=path.parent.name if path.parent.parent == uploads_root else uuid4().hex,
                source=path,
                display_name=path.name,
                export_dir=export_dir,
            )
            for path in paths
        ]
        service.enqueue(specs)
    except QueueLockedError:
        ui.notify(LOCKED_TEXT, color="negative", multi_line=True)
        return False
    except Exception as e:
        dialog_error(error=str(e), traceback=traceback.format_exc())
        return False
    added = paths[0].name if len(paths) == 1 else f"{len(paths)} files"
    ui.notify(f"{added} added to the queue")
    return True
